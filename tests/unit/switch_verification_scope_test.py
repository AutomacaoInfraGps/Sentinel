import unittest
from unittest.mock import Mock, patch

import web_config


class SwitchVerificationScopeTests(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.manager.regionais = {
            "REGIONAL PARANA": [{"host": "SW-PR-01", "regional": "REGIONAL PARANA"}],
        }
        self.manager.switches = [
            {"host": "SW-PR-01", "regional": "REGIONAL PARANA"},
        ]
        self.manager.verificar_switch.return_value = {"status": "online"}

    @patch.object(web_config.gerenciador_regionais, "obter_regional", return_value={"nome": "Parana"})
    @patch.object(web_config.gerenciador_regionais, "listar_regionais", return_value=["REG_PARANA"])
    def test_canonical_sentinel_code_resolves_zabbix_switches(self, _list, _get):
        resultados = web_config._verificar_switches_manager_regional(
            self.manager,
            "REG_PARANA",
        )

        self.assertEqual({"SW-PR-01": {"status": "online"}}, resultados)
        self.manager.verificar_switch.assert_called_once_with("SW-PR-01")

    def test_raw_zabbix_regional_still_works(self):
        resultados = web_config._verificar_switches_manager_regional(
            self.manager,
            "REGIONAL PARANA",
        )

        self.assertIn("SW-PR-01", resultados)


if __name__ == "__main__":
    unittest.main()
