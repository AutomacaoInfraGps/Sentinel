import unittest
from unittest.mock import MagicMock, patch

import web_config
from fortimanager_client import FortiManagerClientError


class FirewallRefreshFallbackTest(unittest.TestCase):
    def setUp(self):
        self.cached_snapshot = {
            "atualizado_em": "2026-09-22T10:00:00",
            "firewalls_por_regional": {
                "REG_BAHIA": [{"nome": "FGT_REGBahia", "status": "online"}],
            },
            "total_firewalls": 1,
        }

    def _collect(self):
        collector = getattr(web_config.listar_firewalls, "__wrapped__", web_config.listar_firewalls)
        with web_config.app.test_request_context("/firewalls?refresh=1"):
            return collector(return_data=True)

    @patch.object(web_config, "_carregar_cache_dashboard")
    @patch.object(web_config, "FortiManagerClient")
    def test_connection_failure_preserves_last_valid_snapshot(self, client_class, load_cache):
        load_cache.return_value = self.cached_snapshot
        client_class.side_effect = FortiManagerClientError("conexao indisponivel")

        result = self._collect()

        self.assertFalse(result["success"])
        self.assertTrue(result["usando_cache"])
        self.assertEqual(result["total_firewalls"], 1)
        self.assertEqual(result["firewalls_por_regional"], self.cached_snapshot["firewalls_por_regional"])

    @patch.object(web_config, "_carregar_cache_dashboard")
    @patch.object(web_config, "FortiManagerClient")
    def test_empty_inventory_preserves_last_valid_snapshot(self, client_class, load_cache):
        load_cache.return_value = self.cached_snapshot
        client = MagicMock()
        client.list_devices.return_value = {"result": [{"data": []}]}
        client_class.return_value = client

        result = self._collect()

        self.assertFalse(result["success"])
        self.assertTrue(result["usando_cache"])
        self.assertEqual(result["total_firewalls"], 1)
        self.assertIn("inventario", result["message"])

    @patch.object(web_config, "_salvar_cache_dashboard")
    @patch.object(web_config.gerenciador_switches, "obter_hosts_em_manutencao_direta", return_value=[])
    @patch.object(web_config.gerenciador_regionais, "obter_regional", return_value={"nome": "Bahia"})
    @patch.object(web_config.gerenciador_regionais, "listar_regionais", return_value=["REG_BAHIA"])
    @patch.object(web_config, "_carregar_cache_dashboard", return_value={})
    @patch.object(web_config, "FortiManagerClient")
    def test_valid_inventory_is_collected_with_central_regional_resolver(
        self,
        client_class,
        _load_cache,
        _list_regionals,
        _get_regional,
        _maintenance_hosts,
        save_cache,
    ):
        client = MagicMock()
        client.list_devices.return_value = {
            "result": [{
                "data": [{
                    "name": "FGT_REGBAHIA",
                    "ip": "10.0.0.1",
                    "hostname": "fgt-bahia",
                    "platform_str": "FortiGate-60F",
                    "sn": "SERIAL-BAHIA",
                    "status": "online",
                }],
            }],
        }
        client.proxy_monitor_license.return_value = {
            "forticare": {"status": "licensed", "expires": 1893456000},
        }
        client_class.return_value = client

        result = self._collect()

        self.assertTrue(result["success"])
        self.assertEqual(result["total_firewalls"], 1)
        self.assertEqual(result["firewalls_por_regional"]["REG_BAHIA"][0]["nome"], "FGT_REGBAHIA")
        save_cache.assert_called_once()

    def test_refresh_button_uses_short_label(self):
        template = (web_config.PROJECT_ROOT / "templates" / "firewalls.html").read_text(encoding="utf-8")
        self.assertIn("Atualizar\n", template)
        self.assertNotIn("Atualizar Forti", template)

    def test_license_summary_and_filter_flags_use_same_sixty_day_rule(self):
        firewalls = {
            "REG_A": [
                {
                    "nome": "FGT_WARNING",
                    "status": "online",
                    "licencas": [
                        {"status": "licensed", "dias_restantes": 30},
                        {"status": "licensed", "dias_restantes": 60},
                    ],
                },
                {
                    "nome": "FGT_ZERO",
                    "status": "online",
                    "licencas": [{"status": "licensed", "dias_restantes": 0}],
                },
                {
                    "nome": "FGT_FUTURE",
                    "status": "online",
                    "licencas": [{"status": "licensed", "dias_restantes": 61}],
                },
                {
                    "nome": "FGT_UNAVAILABLE",
                    "status": "online",
                    "licencas": [{"status": "indisponivel", "dias_restantes": 0}],
                },
                {
                    "nome": "FGT_EXPIRED",
                    "status": "online",
                    "licencas": [{"status": "expired", "dias_restantes": 0}],
                },
            ],
        }

        summary = web_config._recalcular_totais_firewalls(firewalls)

        self.assertEqual(1, summary["total_alertas"])
        self.assertEqual(1, summary["total_expirados"])
        self.assertTrue(firewalls["REG_A"][0]["licencas"][0]["alerta_vencimento"])
        self.assertTrue(firewalls["REG_A"][0]["licencas"][1]["alerta_vencimento"])
        self.assertFalse(firewalls["REG_A"][1]["licencas"][0]["alerta_vencimento"])
        self.assertFalse(firewalls["REG_A"][2]["licencas"][0]["alerta_vencimento"])
        self.assertTrue(firewalls["REG_A"][3]["licencas"][0]["status_indisponivel"])

    def test_normalized_license_marks_sixty_days_as_expiring(self):
        future = web_config.datetime.now().timestamp() + (60 * 24 * 60 * 60)

        license_data = web_config._normalizar_licenca_firewall(
            "forticare",
            {"status": "licensed", "expires": future},
        )

        self.assertTrue(license_data["notificacao_critica"])


if __name__ == "__main__":
    unittest.main()
