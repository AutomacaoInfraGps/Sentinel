import unittest

from services.map_wifi_overlay import overlay_wifi_networks


class MapWifiOverlayTests(unittest.TestCase):
    def test_replaces_only_wifi_inventory_from_latest_snapshot(self):
        map_payload = {
            "regionais": [{
                "codigo": "REG_GALAXIA",
                "servidores": [{"nome": "Rigel"}],
                "redes_wifi": [{"nome": "ANTIGA"}],
                "totais": {"servidores": 1, "redes_wifi": 1},
            }],
            "unmapped": {"redes_wifi": [{"nome": "ANTIGA"}]},
        }
        unifi_payload = {"sites": [{
            "nome": "GALAXIA",
            "redes_wifi": [{
                "nome": "MARTE",
                "rede": "RD_USUARIOS (20)",
                "bandas": ["5 GHz"],
                "transmissao": ["V001_GALAXIA"],
                "ativo": True,
            }],
        }]}

        result = overlay_wifi_networks(
            map_payload,
            unifi_payload,
            lambda regionals, site: "REG_GALAXIA" if site == "GALAXIA" else None,
        )

        self.assertEqual(result, {"available": True, "networks": 1, "mapped": 1})
        self.assertEqual(map_payload["regionais"][0]["servidores"], [{"nome": "Rigel"}])
        self.assertEqual(map_payload["regionais"][0]["redes_wifi"][0]["nome"], "MARTE")
        self.assertEqual(map_payload["regionais"][0]["totais"]["redes_wifi"], 1)
        self.assertEqual(map_payload["unmapped"]["redes_wifi"], [])

    def test_keeps_cache_when_snapshot_uses_legacy_schema(self):
        map_payload = {"regionais": [{"codigo": "REG_GALAXIA", "redes_wifi": [{"nome": "MARTE"}]}]}

        result = overlay_wifi_networks(map_payload, {"sites": [{"nome": "GALAXIA"}]}, lambda *_: None)

        self.assertFalse(result["available"])
        self.assertEqual(map_payload["regionais"][0]["redes_wifi"], [{"nome": "MARTE"}])


if __name__ == "__main__":
    unittest.main()
