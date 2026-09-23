import unittest
from unittest.mock import patch

import web_config


class NotificationBaselineTests(unittest.TestCase):
    @patch.object(web_config, "_carregar_cache_dashboard")
    def test_central_baseline_records_include_only_unresolved_differences(self, load_cache):
        load_cache.return_value = {
            "atualizado_em": "2026-09-22T15:00:00",
            "dispositivos": {
                "__fortimanager__": {
                    "nome": "FortiManager",
                    "tipo": "fortimanager",
                    "novos": ["admin.novo"],
                    "removidos": [],
                },
                "__fortianalyzer__": {
                    "nome": "FortiAnalyzer",
                    "tipo": "fortianalyzer",
                    "novos": [],
                    "removidos": ["admin.removido"],
                },
                "FGT_REG_TESTE": {
                    "nome": "FGT_REG_TESTE",
                    "tipo": "fortigate",
                    "novos": ["admin.regional"],
                    "removidos": [],
                },
            },
        }

        records = web_config._notification_central_admin_baseline_records()

        self.assertEqual(["FortiManager", "FortiAnalyzer"], [item["nome"] for item in records])
        self.assertTrue(all(item["baseline_pending"] for item in records))
        self.assertTrue(all(item["status"] == "alerta" for item in records))

    @patch.object(web_config, "_carregar_cache_dashboard")
    def test_approved_central_baseline_does_not_create_notification_record(self, load_cache):
        load_cache.return_value = {
            "atualizado_em": "2026-09-22T15:00:00",
            "dispositivos": {
                "__fortimanager__": {
                    "nome": "FortiManager",
                    "tipo": "fortimanager",
                    "novos": [],
                    "removidos": [],
                },
            },
        }

        self.assertEqual([], web_config._notification_central_admin_baseline_records())


if __name__ == "__main__":
    unittest.main()
