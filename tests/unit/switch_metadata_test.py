import json
import tempfile
import unittest
from pathlib import Path
from threading import Lock

from gerenciar_switches import GerenciadorSwitches


class SwitchMetadataTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = GerenciadorSwitches.__new__(GerenciadorSwitches)
        self.manager.metadata_file = Path(self.temp_dir.name) / "switches_metadata.json"
        self.manager.status_cache_file = Path(self.temp_dir.name) / "switches_status_cache.json"
        self.manager._metadata_lock = Lock()
        self.manager.switches = [{
            "host": "REG_TESTE - SWITCH - 01",
            "hostid": "12345",
            "zabbix_host": "sw-teste-01",
            "modelo": "Não informado",
            "local": "Não informado",
            "status": "online",
        }]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_modelo_manual_e_salvo_por_hostid_e_aplicado_ao_inventario(self):
        self.manager.atualizar_metadados(
            "REG_TESTE - SWITCH - 01",
            modelo="Cisco CBS350-24T",
            local="Rack principal",
        )

        with open(self.manager.metadata_file, encoding="utf-8") as arquivo:
            salvo = json.load(arquivo)
        self.assertEqual(salvo["hostid:12345"]["modelo"], "Cisco CBS350-24T")

        atualizado_zabbix = {
            "host": "REG_TESTE - SWITCH - 01",
            "hostid": "12345",
            "modelo": "Não informado",
            "local": "Não informado",
        }
        self.manager._aplicar_metadados(atualizado_zabbix)

        self.assertEqual(atualizado_zabbix["modelo"], "Cisco CBS350-24T")
        self.assertEqual(atualizado_zabbix["local"], "Rack principal")

    def test_switch_pode_ser_localizado_pelo_nome_tecnico_do_zabbix(self):
        encontrado = self.manager.obter_switch("sw-teste-01")
        self.assertEqual(encontrado["hostid"], "12345")


if __name__ == "__main__":
    unittest.main()
