from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database.audit_operational_sources import audit_map, audit_sources, main, _time_kind


class SourcesAuditTest(unittest.TestCase):
    def test_never_exports_record_values_or_unknown_keys(self):
        raw = {"regionais": [{"codigo": "REG_PRIVATE", "switches": [
            {"hostid": "PRIVATE_ID", "nome": "PRIVATE_HOST", "password": "PRIVATE_PASS",
             "ip": "PRIVATE_IP", "status": "PRIVATE_STATUS", "PRIVATE_KEY": "PRIVATE_VALUE"}]}]}
        output = json.dumps(audit_map(raw))
        self.assertNotIn("PRIVATE", output)
        self.assertEqual(audit_map(raw)["categorias"]["switches"]["registros"], 1)

    def test_duplicate_candidates_within_regional_only(self):
        report = audit_map({"regionais": [
            {"codigo": "REG_A", "aps": [{"mac": "AA"}, {"mac": "aa"}, {"mac": " "}]},
            {"codigo": "REG_B", "aps": [{"mac": "AA"}]},
        ]})
        values = report["categorias"]["aps"]["candidatos_identidade_por_regional"]["mac"]
        self.assertEqual(values, {"registros_com_valor": 3, "valores_repetidos": 1,
                                  "registros_excedentes": 1})

    def test_missing_empty_invalid_and_unmapped_are_separate(self):
        report = audit_map({"regionais": [{"codigo": "REG_A"},
                            {"codigo": "REG_B", "vpns": []},
                            {"codigo": "REG_C", "vpns": {}},
                            {"codigo": "REG_D", "vpns": [None]}],
                            "unmapped": {"vpns": [{"secret": "DO_NOT_PRINT"}]}})
        vpn = report["categorias"]["vpns"]
        self.assertEqual(vpn["regionais_sem_categoria"], 1)
        self.assertEqual(vpn["regionais_com_lista_vazia"], 1)
        self.assertEqual(vpn["listas_invalidas"], 1)
        self.assertEqual(vpn["registros_invalidos"], 1)
        self.assertEqual(vpn["sem_vinculo_regional"], 1)

    def test_repeated_regionals_or_bad_shape(self):
        self.assertFalse(audit_map([])["estrutura_valida"])
        self.assertFalse(audit_map({"regionais": [None]})["estrutura_valida"])
        self.assertFalse(audit_map({"regionais": [{"codigo": "REG_A"},
                                               {"codigo": "reg_a"}]})["estrutura_valida"])

    def test_timestamp_classification_does_not_guess_timezone(self):
        self.assertEqual(_time_kind("2026-11-16T08:00:00-03:00"), "com_fuso")
        self.assertEqual(_time_kind("2026-11-16 08:00:00"), "sem_fuso")
        self.assertEqual(_time_kind(None), "ausente")
        self.assertEqual(_time_kind("16/11/2026 08:00:00"), "formato_nao_iso")
        self.assertEqual(_time_kind(1234), "formato_nao_iso")

    def test_files_missing_and_bad_json_no_traceback_or_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "output" / "mapa_monitoramento_cache.json"
            target.parent.mkdir()
            target.write_text('{"PRIVATE_BROKEN', encoding="utf-8")
            before = target.read_bytes()
            report = audit_sources(folder)
            self.assertEqual(report["fontes"]["mapa_consolidado"]["situacao"], "leitura_ou_json_invalido")
            self.assertEqual(report["fontes"]["unifi"]["situacao"], "ausente")
            self.assertNotIn("PRIVATE", json.dumps(report))
            self.assertEqual(target.read_bytes(), before)

    def test_summary_omits_verbose_fields(self):
        report = {"fontes": {"mapa": {"categorias": {"aps": {
            "registros": 3, "campos_conhecidos_presentes": {},
            "candidatos_identidade_por_regional": {},
        }}}}}
        with patch("scripts.database.audit_operational_sources.audit_sources", return_value=report):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--summary"]), 0)
        self.assertEqual(json.loads(output.getvalue())["fontes"]["mapa"]["categorias"]["aps"],
                         {"registros": 3})


if __name__ == "__main__":
    unittest.main()
