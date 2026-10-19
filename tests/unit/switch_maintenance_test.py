import unittest
from unittest.mock import Mock

from gerenciar_switches import GerenciadorSwitches


class SwitchMaintenanceTests(unittest.TestCase):
    def test_only_returns_hosts_linked_directly_to_maintenance(self):
        manager = GerenciadorSwitches.__new__(GerenciadorSwitches)
        manager._call_api = Mock(return_value={
            "result": [
                {"maintenanceid": "441", "hosts": [{"hostid": "11030"}]},
                {"maintenanceid": "444", "hosts": []},
            ]
        })

        direct = manager._obter_hosts_com_manutencao_direta(["441", "444"])

        self.assertEqual(direct, {("441", "11030")})

    def test_returns_active_maintenance_with_host_groups(self):
        manager = GerenciadorSwitches.__new__(GerenciadorSwitches)
        manager._active_maintenance_cache = []
        manager._active_maintenance_cache_time = 0
        manager.obter_hosts_em_manutencao = Mock(return_value=[
            {"hostid": "11030", "maintenanceid": "441"},
        ])
        manager._call_api = Mock(return_value={
            "result": [{
                "maintenanceid": "441",
                "name": "MIGRACAO UBERLANDIA",
                "hostgroups": [{"groupid": "8", "name": "REG_UBERLANDIA"}],
                "hosts": [{"hostid": "11030", "name": "UBERLANDIA - SWITCH - 01"}],
            }],
        })

        result = manager.obter_manutencoes_ativas(cache_seconds=0)

        self.assertEqual(result[0]["maintenanceid"], "441")
        self.assertEqual(result[0]["hostgroups"][0]["name"], "REG_UBERLANDIA")


if __name__ == "__main__":
    unittest.main()
