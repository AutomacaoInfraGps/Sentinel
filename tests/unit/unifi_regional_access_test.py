import unittest

from web_config import _filtrar_unifi_por_escopo_regional


class UnifiRegionalAccessTest(unittest.TestCase):
    def test_filters_inventory_sites_and_interference_with_the_same_scope(self):
        payload = {
            "aps": [
                {
                    "nome": "AP Bahia",
                    "site": "V021_BAHIA",
                    "status": "online",
                    "clientes": 7,
                },
                {
                    "nome": "AP Goias",
                    "site": "V023_GOIAS",
                    "status": "offline",
                    "clientes": 2,
                },
                {
                    "nome": "AP sem vinculo",
                    "site": "SITE_DESCONHECIDO",
                    "status": "online",
                },
            ],
            "sites": [
                {"nome": "V021_BAHIA"},
                {"nome": "V023_GOIAS"},
                {"nome": "SITE_DESCONHECIDO"},
            ],
            "interferencia_5ghz_por_site": {
                "V021_BAHIA": [{"canal": 36}],
                "V023_GOIAS": [{"canal": 44}],
                "SITE_DESCONHECIDO": [{"canal": 149}],
            },
        }
        regionais = {
            "REG_BAHIA": {"nome": "Bahia"},
            "REG_GOIAS": {"nome": "Goias"},
        }

        filtered = _filtrar_unifi_por_escopo_regional(
            payload,
            regionais,
            lambda codigo: codigo == "REG_BAHIA",
        )

        self.assertEqual([ap["nome"] for ap in filtered["aps"]], ["AP Bahia"])
        self.assertEqual([site["nome"] for site in filtered["sites"]], ["V021_BAHIA"])
        self.assertEqual(list(filtered["interferencia_5ghz_por_site"]), ["V021_BAHIA"])
        self.assertEqual(filtered["total_aps"], 1)
        self.assertEqual(filtered["aps_online"], 1)
        self.assertEqual(filtered["aps_offline"], 0)
        self.assertEqual(filtered["clientes_conectados"], 7)


if __name__ == "__main__":
    unittest.main()
