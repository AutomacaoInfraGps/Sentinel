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

    def obter_manutencoes_ativas(self, cache_seconds=60):
        return [{
            "maintenanceid": "441",
            "name": "MIGRACAO ABC",
            "active_since": "1792400400",
            "active_till": "1792486800",
            "hostgroups": [{"groupid": "8", "name": "REG_ABC"}],
        }]


class ManyRegionalManager:
    def __init__(self, total=51):
        self.regionais = {
            "regionais": {
                f"REG_TESTE_{index:02d}": {
                    "nome": f"REG_TESTE_{index:02d}",
                    "servidores": [],
                    "links": [],
                }
                for index in range(1, total + 1)
            }
        }

    def recarregar_regionais(self):
        return self.regionais


class EmptySwitchManager:
    regionais = {}

    def obter_manutencoes_ativas(self, cache_seconds=60):
        return []


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
        self.assertEqual(index["returned"], 1)
        self.assertTrue(index["authoritative"])
        self.assertTrue(index["complete"])
        self.assertEqual(index["regionals"][0]["code"], "REG_ABC")
        self.assertEqual(index["maintenance"]["total"], 1)
        self.assertTrue(index["regionals"][0]["in_maintenance"])
        self.assertEqual(
            index["regionals"][0]["maintenance_windows"][0]["name"],
            "MIGRACAO ABC",
        )

        detail = tools_sentinel.consultar_inventario_regional(
            codigo_regional="REG_ABC",
            secoes=["servidores", "links", "switches"],
            allowed_regionals=allowed,
        )
        rendered = json.dumps(detail)
        self.assertIn("Sirius", rendered)
        self.assertIn("Example ISP", rendered)
        self.assertIn("ABC - SWITCH - 01", rendered)
        self.assertIn("MIGRACAO ABC", rendered)
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

    def test_index_returns_all_51_regionals_without_truncation(self):
        manager = ManyRegionalManager(total=51)
        allowed = set(manager.regionais["regionais"])
        tools_sentinel.configurar_ferramentas_sentinel(
            regionais_manager=manager,
            switches_manager=EmptySwitchManager(),
        )

        index = tools_sentinel.consultar_inventario_regional(
            allowed_regionals=allowed
        )

        self.assertEqual(index["total"], 51)
        self.assertEqual(index["returned"], 51)
        self.assertEqual(len(index["regionals"]), 51)
        self.assertTrue(index["complete"])


if __name__ == "__main__":
    unittest.main()
