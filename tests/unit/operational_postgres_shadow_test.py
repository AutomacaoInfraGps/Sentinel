import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from queue import Queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from services.operational_postgres import (
    ShadowWorker, SnapshotError, _safe_warning, enqueue_firewall_snapshot,
    inspect_snapshot, prepare_snapshot, shadow_enabled, write_snapshot,
)
from scripts.database.sync_firewall_cache import main


ROOT = Path(__file__).resolve().parents[2]


class Cursor:
    def __init__(self, *, current=None, counts=(1, 1), fail_license=False):
        self.current = current
        self.counts = counts
        self.fail_license = fail_license
        self.calls = []
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        if sql.startswith("SELECT current_database"):
            self.result = ("sentinel", "sentinel_collector", 5433)
        elif "FROM operacional.sincronizacoes WHERE" in sql:
            self.result = self.current
        elif "RETURNING id" in sql:
            self.result = (42,)
        elif "SELECT count(*) FROM operacional.firewalls" in sql:
            self.result = self.counts
        if self.fail_license and "INSERT INTO operacional.licencas_firewall" in sql:
            raise RuntimeError("PRIVATE_BOUND_VALUE")

    def fetchone(self):
        return self.result


class Connection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.committed = self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.committed = kind is None
        self.rolled_back = kind is not None
        return False

    def cursor(self):
        return self.fake_cursor


class OperationalPostgresShadowTests(unittest.TestCase):
    def setUp(self):
        self.firewall = {
            "nome": "FGT-TEST", "serial": "SERIAL-TEST", "ip": "192.0.2.1",
            "ultima_verificacao": "2026-11-13T08:00:00", "status": "warning",
            "status_disponibilidade": "online",
            "licencas": [{"nome": "forticare", "tipo": "forticare", "status": "registered",
                          "expiracao": "2026-12-21", "dias_restantes": 38}],
        }
        self.payload = {
            "success": True, "atualizado_em": "2026-11-13T08:01:00",
            "firewalls_por_regional": {"REG_TEST": [self.firewall]},
        }

    def snapshot(self):
        return prepare_snapshot(self.payload)

    def test_precision_and_original_status_are_preserved(self):
        snapshot = self.snapshot()
        row = snapshot.firewalls[0]
        self.assertEqual(snapshot.published_at.hour, 11)
        self.assertEqual(row[7].hour, 11)
        self.assertEqual(row[8:11], ("warning", "online", True))
        self.assertIsNone(row[11][0][4])
        self.assertEqual(row[11][0][5].isoformat(), "2026-12-21")
        self.assertEqual(row[11][0][6], 38)

    def test_missing_expiry_is_not_invented_from_reported_days(self):
        self.firewall["licencas"][0].update(expiracao="N/A", dias_restantes=365)
        license_row = self.snapshot().firewalls[0][11][0]
        self.assertEqual(license_row[4:7], (None, None, 365))

    def test_previous_license_uses_previous_collection_not_current_attempt(self):
        self.firewall["licencas"][0].update(
            dados_anteriores=True, ultima_coleta_valida="2026-11-10T08:00:00",
            status="indisponivel", status_ultima_coleta_valida="registered",
        )
        row = self.snapshot().firewalls[0][11][0]
        self.assertEqual(row[7].day, 10)
        self.assertTrue(row[11])
        self.assertEqual(row[12].day, 10)
        self.assertEqual(row[2], "indisponivel")
        self.assertEqual(row[13], "registered")

    def test_previous_license_without_known_collection_stays_unknown(self):
        self.firewall["licencas"][0]["dados_anteriores"] = True
        self.assertIsNone(self.snapshot().firewalls[0][11][0][7])

    def test_invalid_snapshots_do_not_become_empty_success(self):
        for payload in ({}, {**self.payload, "success": False}, {**self.payload, "firewalls_por_regional": {}}, {**self.payload, "firewalls_por_regional": {"REG_TEST": []}}):
            with self.assertRaises(SnapshotError):
                prepare_snapshot(payload)

    def test_duplicate_devices_and_licenses_are_rejected(self):
        self.payload["firewalls_por_regional"]["REG_OTHER"] = [deepcopy(self.firewall)]
        with self.assertRaises(SnapshotError):
            self.snapshot()
        del self.payload["firewalls_por_regional"]["REG_OTHER"]
        self.firewall["licencas"].append(deepcopy(self.firewall["licencas"][0]))
        with self.assertRaises(SnapshotError):
            self.snapshot()

    def test_source_values_are_validated_not_silently_coerced(self):
        for field, value in (("serial", "N/A"), ("nome", "\x00"), ("ip", "bad-address"), ("ultima_verificacao", "invalid")):
            original = self.firewall.get(field)
            self.firewall[field] = value
            with self.subTest(field=field), self.assertRaises(SnapshotError):
                self.snapshot()
            self.firewall[field] = original
        self.firewall["licencas"][0]["dias_restantes"] = True
        with self.assertRaises(SnapshotError):
            self.snapshot()

    def test_unknown_fields_and_credentials_do_not_enter_digest_or_rows(self):
        first = self.snapshot()
        self.firewall.update(senha="PRIVATE_VALUE", token="PRIVATE_VALUE")
        self.firewall["licencas"][0]["private"] = "PRIVATE_VALUE"
        second = self.snapshot()
        self.assertEqual(first.digest, second.digest)
        self.assertNotIn("PRIVATE_VALUE", repr(second.firewalls))
        self.assertNotIn("SERIAL-TEST", repr(second))

    def test_write_is_parameterized_and_absence_is_not_deletion(self):
        snapshot = self.snapshot()
        cursor = Cursor()
        with Connection(cursor) as connection:
            self.assertEqual(write_snapshot(connection, snapshot), "sincronizado")
        self.assertTrue(connection.committed)
        self.assertTrue(any("SET presente_no_snapshot = false" in sql for sql, _ in cursor.calls))
        for sql, params in cursor.calls:
            self.assertNotIn("DELETE", sql)
            self.assertNotIn("TRUNCATE", sql)
            self.assertNotIn("REG_TEST", sql)
            self.assertNotIn("SERIAL-TEST", sql)
            if params is not None:
                self.assertEqual(sql.count("%s"), len(params))
        self.assertIn("INSERT INTO operacional.sincronizacoes", cursor.calls[-1][0])

    def test_duplicate_or_older_publication_cannot_overwrite_current_state(self):
        snapshot = self.snapshot()
        for current, expected in (((snapshot.published_at, snapshot.digest), "sem_alteracoes"), ((snapshot.published_at + timedelta(minutes=1), "0" * 64), "publicacao_antiga_ignorada")):
            cursor = Cursor(current=current)
            self.assertEqual(write_snapshot(Connection(cursor), snapshot), expected)
            self.assertFalse(any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in cursor.calls))

    def test_failure_or_count_mismatch_rolls_back_without_publication_marker(self):
        for kwargs in ({"fail_license": True}, {"counts": (1, 0)}):
            connection = Connection(Cursor(**kwargs))
            with self.assertRaises((SnapshotError, RuntimeError)):
                with connection:
                    write_snapshot(connection, self.snapshot())
            self.assertTrue(connection.rolled_back)
            self.assertFalse(any("INSERT INTO operacional.sincronizacoes" in sql for sql, _ in connection.fake_cursor.calls))

    def test_read_only_check_does_not_write_or_lock_tables(self):
        cursor = Cursor(counts=(49, 49))
        result = inspect_snapshot(Connection(cursor), self.snapshot())
        self.assertEqual(result["modo"], "conferencia_sem_gravacao")
        self.assertEqual(result["banco_firewalls_presentes"], 49)
        self.assertFalse(any(sql.startswith(("LOCK", "UPDATE", "INSERT")) for sql, _ in cursor.calls))

    def test_flag_is_disabled_when_absent_malformed_or_not_boolean_true(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flag.json"
            self.assertFalse(shadow_enabled(path))
            for content in ('{"enabled": "true"}', '{"enabled": false}', 'broken', '[]'):
                path.write_text(content, encoding="utf-8")
                self.assertFalse(shadow_enabled(path))
            path.write_text('{"enabled": true}', encoding="utf-8")
            self.assertTrue(shadow_enabled(path))

    def test_disabled_publish_does_not_validate_connect_or_start_worker(self):
        with patch("services.operational_postgres.shadow_enabled", return_value=False), patch("services.operational_postgres._worker") as worker, patch("services.operational_postgres.prepare_snapshot") as prepare:
            self.assertFalse(enqueue_firewall_snapshot(self.payload, Mock()))
            worker.submit.assert_not_called()
            prepare.assert_not_called()

    def test_queued_snapshot_is_independent_of_later_user_scope_mutation(self):
        with patch("services.operational_postgres.shadow_enabled", return_value=True), patch("services.operational_postgres._worker") as worker:
            self.assertTrue(enqueue_firewall_snapshot(self.payload, Mock()))
            snapshot = worker.submit.call_args.args[0]
            self.firewall["licencas"].clear()
            self.payload["firewalls_por_regional"].clear()
            self.assertEqual(snapshot.license_count, 1)
            self.assertEqual(len(snapshot.firewalls), 1)

    def test_worker_queue_is_bounded_and_replaces_pending_not_inflight(self):
        worker = ShadowWorker()
        with patch("services.operational_postgres.threading.Thread") as thread:
            worker.submit(self.snapshot(), Mock())
            self.payload["atualizado_em"] = "2026-11-13T08:02:00"
            newest = self.snapshot()
            worker.submit(newest, Mock())
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(worker.pending.qsize(), 1)
        self.assertEqual(worker.pending.get_nowait()[0].digest, newest.digest)

    def test_older_submission_cannot_displace_newer_pending_snapshot(self):
        worker = ShadowWorker()
        older = self.snapshot()
        self.payload["atualizado_em"] = "2026-11-13T08:02:00"
        newest = self.snapshot()
        with patch("services.operational_postgres.threading.Thread"):
            worker.submit(newest, Mock())
            worker.submit(older, Mock())
        self.assertEqual(worker.pending.get_nowait()[0].digest, newest.digest)

    def test_worker_sql_failure_is_contained_and_not_logged_with_values(self):
        worker, logger = ShadowWorker(), Mock()
        worker.pending = Mock()
        worker.pending.get.side_effect = [(self.snapshot(), logger), StopIteration()]
        with patch("services.operational_postgres.shadow_enabled", return_value=True), patch("services.operational_postgres.connect_collector", side_effect=RuntimeError("PRIVATE_PASSWORD")):
            with self.assertRaises(StopIteration):
                worker._run()
        worker.pending.task_done.assert_called_once()
        self.assertNotIn("PRIVATE_PASSWORD", str(logger.warning.call_args))

    def test_unsafe_error_sqlstate_is_never_echoed(self):
        logger = Mock()
        error = RuntimeError("PRIVATE_PASSWORD")
        error.sqlstate = "PRIVATE_PASSWORD"
        _safe_warning(logger, "falha_sincronizacao", error)
        self.assertNotIn("PRIVATE_PASSWORD", str(logger.warning.call_args))

    def test_web_cache_stays_saved_if_shadow_callback_fails(self):
        module = ast.parse((ROOT / "web_config.py").read_text(encoding="utf-8"))
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_salvar_cache_dashboard")
        isolated = ast.Module(body=[function], type_ignores=[])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = Mock()
            namespace = {"PROJECT_ROOT": root, "json": json, "current_app": SimpleNamespace(logger=logger)}
            exec(compile(isolated, "web_cache_isolated", "exec"), namespace)
            path = root / "output" / "dashboard_firewalls_cache.json"

            def fail_after_check(payload, passed_logger):
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.payload)
                raise RuntimeError("PRIVATE_PASSWORD")

            with patch("services.operational_postgres.enqueue_firewall_snapshot", side_effect=fail_after_check):
                namespace["_salvar_cache_dashboard"]("firewalls", self.payload)
            self.assertTrue(path.exists())
            self.assertNotIn("PRIVATE_PASSWORD", str(logger.warning.call_args))

    def test_cli_write_requires_digest_before_connecting(self):
        with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), patch("scripts.database.sync_firewall_cache.connect_collector") as connect, redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--apply"]), 1)
            connect.assert_not_called()

    def test_cli_default_is_read_only_and_uses_no_interactive_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text(json.dumps(self.payload), encoding="utf-8")
            connection = Connection(Cursor())
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), patch("scripts.database.sync_firewall_cache.connect_collector", return_value=connection) as connect, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--cache", str(path)]), 0)
            connect.assert_called_once_with(read_only=True)
            self.assertEqual(json.loads(output.getvalue())["modo"], "conferencia_sem_gravacao")

    def test_schema_has_guard_presence_and_no_destructive_or_extra_grants(self):
        source = (ROOT / "scripts/database/sql/001_firewall_shadow_sync.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'sentinel'", source)
        self.assertIn("inet_server_port() IS DISTINCT FROM 5433", source)
        self.assertIn("E:/Sentinel/PostgreSQL/data", source)
        self.assertIn("NULLS NOT DISTINCT", source)
        self.assertIn("ADD COLUMN dados_anteriores", source)
        self.assertNotIn("DELETE", source)
        self.assertNotIn("TRUNCATE", source)
        self.assertNotIn("GRANT ALL", source)


if __name__ == "__main__":
    unittest.main()
