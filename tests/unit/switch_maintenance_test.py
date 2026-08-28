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


if __name__ == "__main__":
    unittest.main()
