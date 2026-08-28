import json
import tempfile
import unittest
from pathlib import Path

from dashboard_security_sections import build_security_dashboard


class SecurityDashboardTests(unittest.TestCase):
    def test_firewall_rows_include_all_licenses_and_availability(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "output").mkdir()
            (root / "estrutura_regionais.json").write_text(
                json.dumps({"regionais": {"REG_TESTE": {"nome": "REG_TESTE"}}}),
                encoding="utf-8",
            )
            cache = {
                "atualizado_em": "2026-08-26T12:00:00",
                "firewalls_por_regional": {
                    "REG_TESTE": [
                        {
                            "nome": "FW-ONLINE",
                            "ip": "10.0.0.1",
                            "status_disponibilidade": "online",
                            "licencas": [
                                {"nome": "forticare", "status": "valid", "dias_restantes": 100},
                                {
                                    "nome": "fortiguard",
                                    "status": "valid",
                                    "dias_restantes": 45,
                                },
                            ],
                        },
                        {
                            "nome": "FW-OFFLINE",
                            "ip": "10.0.0.2",
                            "status_disponibilidade": "offline",
                            "licencas": [{"nome": "forticare", "status": "offline"}],
                        },
                    ]
                },
            }
            (root / "output" / "dashboard_firewalls_cache.json").write_text(
                json.dumps(cache), encoding="utf-8"
            )
            (root / "output" / "dashboard_admins_cache.json").write_text("{}", encoding="utf-8")

            dashboard = build_security_dashboard(root)
            detail = dashboard["firewall_detail"]

            self.assertIn("fortiguard: valid", detail)
            self.assertIn('data-status="warning"', detail)
            self.assertIn('data-fw-status="offline"', detail)
            self.assertEqual(dashboard["firewall_counts"]["warning"], 1)
            self.assertEqual(dashboard["firewall_availability_counts"]["offline"], 1)

    def test_checklist_license_kpis_use_filterable_statuses(self):
        source = (Path(__file__).parents[2] / "executar_tudo.py").read_text(encoding="utf-8")
        self.assertIn("replace(/^licence-/, '')", source)
        self.assertIn("row.dataset.status === normalizedAction", source)


if __name__ == "__main__":
    unittest.main()
