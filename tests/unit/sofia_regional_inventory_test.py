import json
import unittest

from sofia import tools_sentinel


class FakeRegionalManager:
    def __init__(self):
        self.regionais = {
            "regionais": {
                "REG_ABC": {
                    "nome": "ABC",
                    "uf": "SP",
                    "servidores": [{
                        "nome": "Sirius",
                        "ip": "192.0.2.10",
                        "usuario": "technical-user",
                        "senha": "must-never-leak",
                        "status": "online",
                    }],
                    "links_internet_auto": [{
                        "nome": "wan1",
                        "provedor": "Example ISP",
                        "ip_exibicao": "192.0.2.0/29",
                        "status": "online",
                    }],
                },
                "REG_FORA": {"nome": "Fora", "servidores": [], "links": []},
            }
        }

    def recarregar_regionais(self):
        return self.regionais


class FakeSwitchManager:
    regionais = {
        "ABC": [{
            "host": "ABC - SWITCH - 01",
            "ip": "192.0.2.20",
            "community": "must-never-leak-either",
            "status": "online",
        }]
    }


class SofiaRegionalInventoryTest(unittest.TestCase):
    def setUp(self):
        tools_sentinel.configurar_ferramentas_sentinel(
            regionais_manager=FakeRegionalManager(),
            switches_manager=FakeSwitchManager(),
        )

    def tearDown(self):
        tools_sentinel.configurar_ferramentas_sentinel(
            regionais_manager=None,
            switches_manager=None,
        )

    def test_index_and_detail_are_scoped_and_credential_free(self):
        allowed = {"REG_ABC"}
        index = tools_sentinel.consultar_inventario_regional(
            allowed_regionals=allowed
        )
        self.assertEqual(index["total"], 1)
        self.assertEqual(index["regionals"][0]["code"], "REG_ABC")

        detail = tools_sentinel.consultar_inventario_regional(
            codigo_regional="REG_ABC",
            secoes=["servidores", "links", "switches"],
            allowed_regionals=allowed,
        )
        rendered = json.dumps(detail)
        self.assertIn("Sirius", rendered)
        self.assertIn("Example ISP", rendered)
        self.assertIn("ABC - SWITCH - 01", rendered)
        self.assertNotIn("must-never-leak", rendered)
        self.assertNotIn("technical-user", rendered)
        self.assertNotIn("community", rendered)
        self.assertIsNone(
            tools_sentinel.consultar_inventario_regional(
                codigo_regional="REG_FORA",
                secoes=[],
                allowed_regionals=allowed,
            )
        )


if __name__ == "__main__":
    unittest.main()
