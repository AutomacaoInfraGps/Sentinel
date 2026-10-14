import unittest

from services.unifi_networks import (
    extract_unifi_items,
    merge_wifi_networks,
    sanitize_ap_wifi_networks,
    sanitize_site_wifi_networks,
)


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

    def test_infers_wifi_names_from_ap_runtime_data(self):
        result = sanitize_ap_wifi_networks([{
            "name": "V021_AP_PISO1",
            "vap_table": [
                {"essid": "MARTE", "radio": "na", "x_passphrase": "segredo"},
                {"essid": "MARTE", "radio": "ng"},
                {"essid": "SATURNO", "radio": "na"},
            ],
        }])

        self.assertEqual([item["nome"] for item in result], ["MARTE", "SATURNO"])
        self.assertEqual(result[0]["bandas"], ["5 GHz", "2.4 GHz"])
        self.assertEqual(result[0]["transmissao"], ["V021_AP_PISO1"])
        self.assertNotIn("segredo", repr(result))

    def test_merges_configured_and_observed_wifi(self):
        result = merge_wifi_networks(
            [{"nome": "MARTE", "rede": "USUARIOS", "bandas": [], "transmissao": [], "ativo": True}],
            [{"nome": "MARTE", "rede": "", "bandas": ["5 GHz"], "transmissao": ["AP-01"], "ativo": True}],
        )
        self.assertEqual(result[0]["rede"], "USUARIOS")
        self.assertEqual(result[0]["bandas"], ["5 GHz"])
        self.assertEqual(result[0]["transmissao"], ["AP-01"])

    def test_extracts_legacy_and_v2_collections(self):
        self.assertEqual(extract_unifi_items({"data": [{"name": "MARTE"}]}), [{"name": "MARTE"}])
        self.assertEqual(extract_unifi_items([{"name": "SATURNO"}]), [{"name": "SATURNO"}])


if __name__ == "__main__":
    unittest.main()
