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
            "regional": "REG_TESTE",
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

    def test_modelo_detectado_preenche_cadastro_sem_modelo_manual(self):
        efetivos = self.manager.atualizar_modelos_detectados({
            "REG_TESTE - SWITCH - 01": "HPE Networking Instant On 1830 48p"
        })

        self.assertEqual(
            efetivos["REG_TESTE - SWITCH - 01"],
            "HPE Networking Instant On 1830 48p",
        )
        self.assertEqual(
            self.manager.switches[0]["modelo"],
            "HPE Networking Instant On 1830 48p",
        )
        with open(self.manager.metadata_file, encoding="utf-8") as arquivo:
            salvo = json.load(arquivo)["hostid:12345"]
        self.assertEqual(salvo["modelo_source"], "firmware")

    def test_modelo_manual_detalhado_nao_e_substituido_pelo_detectado(self):
        manual = "HPE Networking Instant On 1830 48p Gigabit 4p SFP Switch JL814A"
        self.manager.atualizar_metadados(
            "REG_TESTE - SWITCH - 01",
            modelo=manual,
            local="Rack principal",
        )

        efetivos = self.manager.atualizar_modelos_detectados({
            "REG_TESTE - SWITCH - 01": "HPE Networking Instant On 1830 48p"
        })

        self.assertEqual(efetivos["REG_TESTE - SWITCH - 01"], manual)
        self.assertEqual(self.manager.switches[0]["modelo"], manual)
        with open(self.manager.metadata_file, encoding="utf-8") as arquivo:
            salvo = json.load(arquivo)["hostid:12345"]
        self.assertEqual(salvo["modelo"], manual)
        self.assertEqual(salvo["modelo_source"], "manual")

    def test_core_manual_e_persistido(self):
        atualizado = self.manager.atualizar_metadados(
            "REG_TESTE - SWITCH - 01",
            is_core=True,
        )

        self.assertTrue(atualizado["is_core"])
        with open(self.manager.metadata_file, encoding="utf-8") as arquivo:
            salvo = json.load(arquivo)["hostid:12345"]
        self.assertTrue(salvo["is_core"])
        self.assertEqual(salvo["core_source"], "manual")

    def test_regional_nao_aceita_dois_cores(self):
        self.manager.switches.append({
            "host": "REG_TESTE - SWITCH - 02",
            "hostid": "67890",
            "regional": "REG_TESTE",
            "modelo": "Não informado",
            "local": "Não informado",
            "is_core": False,
        })
        self.manager.atualizar_metadados("REG_TESTE - SWITCH - 01", is_core=True)

        with self.assertRaisesRegex(ValueError, "ja possui o switch CORE"):
            self.manager.atualizar_metadados("REG_TESTE - SWITCH - 02", is_core=True)

    def test_nome_core_nao_classifica_switch_automaticamente(self):
        switch = {"host": "REG - SWITCH CORE - 01", "regional": "REG"}
        self.manager._aplicar_metadados(switch, {})
        self.assertFalse(switch["is_core"])


if __name__ == "__main__":
    unittest.main()
