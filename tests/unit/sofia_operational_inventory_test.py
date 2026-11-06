import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sofia.operational_inventory import RESOURCES, query_operational_inventory


class SofiaOperationalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "map.json"
        self.payload = {"cache_atualizado_em": "2026-11-06T10:00:00-03:00", "regionais": [
            {"codigo": "REG_REGIONAL BELO HORIZONTE", "em_manutencao": False,
             "firewalls": [{"nome": "FGT-BH", "serial": "SERIAL-BH", "status": "warning",
                 "senha": "SECRET_PASSWORD", "token": "SECRET_TOKEN", "licencas": [
                     {"nome": "FortiCare", "notificacao_critica": True, "expiracao": "2026-11-20", "dias_restantes": 14, "private": "SECRET_LICENSE"},
                     {"nome": "FortiGuard", "notificacao_critica": True, "expiracao": "2026-12-01", "dias_restantes": 25},
                 ]}],
             "links": [{"nome": "WAN1", "ip": "192.0.2.1", "status": "online", "senha": "SECRET_PASSWORD"}],
             "vpns": [{"tunel": "TUN-BH", "status": "down", "psk": "SECRET_PSK"}],
             "aps": [{"nome": "AP-BH", "status": "offline", "clientes": 0, "password": "SECRET_PASSWORD"}],
             "switches": [{"nome": "SW-BH", "status": "online", "community": "SECRET_COMMUNITY"}],
             "servidores": [{"nome": "VM-BH", "status": "online", "usuario": "SECRET_USER"}],
             "redes_wifi": [{"ssid": "WIFI-BH", "status": "online", "wpa_psk": "SECRET_PSK"}],
             "alertas": [{"tipo": "firewalls", "descricao": "licencas a vencer", "quantidade": 1, "severidade": "atencao"}]},
            {"codigo": "REG_FORA", "firewalls": [{"nome": "FORBIDDEN_DEVICE", "licencas": [
                {"nome": "FORBIDDEN_LICENSE", "notificacao_critica": True, "expiracao": "2026-11-10", "dias_restantes": 4}]}]},
        ]}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")

    def query(self, resource, **kwargs):
        return query_operational_inventory(resource=resource,
            allowed_regionals=["REG_REGIONAL_BELO_HORIZONTE"], path=self.path,
            now=datetime(2026, 11, 6, 13, 1, tzinfo=timezone.utc), **kwargs)

    def test_licenses_keep_regional_firewall_dates_and_distinct_counts(self):
        result = self.query("licenses", status="expiring", detail_level="summary")
        self.assertEqual(result["summary"]["licenses"], 2)
        self.assertEqual(result["summary"]["firewalls"], 1)
        self.assertEqual(result["regionals"], [{"code": "REG_REGIONAL_BELO_HORIZONTE", "records": 2}])
        self.assertTrue(result["details_omitted"])
        detail = self.query("licenses", expires_within_days=20)
        self.assertEqual(detail["available"], 1)
        self.assertEqual(detail["records"][0]["firewall"], "FGT-BH")
        self.assertEqual(detail["records"][0]["expires_at"], "2026-11-20")

    def test_every_resource_is_scoped_and_credential_free(self):
        for resource in RESOURCES:
            with self.subTest(resource=resource):
                result = self.query(resource)
                self.assertEqual(result["available"], 2 if resource == "licenses" else 1)
                rendered = json.dumps(result)
                self.assertNotIn("SECRET_", rendered)
                self.assertNotIn("FORBIDDEN_", rendered)
                self.assertTrue(result["fresh"])

    def test_scopes_cannot_be_bypassed_by_search_or_regional(self):
        with self.assertRaises(PermissionError):
            self.query("licenses", regional="REG_FORA")
        self.assertEqual(self.query("licenses", search="FORBIDDEN")["available"], 0)

    def test_filtering_and_regional_summary_happen_before_pagination(self):
        result = self.query("licenses", status="expiring", limit=1)
        self.assertEqual(result["available"], 2)
        self.assertEqual(result["returned"], 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["regionals"][0]["records"], 2)
        second = self.query("licenses", status="expiring", limit=1, offset=1)
        self.assertFalse(second["truncated"])
        self.assertNotEqual(result["records"], second["records"])

    def test_offline_license_is_not_reported_as_expired_or_valid(self):
        self.payload["regionais"][0]["firewalls"][0]["licencas"] = [
            {"nome": "FortiCare", "status": "offline", "expiracao": "N/A", "dias_restantes": 0}
        ]
        self.save()
        record = self.query("licenses")["records"][0]
        self.assertEqual(record["status"], "unavailable")
        self.assertIsNone(record["days_remaining"])
        self.assertIsNone(record["expires_at"])
        self.assertEqual(self.query("licenses", expires_within_days=30)["available"], 0)

    def test_missing_license_details_are_explicit(self):
        self.payload["regionais"][0]["firewalls"][0]["licencas"] = []
        self.save()
        result = self.query("licenses")
        self.assertEqual(result["data_gaps"][0]["reason"], "license_details_unavailable")

    def test_invalid_queries_cannot_select_arbitrary_json_or_files(self):
        for resource in ["credentials", "../../environment.json", "admins", "ad_users"]:
            with self.assertRaises(ValueError):
                self.query(resource)
        for kwargs in [{"limit": 1000}, {"offset": -1}, {"limit": True},
                       {"status": "ANYTHING"}, {"expires_within_days": -1}, {"search": "x" * 121}]:
            with self.assertRaises(ValueError):
                self.query("licenses", **kwargs)

    def test_stale_source_is_not_presented_as_current(self):
        self.payload["cache_atualizado_em"] = "2026-11-05T10:00:00-03:00"
        self.save()
        self.assertFalse(self.query("licenses")["fresh"])
