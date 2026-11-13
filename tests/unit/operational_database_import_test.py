from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.database.import_firewall_cache import (
    ImportErrorSafe, _database_error, _read_password, apply_plan, build_plan, main, write_empty_database,
)


class FakeCursor:
    def __init__(self, *, identity=("sentinel", "sentinel_collector", 5433), initial=(0, 0, 0), final=(1, 1, 1), fail_insert=False):
        self.identity = identity
        self.counts = iter((initial, final))
        self.fail_insert = fail_insert
        self.calls = []
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql.startswith("SELECT current_database"):
            self.result = self.identity
        elif "SELECT count(*) FROM operacional.regionais" in sql:
            self.result = next(self.counts)
        elif "has_table_privilege" in sql:
            self.result = (True, True, True, True, True)
        elif "INSERT INTO operacional.firewalls" in sql:
            self.result = (42,)
        if self.fail_insert and "INSERT INTO operacional.licencas_firewall" in sql:
            raise RuntimeError("DO_NOT_PRINT_BOUND_VALUES")

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.committed = self.rolled_back = False

    def cursor(self):
        return self.fake_cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.committed = exc_type is None
        self.rolled_back = exc_type is not None
        return False


class OperationalDatabaseImportTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "nome": "FGT-TEST", "serial": "Serial-Test", "ip": "192.0.2.1",
            "ultima_verificacao": "2026-11-12T10:00:00",
            "senha": "SECRET_NOT_IMPORTED", "token": "SECRET_NOT_IMPORTED",
            "licencas": [{"nome": "forticare", "tipo": "forticare", "dias_restantes": 39,
                          "expiracao": "2026-12-21", "notificacao_critica": True,
                          "private": "SECRET_NOT_IMPORTED"}],
        }
        self.payload = {"firewalls_por_regional": {"REG_TEST": [self.record]}}

    def raw(self):
        return json.dumps(self.payload).encode()

    def plan(self):
        return build_plan(self.raw(), "America/Sao_Paulo")

    def test_password_pipe_preserves_dollar_unicode_and_spaces_without_prompt(self):
        password = '  Test$"\\\u00e7\u00e3o  '
        stream = io.TextIOWrapper(io.BytesIO((json.dumps(password, ensure_ascii=False) + "\r\n").encode("utf-8")), encoding="utf-8")
        with stream, patch("sys.stdin", stream), patch("getpass.getpass") as prompt:
            self.assertEqual(_read_password(from_stdin=True), password)
            prompt.assert_not_called()

    def test_password_pipe_rejects_malformed_or_empty_values_without_echo(self):
        for raw in (b'', b'null', b'{}', b'""', b'INVALID_SECRET', b'"\\u0000"', b'x' * 65537):
            stream = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
            with stream, patch("sys.stdin", stream):
                with self.assertRaises(ImportErrorSafe) as caught:
                    _read_password(from_stdin=True)
            self.assertNotIn("INVALID_SECRET", str(caught.exception))

    def test_password_pipe_supports_transactional_writing_without_getpass(self):
        password = 'Synthetic$Password'
        stream = io.TextIOWrapper(io.BytesIO(json.dumps(password).encode("utf-8")), encoding="utf-8")
        connection = FakeConnection(FakeCursor())
        captures = {}

        def connect(**values):
            captures.update(values)
            return connection

        with stream, patch("sys.stdin", stream), patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}), patch("getpass.getpass") as prompt:
            apply_plan(self.plan(), password_from_stdin=True)
        self.assertTrue(connection.committed)
        self.assertEqual(captures["password"], password)
        prompt.assert_not_called()

    def test_cli_rejects_password_pipe_without_database_mode_before_prompt(self):
        with patch("getpass.getpass") as prompt, redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--source-timezone", "UTC", "--password-stdin"]), 1)
            prompt.assert_not_called()

    def test_cli_pipe_apply_still_requires_reviewed_hash_and_rigel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_bytes(self.raw())
            base = ["--cache", str(path), "--source-timezone", "America/Sao_Paulo", "--apply", "--password-stdin"]
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), patch("scripts.database.import_firewall_cache.apply_plan") as apply, redirect_stderr(io.StringIO()):
                for options in ([], ["--expected-sha256", "0" * 64]):
                    self.assertEqual(main([*base, *options]), 1)
                apply.assert_not_called()
            args = [*base, "--expected-sha256", self.plan().sha256]
            with patch.dict("os.environ", {"COMPUTERNAME": "DEVELOPMENT"}), patch("scripts.database.import_firewall_cache.apply_plan") as apply, redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 1)
                apply.assert_not_called()
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), patch("scripts.database.import_firewall_cache.apply_plan") as apply, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
                self.assertTrue(apply.call_args.kwargs["password_from_stdin"])
                self.assertFalse(apply.call_args.kwargs.get("check_only", False))
                self.assertEqual(json.loads(output.getvalue())["modo"], "carga_inicial_confirmada")

    def test_naive_collection_becomes_utc_with_declared_origin(self):
        plan = self.plan()
        license_values = plan.firewalls[0][7][0]
        self.assertEqual(license_values[7], datetime(2026, 11, 12, 13, tzinfo=timezone.utc))
        self.assertEqual(license_values[4:6], (None, date(2026, 12, 21)))
        self.assertEqual(license_values[6], 39)
        self.assertEqual(plan.firewalls[0][1], "SERIAL-TEST")

    def test_known_offset_is_not_reinterpreted_as_brasilia(self):
        self.record["ultima_verificacao"] = "2026-11-12T10:00:00+01:00"
        self.assertEqual(self.plan().firewalls[0][7][0][7].hour, 9)

    def test_unix_expiry_is_an_instant_not_server_local_time(self):
        self.record["licencas"][0]["expiracao"] = 1797840000
        values = self.plan().firewalls[0][7][0]
        self.assertEqual(values[4], datetime.fromtimestamp(1797840000, timezone.utc))
        self.assertIsNone(values[5])

    def test_missing_expiry_stays_null_and_reported_days_stay_observations(self):
        self.record["licencas"][0].update(expiracao="N/A", dias_restantes=365, origem="device_data")
        values = self.plan().firewalls[0][7][0]
        self.assertEqual(values[4:6], (None, None))
        self.assertEqual(values[6], 365)
        self.assertEqual(self.plan().summary["licencas_sem_vencimento"], 1)

    def test_absent_observation_is_not_replaced_with_import_time(self):
        del self.record["ultima_verificacao"]
        self.assertIsNone(self.plan().firewalls[0][7][0][7])
        self.assertEqual(self.plan().summary["coletas_sem_data"], 1)

    def test_secrets_and_raw_records_never_enter_plan_or_summary(self):
        plan = self.plan()
        self.assertNotIn("SECRET_NOT_IMPORTED", repr(plan.firewalls))
        self.assertNotIn("SECRET_NOT_IMPORTED", json.dumps(plan.summary))
        self.assertNotIn("SERIAL-TEST", repr(plan))

    def test_nonexistent_and_ambiguous_historical_local_times_are_rejected(self):
        for value in ("2018-11-04T00:30:00", "2019-02-16T23:30:00"):
            self.record["ultima_verificacao"] = value
            with self.assertRaises(ImportErrorSafe):
                self.plan()

    def test_unknown_zone_and_invalid_cache_are_rejected(self):
        with self.assertRaises(ImportErrorSafe):
            build_plan(self.raw(), "Not/AZone")
        with self.assertRaises(ImportErrorSafe):
            build_plan(b'{"firewalls_por_regional": {}, "firewalls_por_regional": {}}', "UTC")
        self.payload["firewalls_por_regional"]["REG_OTHER"] = [deepcopy(self.record)]
        with self.assertRaises(ImportErrorSafe):
            self.plan()

    def test_simulation_never_connects_or_prompts_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            raw = self.raw()
            path.write_bytes(raw)
            with patch("scripts.database.import_firewall_cache.apply_plan") as apply, patch("getpass.getpass") as password, redirect_stdout(io.StringIO()):
                result = main(["--cache", str(path), "--source-timezone", "America/Sao_Paulo"])
            self.assertEqual(result, 0)
            apply.assert_not_called()
            password.assert_not_called()
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_apply_requires_matching_reviewed_hash_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_bytes(self.raw())
            with patch("scripts.database.import_firewall_cache.apply_plan") as apply, redirect_stderr(io.StringIO()):
                for options in ([], ["--expected-sha256", "0" * 64]):
                    self.assertEqual(main(["--cache", str(path), "--source-timezone", "America/Sao_Paulo", "--apply", *options]), 1)
                apply.assert_not_called()

    def test_apply_refuses_other_computers_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_bytes(self.raw())
            with patch.dict("os.environ", {"COMPUTERNAME": "DEVELOPMENT"}), patch("scripts.database.import_firewall_cache.apply_plan") as apply, redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--cache", str(path), "--source-timezone", "America/Sao_Paulo", "--apply", "--expected-sha256", self.plan().sha256]), 1)
                apply.assert_not_called()

    def test_sql_is_parameterized_and_links_license_to_returned_id(self):
        cursor = FakeCursor()
        write_empty_database(FakeConnection(cursor), self.plan())
        calls = cursor.calls
        lock_index = next(i for i, (sql, _) in enumerate(calls) if sql.startswith("LOCK TABLE"))
        insert_index = next(i for i, (sql, _) in enumerate(calls) if sql.startswith("INSERT"))
        self.assertLess(lock_index, insert_index)
        license_sql, params = next((sql, params) for sql, params in calls if "INSERT INTO operacional.licencas_firewall" in sql)
        self.assertEqual(params[0], 42)
        self.assertEqual(license_sql.count("%s"), len(params))
        for sql, _ in calls:
            self.assertNotIn("SERIAL-TEST", sql)
            self.assertNotIn("REG_TEST", sql)
            self.assertNotIn("DELETE", sql)
            self.assertNotIn("TRUNCATE", sql)

    def test_nonempty_database_and_wrong_identity_are_refused_before_writes(self):
        for kwargs in ({"initial": (1, 0, 0)}, {"identity": ("aegis", "sentinel_collector", 5432)}, {"identity": ("sentinel", "sentinel_admin", 5433)}):
            cursor = FakeCursor(**kwargs)
            with self.assertRaises(ImportErrorSafe):
                write_empty_database(FakeConnection(cursor), self.plan())
            self.assertFalse(any(sql.startswith("INSERT") for sql, _ in cursor.calls))

    def test_apply_context_commits_only_after_counts_match(self):
        for kwargs, exception in (({}, None), ({"fail_insert": True}, ImportErrorSafe), ({"final": (1, 1, 0)}, ImportErrorSafe)):
            with self.subTest(kwargs=kwargs):
                connection = FakeConnection(FakeCursor(**kwargs))
                captures = {}

                def connect(**values):
                    captures.update(values)
                    return connection

                with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}), patch("getpass.getpass", return_value="PASSWORD_NEVER_PRINT"):
                    if exception:
                        with self.assertRaises(exception):
                            apply_plan(self.plan())
                        self.assertTrue(connection.rolled_back)
                    else:
                        apply_plan(self.plan())
                        self.assertTrue(connection.committed)
                self.assertEqual((captures["host"], captures["port"], captures["dbname"], captures["user"]), ("127.0.0.1", 5433, "sentinel", "sentinel_collector"))

    def test_database_check_is_read_only_and_reports_existing_counts(self):
        cursor = FakeCursor(initial=(49, 49, 49))
        connection = FakeConnection(cursor)
        captures = {}

        def connect(**values):
            captures.update(values)
            return connection

        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}), patch("getpass.getpass", return_value="DO_NOT_PRINT"):
            result = apply_plan(self.plan(), check_only=True)
        self.assertFalse(result["tabelas_vazias"])
        self.assertEqual((result["regionais"], result["firewalls"], result["licencas"]), (49, 49, 49))
        self.assertEqual(len(result["permissoes"]), 5)
        self.assertIn("default_transaction_read_only=on", captures["options"])
        self.assertIn(("SET TRANSACTION READ ONLY", None), cursor.calls)
        for sql, _ in cursor.calls:
            self.assertFalse(sql.startswith(("INSERT", "UPDATE", "DELETE", "LOCK", "CREATE", "TRUNCATE")))

    def test_sqlstate_and_phase_are_reported_without_error_details(self):
        class FakeDatabaseError(Exception):
            sqlstate = "42501"

        error = _database_error("insercao_licencas", FakeDatabaseError("SECRET_SQL_BOUND_VALUE"))
        self.assertIn("insercao_licencas", str(error))
        self.assertIn("42501", str(error))
        self.assertNotIn("SECRET", str(error))

    def test_malformed_error_metadata_is_not_echoed(self):
        class FakeDatabaseError(Exception):
            sqlstate = "SECRET_NOT_A_CODE"

        self.assertNotIn("SECRET", str(_database_error("conexao", FakeDatabaseError("SECRET"))))

    def test_connection_error_can_classify_without_sqlstate_or_exposing_message(self):
        samples = (
            ("password authentication failed for user SECRET_VALUE", "AUTENTICACAO_POR_SENHA_RECUSADA"),
            ("connection refused: SECRET_VALUE", "CONEXAO_RECUSADA"),
            ("invalid value for parameter: SECRET_VALUE", "OPCAO_DE_CONEXAO_OU_SERVIDOR_INVALIDA"),
            ("certificate verify failed: SECRET_VALUE", "FALHA_TLS_OU_CERTIFICADO"),
            ("no pg_hba.conf entry for SECRET_VALUE", "REGRA_HBA_RECUSOU_CONEXAO"),
            ("unexpected SECRET_VALUE", "CAUSA_AINDA_NAO_CLASSIFICADA"),
        )
        for message, hint in samples:
            with self.subTest(hint=hint):
                result = str(_database_error("conexao", RuntimeError(message)))
                self.assertIn(hint, result)
                self.assertNotIn("SECRET_VALUE", result)
                self.assertIn("SQLSTATE: indisponivel", result)

    def test_connection_hints_do_not_classify_bound_sql_values_as_connection_errors(self):
        result = str(_database_error("insercao_licencas", RuntimeError("password authentication failed SECRET_VALUE")))
        self.assertNotIn("Indicio", result)
        self.assertNotIn("SECRET_VALUE", result)

    def test_insert_failure_has_phase_and_rolls_back(self):
        connection = FakeConnection(FakeCursor(fail_insert=True))
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=lambda **kwargs: connection)}), patch("getpass.getpass", return_value="DO_NOT_PRINT"):
            with self.assertRaisesRegex(ImportErrorSafe, "insercao_licencas") as caught:
                apply_plan(self.plan())
        self.assertNotIn("DO_NOT_PRINT_BOUND_VALUES", str(caught.exception))
        self.assertTrue(connection.rolled_back)

    def test_cli_read_only_mode_selects_check_instead_of_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_bytes(self.raw())
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), patch("scripts.database.import_firewall_cache.apply_plan", return_value={"tabelas_vazias": True}) as apply, redirect_stdout(io.StringIO()) as output:
                result = main(["--cache", str(path), "--source-timezone", "America/Sao_Paulo", "--check-database"])
            self.assertEqual(result, 0)
            self.assertTrue(apply.call_args.kwargs["check_only"])
            self.assertEqual(json.loads(output.getvalue())["modo"], "conferencia_banco_somente_leitura")

    def test_cli_sanitizes_database_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_bytes(self.raw())
            with patch.dict("os.environ", {"COMPUTERNAME": "RIGEL"}), patch("scripts.database.import_firewall_cache.apply_plan", side_effect=RuntimeError("SECRET_BOUND_VALUE")), redirect_stderr(io.StringIO()) as output:
                result = main(["--cache", str(path), "--source-timezone", "America/Sao_Paulo", "--apply", "--expected-sha256", self.plan().sha256])
            self.assertEqual(result, 1)
            self.assertNotIn("SECRET_BOUND_VALUE", output.getvalue())


if __name__ == "__main__":
    unittest.main()
