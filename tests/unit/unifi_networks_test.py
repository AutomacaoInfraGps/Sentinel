import unittest

from services.unifi_networks import sanitize_site_wifi_networks


class UnifiNetworksTest(unittest.TestCase):
    def test_keeps_display_metadata_and_drops_credentials(self):
        result = sanitize_site_wifi_networks(
            [{
                "name": "SATURNO",
                "enabled": True,
                "networkconf_id": "network-10",
                "ap_group_ids": ["aps-galaxia"],
                "wlan_bands": ["2g", "5g"],
                "x_passphrase": "nao-pode-sair",
                "security": "wpapsk",
            }],
            [{"_id": "network-10", "name": "VISITANTE", "vlan": 10}],
            [{"_id": "aps-galaxia", "name": "V001_GALAXIA"}],
        )

        self.assertEqual(result, [{
            "nome": "SATURNO",
            "rede": "VISITANTE (10)",
            "bandas": ["2g", "5g"],
            "transmissao": ["V001_GALAXIA"],
            "ativo": True,
        }])
        self.assertNotIn("nao-pode-sair", repr(result))
        self.assertNotIn("passphrase", repr(result))


if __name__ == "__main__":
    unittest.main()
