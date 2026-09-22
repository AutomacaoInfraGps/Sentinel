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


if __name__ == "__main__":
    unittest.main()
