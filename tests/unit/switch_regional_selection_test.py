import unittest

from gerenciar_switches import GerenciadorSwitches


class SwitchRegionalSelectionTests(unittest.TestCase):
    def setUp(self):
        self.manager = GerenciadorSwitches.__new__(GerenciadorSwitches)

    def test_regional_explicita_prevalece_sobre_grupo_tecnico(self):
        groups = [
            {"name": "REG_GRSA_MACAE"},
            {"name": "REGIONAL MACAE"},
            {"name": "SWITCHES"},
        ]

        self.assertEqual(self.manager._selecionar_regional_zabbix(groups), "REGIONAL MACAE")

    def test_mantem_grsa_quando_nao_existe_outra_regional(self):
        groups = [{"name": "REG_GRSA_MACAE"}, {"name": "SWITCHES"}]

        self.assertEqual(self.manager._selecionar_regional_zabbix(groups), "REG_GRSA_MACAE")

    def test_resultado_independe_da_ordem_dos_grupos(self):
        groups = [{"name": "REGIONAL MACAE"}, {"name": "REG_GRSA_MACAE"}]

        first = self.manager._selecionar_regional_zabbix(groups)
        second = self.manager._selecionar_regional_zabbix(list(reversed(groups)))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
