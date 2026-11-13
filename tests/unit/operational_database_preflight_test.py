from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.database.audit_firewall_cache import AuditError, audit_payload, main


class OperationalDatabasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.firewall = {
            "nome": "FGT-TEST", "serial": "SERIAL-TEST", "ip": "192.0.2.1",
            "ultima_verificacao": "2026-11-12T10:00:00-03:00",
            "licencas": [{"nome": "forticare", "expiracao": "2026-12-21", "dias_restantes": 39}],
        }
        self.payload = {"firewalls_por_regional": {"REG_TEST": [self.firewall]}}

    def test_valid_payload_is_counted_without_exposing_values(self):
        result = audit_payload(self.payload)
        self.assertTrue(result["estrutura_valida"])
        self.assertEqual((result["regionais_no_cache"], result["firewalls"], result["licencas"]), (1, 1, 1))
        self.assertEqual(result["vencimentos_apenas_data"], 1)
        self.assertNotIn("SERIAL-TEST", json.dumps(result))

    def test_duplicate_serials_across_regionals_are_blocking_and_case_insensitive(self):
        other = deepcopy(self.firewall)
        other["serial"] = "serial-test"
        self.payload["firewalls_por_regional"]["REG_OTHER"] = [other]
        result = audit_payload(self.payload)
        self.assertFalse(result["estrutura_valida"])
        self.assertEqual(result["erros"]["serial_duplicado"], 1)

    def test_placeholder_serial_is_blocking(self):
        for value in (None, "", "N/A", "unknown", 123):
            with self.subTest(value=value):
                self.firewall["serial"] = value
                self.assertIn("serial_invalido", audit_payload(self.payload)["erros"])

    def test_invalid_schema_types_and_lengths_are_blocking(self):
        self.firewall.update(nome="x" * 241, firmware=["invalid"], ip="not-an-ip")
        license_record = self.firewall["licencas"][0]
        license_record.update(dias_restantes=True, notificacao_critica="false")
        errors = audit_payload(self.payload)["erros"]
        for key in ("nome_firewall_invalido", "campo_firewall_invalido", "ip_firewall_invalido", "dias_restantes_invalidos", "indicador_licenca_invalido"):
            self.assertIn(key, errors)

    def test_known_expiry_formats_preserve_precision(self):
        for value, key in (("21/12/2026", "vencimentos_apenas_data"),
                           (1797840000, "vencimentos_com_instante"),
                           ("2026-12-21T00:00:00Z", "vencimentos_com_instante"),
                           ("2026-12-21T00:00:00", "vencimentos_sem_fuso")):
            with self.subTest(value=value):
                self.firewall["licencas"][0]["expiracao"] = value
                self.assertEqual(audit_payload(self.payload)[key], 1)

    def test_missing_expiry_is_not_zero_days_or_an_error(self):
        for value in (None, "N/A", 0):
            self.firewall["licencas"][0]["expiracao"] = value
            result = audit_payload(self.payload)
            self.assertTrue(result["estrutura_valida"])
            self.assertEqual(result["vencimentos_ausentes"], 1)

    def test_malformed_dates_are_blocking(self):
        for value in ("2026-02-30", "invalid", True, -1, float("inf")):
            self.firewall["licencas"][0]["expiracao"] = value
            self.assertIn("vencimento_invalido", audit_payload(self.payload)["erros"])

    def test_naive_collection_time_requires_explicit_timezone_not_guessing(self):
        self.firewall["ultima_verificacao"] = "2026-11-12T10:00:00"
        result = audit_payload(self.payload)
        self.assertEqual(result["coletas_sem_fuso"], 1)
        self.assertIn("datas_sem_fuso_exigem_configuracao_explicita", result["avisos"])

    def test_malformed_collections_are_not_empty_success(self):
        for payload in ([], {}, {"firewalls_por_regional": []}):
            with self.assertRaises(AuditError):
                audit_payload(payload)
        for firewalls in ({}, [None], [{"nome": "FGT", "licencas": {}}], []):
            result = audit_payload({"firewalls_por_regional": {"REG_TEST": firewalls}})
            self.assertFalse(result["estrutura_valida"])

    def test_cli_is_read_only_and_does_not_print_secrets(self):
        self.firewall.update(senha="DO_NOT_PRINT", token="DO_NOT_PRINT")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            original = json.dumps(self.payload).encode()
            path.write_bytes(original)
            before = path.stat().st_mtime_ns
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--cache", str(path)]), 0)
            self.assertNotIn("DO_NOT_PRINT", output.getvalue())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_cli_read_errors_do_not_leak_source_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text('{"secret": "DO_NOT_PRINT", BROKEN', encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(main(["--cache", str(path)]), 2)
            self.assertNotIn("DO_NOT_PRINT", error.getvalue())


if __name__ == "__main__":
    unittest.main()
