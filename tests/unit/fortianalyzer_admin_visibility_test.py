import unittest

import web_config


class FortiAnalyzerAdminVisibilityTests(unittest.TestCase):
    def test_permission_failure_preserves_last_confirmed_baseline_alert(self):
        result = web_config._reconcile_faz_admin_snapshot(
            {
                "admins": [],
                "visibilidade_completa": False,
                "motivo": "No permission for the resource",
            },
            ["admin"],
            previous={
                "admins": ["admin", "admin.satiro"],
                "novos": ["admin.satiro"],
                "removidos": [],
                "ultima_coleta_valida": "2026-09-22T09:00:00",
            },
        )

        self.assertEqual(["admin.satiro"], result["novos"])
        self.assertEqual(["admin", "admin.satiro"], result["admins"])
        self.assertFalse(result["complete"])

    def test_complete_query_recalculates_against_baseline(self):
        result = web_config._reconcile_faz_admin_snapshot(
            {
                "admins": ["admin", "admin.novo"],
                "visibilidade_completa": True,
                "apenas_contas_api": False,
            },
            ["admin", "admin.removido"],
            previous={"novos": ["obsoleto"]},
        )

        self.assertEqual(["admin.novo"], result["novos"])
        self.assertEqual(["admin.removido"], result["removidos"])
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
