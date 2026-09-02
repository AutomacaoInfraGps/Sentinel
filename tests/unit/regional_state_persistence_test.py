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
