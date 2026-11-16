from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database.import_firewall_cache import ImportErrorSafe
from scripts.database.import_server_catalog import build_catalog, inspect_catalog, main, write_catalog


def payload():
    return {"regionais": {"REG_A": {"nome": "Regional A", "servidores": [{
        "id": "server1", "nome": "Servidor", "ip": "192.0.2.1", "status": "online",
        "ativo": True, "ultima_verificacao": "2026-11-16T08:05:00", "tempo_resposta": 0.2,
        "usuario": "PRIVATE_USER", "senha": {"credential_ref": "PRIVATE_REFERENCE"},
    }]}, "REG_B": {"nome": "Regional B", "servidores": []}}}


def build(data=None):
    return build_catalog(json.dumps(data or payload()).encode(), "America/Sao_Paulo")


def connection(results):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = results
    return conn, cursor


class ServerCatalogTest(unittest.TestCase):
    def test_projection_ignores_credentials_and_preserves_timestamp(self):
        catalog = build()
        self.assertEqual(len(catalog.regionals), 2)
        self.assertEqual(len(catalog.servers), 1)
        self.assertNotIn("PRIVATE", repr(catalog.servers))
        self.assertNotIn("Servidor", repr(catalog))
        self.assertEqual(catalog.servers[0][10], datetime(2026, 11, 16, 11, 5, tzinfo=timezone.utc))
        self.assertFalse(catalog.summary()["sincronizacao_automatica_servidores"])

    def test_missing_time_remains_null(self):
        data = payload()
        del data["regionais"]["REG_A"]["servidores"][0]["ultima_verificacao"]
        catalog = build(data)
        self.assertIsNone(catalog.servers[0][10])
        self.assertEqual(catalog.summary()["servidores_sem_data_de_observacao"], 1)

    def test_empty_or_invalid_categories_rejected(self):
        for data in ({}, {"regionais": {}}, {"regionais": {"REG_A": {}}},
                     {"regionais": {"REG_A": {"servidores": []}}}):
            with self.subTest(data=data), self.assertRaises(ImportErrorSafe):
                build_catalog(json.dumps(data).encode(), "America/Sao_Paulo")

    def test_invalid_fields_no_silent_coercion(self):
        for key, value in (("id", ""), ("id", 123), ("nome", ""), ("ip", "PRIVATE_BAD_IP"),
                           ("ativo", "false"), ("tempo_resposta", True), ("tempo_resposta", -1),
                           ("tempo_resposta", float("nan")), ("status", "X" * 121),
                           ("ultima_verificacao", "invalid")):
            with self.subTest(key=key, value=value):
                data = payload()
                data["regionais"]["REG_A"]["servidores"][0][key] = value
                with self.assertRaises(ImportErrorSafe) as error:
                    build(data)
                self.assertNotIn("PRIVATE", str(error.exception))

    def test_duplicate_json_and_server_identity_rejected(self):
        with self.assertRaises(ImportErrorSafe):
            build_catalog(b'{"regionais":{},"regionais":{}}', "America/Sao_Paulo")
        data = payload()
        records = data["regionais"]["REG_A"]["servidores"]
        duplicate = deepcopy(records[0])
        duplicate["id"] = duplicate["id"].upper()
        records.append(duplicate)
        with self.assertRaises(ImportErrorSafe):
            build(data)

    def test_write_checks_identity_locks_and_counts(self):
        catalog = build()
        conn, cursor = connection([("sentinel", "sentinel_collector", 5433), (0,), (1,), (2,)])
        write_catalog(conn, catalog)
        calls = cursor.execute.call_args_list
        statements = [call.args[0] for call in calls]
        self.assertIn("LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE", statements)
        self.assertIn("LOCK TABLE operacional.servidores IN ROW EXCLUSIVE MODE", statements)
        self.assertFalse(any("operacional.firewalls" in sql or "operacional.licencas_firewall" in sql for sql in statements))
        self.assertFalse(any("DELETE" in sql or "TRUNCATE" in sql for sql in statements))
        self.assertTrue(any("COALESCE(operacional.regionais.nome" in sql for sql in statements))
        self.assertNotIn("PRIVATE", repr(calls))
        conn.commit.assert_not_called()

    def test_server_lock_compatible_with_insert_only_role(self):
        conn, cursor = connection([("sentinel", "sentinel_collector", 5433), (0,), (1,), (2,)])

        def enforce_grants(sql, *parameters):
            if sql.startswith("LOCK TABLE operacional.servidores") and "IN ROW EXCLUSIVE MODE" not in sql:
                raise PermissionError("PRIVATE_DRIVER_MESSAGE")

        cursor.execute.side_effect = enforce_grants
        write_catalog(conn, build())

    def test_cli_driver_error_reports_phase_and_sqlstate_without_values(self):
        class DriverFailure(Exception):
            sqlstate = "42501"

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            source.write_text(json.dumps(payload()), encoding="utf-8")
            catalog = build_catalog(source.read_bytes(), "America/Sao_Paulo")
            conn, cursor = connection([("sentinel", "sentinel_collector", 5433)])
            conn.__enter__.return_value = conn

            def fail_lock(sql, *parameters):
                if sql.startswith("LOCK TABLE"):
                    raise DriverFailure("PRIVATE_PASSWORD")

            cursor.execute.side_effect = fail_lock
            output = io.StringIO()
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), \
                    patch("services.operational_postgres.connect_collector", return_value=conn), \
                    redirect_stderr(output):
                result = main(["--source", str(source), "--source-timezone", "America/Sao_Paulo",
                               "--apply", "--expected-sha256", catalog.digest])
            self.assertEqual(result, 1)
            self.assertIn("bloqueio_tabelas", output.getvalue())
            self.assertIn("42501", output.getvalue())
            self.assertNotIn("PRIVATE", output.getvalue())

    def test_existing_servers_and_wrong_instance_fail_before_inserts(self):
        for results in ([('sentinel', 'sentinel_collector', 5433), (1,)],
                        [('aegis', 'sentinel_collector', 5432)]):
            conn, cursor = connection(results)
            with self.assertRaises(ImportErrorSafe):
                write_catalog(conn, build())
            self.assertFalse(any("INSERT" in call.args[0] for call in cursor.execute.call_args_list))

    def test_bad_final_counts_raise_for_caller_to_rollback(self):
        conn, _ = connection([("sentinel", "sentinel_collector", 5433), (0,), (0,)])
        with self.assertRaises(ImportErrorSafe):
            write_catalog(conn, build())

    def test_inspection_read_only(self):
        conn, cursor = connection([("sentinel", "sentinel_collector", 5433), (49, 0)])
        result = inspect_catalog(conn)
        self.assertTrue(result["tabela_servidores_vazia"])
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "SET TRANSACTION READ ONLY")

    def test_default_simulation_never_connects_and_hash_guard_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            source.write_text(json.dumps(payload()), encoding="utf-8")
            argv = ["--source", str(source), "--source-timezone", "America/Sao_Paulo"]
            with patch("services.operational_postgres.connect_collector") as connect:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(argv), 0)
                connect.assert_not_called()
                self.assertNotIn("PRIVATE", output.getvalue())
                with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}):
                    self.assertEqual(main([*argv, "--apply", "--expected-sha256", "wrong"]), 1)
                connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
