import unittest
from unittest.mock import MagicMock, patch

from fortimanager_client import FortiManagerClient
from gerenciar_fortigate import GerenciadorFortigate


class FortiManagerVpnTests(unittest.TestCase):
    def test_phase1_interfaces_preserve_names_and_comments(self):
        client = FortiManagerClient(host="example.local", api_key="test")
        payload = {
            "result": [{
                "status": {"code": 0},
                "data": [
                    {"name": "T001_TESTE", "comments": "Regional TESTE"},
                    {"name": "T002_SEM_COMENTARIO"},
                ],
            }]
        }
        with patch.object(client, "_request", return_value=payload):
            tunnels = client.get_vpn_phase1_interfaces("FGT_TESTE")

        self.assertEqual(tunnels, [
            {"name": "T001_TESTE", "comments": "Regional TESTE"},
            {"name": "T002_SEM_COMENTARIO", "comments": ""},
        ])

    def test_fortimanager_marks_only_monitored_tunnels_up(self):
        manager = GerenciadorFortigate(
            host="192.0.2.1", port=443, username="test", password="test"
        )
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.get_vpn_phase1_interfaces.return_value = [
            {"name": "T001_UP", "comments": "Regional UM"},
            {"name": "T002_DOWN", "comments": "Regional DOIS"},
        ]
        client.proxy_monitor_vpn_ipsec.return_value = {
            "results": [{"name": "T001_UP", "parent": "T001_UP"}]
        }
        config = {
            "fortimanager": {
                "host": "fmg.example.local",
                "adom": "ADOM_TESTE",
                "vpn_hub_device": "FGT_HUB",
            }
        }

        with patch("gerenciar_fortigate.ENV_CONFIG", config), \
                patch("gerenciar_fortigate.FortiManagerClient", return_value=client):
            result = manager.obter_vpn_ipsec_fortimanager()

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "fortimanager_proxy")
        self.assertEqual([vpn["status"] for vpn in result["vpns"]], ["up", "down"])


if __name__ == "__main__":
    unittest.main()
