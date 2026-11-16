from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gerenciar_regionais import GerenciadorRegionais
from scripts.database.import_firewall_cache import ImportErrorSafe
from scripts.database.sync_server_catalog import main as sync_main
from services.operational_postgres import SnapshotError
from services.operational_server_postgres import (
    CONFIG_PATH, PROJECT_ROOT, ServerShadowWorker, enqueue_server_snapshot,
    inspect_server_snapshot, prepare_server_snapshot, write_server_snapshot,
)


def payload():
    return {"configuracao": {"ultima_atualizacao": "2026-11-16T09:00:00"},
            "regionais": {"REG_A": {"nome": "Regional A", "servidores": [{
                "id": "srv1", "nome": "Server", "ip": "192.0.2.1", "status": "online",
                "ultima_verificacao": "2026-11-16T08:30:00", "ativo": True,
                "senha": "PRIVATE_PASSWORD", "usuario": "PRIVATE_USER",
            }]}}}


class Cursor:
    def __init__(self, current=None, counts=(1, 1), failure=None):
        self.current, self.counts, self.failure = current, counts, failure
        self.calls, self.result = [], None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.failure and self.failure in sql:
            raise RuntimeError("PRIVATE_DRIVER_VALUE")
        if sql.startswith("SELECT current_database"):
            self.result = ("sentinel", "sentinel_collector", 5433)
        elif "SELECT cadastro_publicado_em" in sql:
            self.result = self.current
        elif "SELECT count(*)" in sql:
            self.result = self.counts

    def fetchone(self):
        return self.result


def connection(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class ServerShadowTest(unittest.TestCase):
    def test_projection_excludes_secrets_and_is_detached(self):
        raw = payload()
        snapshot = prepare_server_snapshot(raw)
        changed = deepcopy(raw)
        changed["regionais"]["REG_A"]["servidores"][0]["senha"] = "OTHER_SECRET"
        self.assertEqual(snapshot.digest, prepare_server_snapshot(changed).digest)
        self.assertNotIn("PRIVATE", repr(snapshot.servers))
        self.assertNotIn(repr(snapshot.servers), repr(snapshot))
        raw["regionais"]["REG_A"]["servidores"][0]["nome"] = "changed"
        self.assertEqual(snapshot.servers[0][2], "Server")
        self.assertEqual(snapshot.published_at.hour, 12)
        self.assertEqual(snapshot.servers[0][10].hour, 11)

    def test_timestamp_and_malformed_source_fail_closed(self):
        for value in (None, "bad"):
            raw = payload()
            raw["configuracao"]["ultima_atualizacao"] = value
            with self.assertRaises((SnapshotError, ImportErrorSafe)):
                prepare_server_snapshot(raw)
        with self.assertRaises(ImportErrorSafe):
            prepare_server_snapshot({"configuracao": payload()["configuracao"], "regionais": {}})

    def test_zero_servers_explicitly_allowed_for_removals(self):
        raw = payload()
        raw["regionais"]["REG_A"]["servidores"] = []
        snapshot = prepare_server_snapshot(raw)
        self.assertEqual(snapshot.summary()["servidores"], 0)
        cursor = Cursor(counts=(1, 0))
        self.assertEqual(write_server_snapshot(connection(cursor), snapshot), "sincronizado")

    def test_same_digest_or_older_publication_never_updates(self):
        snapshot = prepare_server_snapshot(payload())
        cases = [((snapshot.published_at, snapshot.digest), "sem_alteracoes"),
                 ((snapshot.published_at + timedelta(seconds=1), "other"), "publicacao_antiga_ignorada")]
        for current, expected in cases:
            cursor = Cursor(current=current)
            self.assertEqual(write_server_snapshot(connection(cursor), snapshot), expected)
            self.assertFalse(any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in cursor.calls))

    def test_same_time_conflicting_content_rejected(self):
        snapshot = prepare_server_snapshot(payload())
        cursor = Cursor(current=(snapshot.published_at, "other"))
        with self.assertRaises(SnapshotError):
            write_server_snapshot(connection(cursor), snapshot)

    def test_transaction_sql_presence_no_delete_and_marker_last(self):
        snapshot = prepare_server_snapshot(payload())
        cursor = Cursor()
        conn = connection(cursor)
        self.assertEqual(write_server_snapshot(conn, snapshot), "sincronizado")
        statements = [sql for sql, _ in cursor.calls]
        self.assertIn("SET TRANSACTION ISOLATION LEVEL READ COMMITTED", statements)
        self.assertTrue(any("SET presente_no_snapshot=false" in sql for sql in statements))
        self.assertTrue(any("EXCLUDED.ultima_verificacao >= s.ultima_verificacao" in sql for sql in statements))
        self.assertTrue(statements[-1].startswith("INSERT INTO operacional.sincronizacoes_servidores"))
        self.assertFalse(any("DELETE" in sql or "TRUNCATE" in sql for sql in statements))
        self.assertFalse(any("operacional.firewalls" in sql or "operacional.licencas_firewall" in sql for sql in statements))
        self.assertNotIn("PRIVATE", repr(cursor.calls))
        conn.commit.assert_not_called()

    def test_bad_counts_and_insert_failure_never_publish_marker(self):
        snapshot = prepare_server_snapshot(payload())
        for cursor in (Cursor(counts=(1, 0)), Cursor(failure="INSERT INTO operacional.servidores AS")):
            with self.assertRaises((SnapshotError, RuntimeError)):
                write_server_snapshot(connection(cursor), snapshot)
            self.assertFalse(any(sql.startswith("INSERT INTO operacional.sincronizacoes_servidores")
                                 for sql, _ in cursor.calls))

    def test_inspection_read_only(self):
        snapshot = prepare_server_snapshot(payload())
        cursor = Cursor(current=(snapshot.published_at, snapshot.digest))
        result = inspect_server_snapshot(connection(cursor), snapshot)
        self.assertTrue(result["conteudo_ja_sincronizado"])
        self.assertIn("READ ONLY", cursor.calls[0][0])
        self.assertFalse(any(sql.startswith(("LOCK", "UPDATE", "INSERT")) for sql, _ in cursor.calls))

    def test_disabled_flag_and_noncanonical_source_not_enqueued(self):
        with patch("services.operational_server_postgres.shadow_enabled", return_value=False), \
                patch("services.operational_server_postgres._worker") as worker:
            self.assertFalse(enqueue_server_snapshot(payload(), PROJECT_ROOT / "estrutura_regionais.json", MagicMock()))
            worker.submit.assert_not_called()
        with patch("services.operational_server_postgres.shadow_enabled", return_value=True), \
                patch("services.operational_server_postgres._worker") as worker:
            self.assertFalse(enqueue_server_snapshot(payload(), PROJECT_ROOT / "other.json", MagicMock()))
            worker.submit.assert_not_called()

    def test_hook_after_successful_replace_and_sql_exception_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "regionais.json"
            manager = GerenciadorRegionais(str(source))
            manager.regionais = payload()

            def fail_after_save(data, path, logger):
                self.assertTrue(Path(path).exists())
                self.assertIn("REG_A", json.loads(source.read_text(encoding="utf-8"))["regionais"])
                raise RuntimeError("PRIVATE_ERROR")

            with patch("services.operational_server_postgres.enqueue_server_snapshot", side_effect=fail_after_save), \
                    self.assertLogs("gerenciar_regionais", level="WARNING") as logs:
                manager.salvar_regionais()
            self.assertNotIn("PRIVATE", str(logs.output))

    def test_failed_json_replace_never_calls_hook(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = GerenciadorRegionais(str(Path(folder) / "regional.json"))
            manager.regionais = payload()
            with patch("gerenciar_regionais.os.replace", side_effect=OSError("failure")), \
                    patch("services.operational_server_postgres.enqueue_server_snapshot") as enqueue:
                with self.assertRaises(OSError):
                    manager.salvar_regionais()
                enqueue.assert_not_called()

    def test_worker_failure_safe_logging_and_disabled_skips_connection(self):
        snapshot = prepare_server_snapshot(payload())
        for enabled in (True, False):
            worker = ServerShadowWorker()
            worker.pending = MagicMock()
            logger = MagicMock()
            worker.pending.get.side_effect = [(snapshot, logger), SystemExit()]
            with patch("services.operational_server_postgres.shadow_enabled", return_value=enabled), \
                    patch("services.operational_server_postgres.connect_collector") as connect, \
                    patch("services.operational_server_postgres.write_server_snapshot", side_effect=RuntimeError("PRIVATE")):
                with self.assertRaises(SystemExit):
                    worker._run()
                if enabled:
                    self.assertNotIn("PRIVATE", repr(logger.warning.call_args))
                else:
                    connect.assert_not_called()
            worker.pending.task_done.assert_called_once()

    def test_migration_has_update_for_strong_lock_and_default_disabled(self):
        sql = (PROJECT_ROOT / "scripts/database/sql/003_server_shadow_sync.sql").read_text()
        self.assertIn("GRANT UPDATE ON operacional.servidores TO sentinel_collector", sql)
        self.assertNotIn("GRANT DELETE", sql)
        self.assertNotIn("GRANT ALL", sql)
        example = PROJECT_ROOT / "scripts/database/operational-postgres-servers-shadow.example.json"
        self.assertIs(json.loads(example.read_text())["enabled"], False)
        self.assertNotEqual(CONFIG_PATH.name, "operational-postgres-shadow.json")

    def test_cli_default_read_only_and_digest_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            source.write_text(json.dumps(payload()), encoding="utf-8")
            cursor = Cursor()
            conn = connection(cursor)
            conn.__enter__.return_value = conn
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), \
                    patch("scripts.database.sync_server_catalog.connect_collector", return_value=conn) as connect:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(sync_main(["--source", str(source)]), 0)
                connect.assert_called_once_with(read_only=True)
                self.assertEqual(json.loads(output.getvalue())["modo"], "conferencia_sem_gravacao")
                connect.reset_mock()
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(sync_main(["--source", str(source), "--apply",
                                                "--expected-digest", "wrong"]), 1)
                connect.assert_not_called()

    def test_cli_failure_does_not_leak_driver_message(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            source.write_text(json.dumps(payload()), encoding="utf-8")
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), \
                    patch("scripts.database.sync_server_catalog.connect_collector",
                          side_effect=RuntimeError("PRIVATE_PASSWORD")):
                output = io.StringIO()
                with redirect_stderr(output):
                    self.assertEqual(sync_main(["--source", str(source)]), 1)
                self.assertIn("conexao", output.getvalue())
                self.assertNotIn("PRIVATE", output.getvalue())

    def test_cli_wrong_host_never_reads_source_or_connects(self):
        with patch.dict("os.environ", {"COMPUTERNAME": "OTHER"}), \
                patch("scripts.database.sync_server_catalog.connect_collector") as connect, \
                redirect_stderr(io.StringIO()):
            self.assertEqual(sync_main(["--source", "not-present.json"]), 1)
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
