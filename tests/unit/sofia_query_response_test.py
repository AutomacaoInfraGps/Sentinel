import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from sofia.query_response import execute_plan, validate_plan


class SofiaQueryResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "snapshot.json"
        self.path.write_text(json.dumps({"cache_atualizado_em": "2026-11-09T12:00:00+00:00",
            "regionais": [{"codigo": "REG_ARARAS", "switches": [
                {"nome": "SW-01", "status": "maintenance", "senha": "SECRET"}],
                "aps": [{"nome": "AP-01", "ip": "192.0.2.1", "status": "offline", "mac": "PRIVATE_MAC"},
                        {"nome": "AP-02", "ip": "192.0.2.2", "status": "offline"}],
                "firewalls": [{"nome": "FW-01", "model": "FortiGate-60F", "firmware": "7.4.13", "status": "online"}]},
                {"codigo": "REG_FORA", "aps": [{"nome": "FORBIDDEN", "status": "offline"}]}]}), encoding="utf-8")

    def query(self, **kwargs):
        plan = {"mode": "query", "resource": "aps", "regional": "", "status": "",
                "search": "", "view": "list", "fields": [], "limit": 20, "offset": 0, **kwargs}
        return execute_plan(plan, {"REG_ARARAS"}, path=self.path,
                            now=datetime(2026, 11, 9, 12, 1, tzinfo=timezone.utc))

    def test_positive_maintenance_count_never_depends_on_detail_rows(self):
        result = self.query(resource="switches", status="maintenance", view="count")
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["reply"], "Encontrei 1 switch em manutenção nas regionais autorizadas.")
        self.assertNotIn("SECRET", result["reply"])

    def test_requested_fields_are_scoped_and_do_not_include_extra_identifiers(self):
        result = self.query(status="offline", fields=["name", "ip", "regional"])
        self.assertEqual(result["matched"], 2)
        self.assertIn("AP-01", result["reply"])
        self.assertIn("192.0.2.2", result["reply"])
        self.assertNotIn("MAC", result["reply"])
        self.assertNotIn("FORBIDDEN", result["reply"])

    def test_equipment_lists_identify_each_row_when_only_status_is_requested(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["regionais"][0]["servidores"] = [
            {"nome": "Alhena", "status": "offline"},
            {"nome": "Markeb", "status": "offline"},
            {"nome": "Sadr", "status": "offline"},
        ]
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        for resource, names in [("servers", ["Alhena", "Markeb", "Sadr"]),
                                ("aps", ["AP-01", "AP-02"]), ("switches", ["SW-01"])]:
            with self.subTest(resource=resource):
                result = self.query(resource=resource, fields=["status"])
                rows = [line for line in result["reply"].splitlines() if line.startswith("- ")]
                self.assertEqual(len(rows), len(names))
                for row, name in zip(rows, names):
                    self.assertTrue(row.startswith(f"- {name} | Estado — "))
                self.assertNotIn("FORBIDDEN", result["reply"])

    def test_name_already_requested_is_displayed_once_and_count_has_no_rows(self):
        result = self.query(fields=["name", "status"])
        self.assertEqual(result["reply"].count("AP-01"), 1)
        self.assertNotIn("\n- ", self.query(view="count", fields=["status"])["reply"])

    def test_regional_lists_keep_regional_identity(self):
        result = self.query(resource="regionals", fields=["status"])
        self.assertIn("Regional — REG_ARARAS", result["reply"])

    def test_natural_count_and_empty_results_keep_the_filter(self):
        result = self.query(status="offline", view="count")
        self.assertEqual(result["reply"], "Encontrei 2 APs offline nas regionais autorizadas.")
        empty = self.query(resource="switches", status="offline", view="count")
        self.assertEqual(empty["reply"], "Não encontrei switches offline nas regionais autorizadas.")

    def test_unfiltered_count_preserves_status_distribution(self):
        result = self.query(view="count")
        self.assertIn("Encontrei 2 APs nas regionais autorizadas.", result["reply"])
        self.assertIn("Por estado, temos 2 offline.", result["reply"])

    def test_regional_alias_and_firmware(self):
        result = self.query(resource="firewalls", regional="Araras", fields=["model", "firmware"])
        self.assertIn("FortiGate-60F", result["reply"])
        self.assertIn("7.4.13", result["reply"])
        with self.assertRaises(PermissionError):
            self.query(regional="FORA")

    def test_pagination_count_stays_total_and_next_offset_is_correct(self):
        first = self.query(limit=1)
        self.assertEqual(first["matched"], 2)
        self.assertEqual(first["displayed"], 1)
        self.assertEqual(first["next_offset"], 1)
        self.assertIn("Lista parcial", first["reply"])
        self.assertIn("deslocamento — 1", first["reply"])
        last = self.query(limit=1, offset=1)
        self.assertIsNone(last["next_offset"])
        self.assertNotIn("Lista parcial", last["reply"])

    def test_missing_fields_and_stale_source_are_explicit(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["cache_atualizado_em"] = "2026-11-01T12:00:00+00:00"
        del payload["regionais"][0]["aps"][0]["ip"]
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        result = self.query(fields=["name", "ip"])
        self.assertIn("IP — não informado", result["reply"])
        self.assertIn("Última atualização — 01/11/2026 às 09:00:00 (horário de Brasília).", result["reply"])
        self.assertNotIn("Fonte desatualizada", result["reply"])

    def test_last_update_without_timezone_uses_brasilia(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["cache_atualizado_em"] = "2026-11-01T08:43:36.274863"
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("01/11/2026 às 08:43:36", self.query()["reply"])

    def test_missing_last_update_is_not_replaced_with_current_time(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["cache_atualizado_em"] = "invalid"
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("Horário da última atualização não informado.", self.query()["reply"])

    def test_unknown_resource_and_arbitrary_fields_fail_closed(self):
        for change in ({"resource": "ad_users"}, {"fields": ["senha"]}, {"url": "http://invalid"},
                       {"fields": "*"}, {"limit": True}, {"offset": -1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_plan({"mode": "query", "resource": "aps", **change})

    def test_regionals_are_the_authorized_universe(self):
        result = self.query(resource="regionals", view="count")
        self.assertEqual(result["matched"], 1)
        self.assertIn("regionais autorizadas", result["reply"])

    def test_oversized_rows_remain_explicitly_partial(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["regionais"][0]["aps"] = [{"nome": "x" * 240, "status": "offline", "ip": "y" * 240,
                                            "modelo": "z" * 240} for _ in range(50)]
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        result = self.query(limit=50, fields=["name", "ip", "model"])
        self.assertLessEqual(len(result["reply"]), 8000)
        self.assertIn("Lista parcial", result["reply"])
        self.assertLess(result["displayed"], 50)
        self.assertEqual(result["next_offset"], result["displayed"])
