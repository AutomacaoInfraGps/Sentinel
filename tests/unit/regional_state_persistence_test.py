import tempfile
import unittest
from pathlib import Path

from gerenciar_regionais import GerenciadorRegionais


class RegionalStatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "regionais.json"
        self.manager = GerenciadorRegionais(str(self.path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_estado_persiste_ao_criar_e_recarregar(self):
        self.manager.adicionar_regional("REG_TESTE", "Regional Teste", estado="SP")

        reloaded = GerenciadorRegionais(str(self.path)).obter_regional("REG_TESTE")

        self.assertEqual(reloaded["estado"], "SP")
        self.assertEqual(reloaded["uf"], "SP")

    def test_estado_persiste_ao_editar(self):
        self.manager.adicionar_regional("REG_TESTE", "Regional Teste")
        self.manager.atualizar_regional(
            "REG_TESTE", "REG_TESTE", "Regional Teste", estado="RJ"
        )

        reloaded = GerenciadorRegionais(str(self.path)).obter_regional("REG_TESTE")

        self.assertEqual(reloaded["estado"], "RJ")
        self.assertEqual(reloaded["uf"], "RJ")

    def test_remover_servidor_recarrega_e_persiste_a_estrutura(self):
        self.manager.adicionar_regional("REG_TESTE", "Regional Teste", estado="SP")
        self.manager.adicionar_servidor("REG_TESTE", {
            "id": 123,
            "nome": "Servidor Teste",
            "tipo": "vm",
            "ip": "10.0.0.10",
            "usuario": "usuario",
            "senha": "senha",
        })

        ok, _ = self.manager.remover_servidor("REG_TESTE", "123")
        reloaded = GerenciadorRegionais(str(self.path)).obter_regional("REG_TESTE")

        self.assertTrue(ok)
        self.assertEqual(reloaded["servidores"], [])

    def test_renomear_regional_descarta_links_auto_e_preserva_manuais(self):
        self.manager.adicionar_regional("REG_CNTRL_MACEIO", "REG_CNTRL_MACEIO")
        regional = self.manager.regionais["regionais"]["REG_CNTRL_MACEIO"]
        regional["links"] = [
            {"id": "auto", "origem_sync": "fortimanager", "fortigate_host": "10.0.0.1"},
            {"id": "manual", "nome": "Link manual"},
        ]
        regional["links_internet_auto"] = [{"id": "auto"}]
        self.manager.salvar_regionais()

        self.manager.atualizar_regional(
            "REG_CNTRL_MACEIO", "REG_CONTROL_MACEIO", "REG_CONTROL_MACEIO"
        )
        reloaded = GerenciadorRegionais(str(self.path)).obter_regional("REG_CONTROL_MACEIO")

        self.assertNotIn("links_internet_auto", reloaded)
        self.assertEqual(["manual"], [link["id"] for link in reloaded["links"]])
