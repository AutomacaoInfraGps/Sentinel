import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gerenciar_contatos_email import GerenciadorContatosEmail


class GerenciadorContatosEmailTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = GerenciadorContatosEmail(Path(self.temp_dir.name) / "environment.json")
        self.registro = {
            "NOME_REGIONAL": "PADRAO SLA",
            "NOME_REG_FORTI": "REPORT DE SEGURANCA-FGT_ORMEC_PARA",
            "NOME_DIRETOR_1": "Maria Silva",
            "EMAIL_DIRETOR": "maria@example.com",
            "NOME_GERENTE": "SEM_GERENTE",
            "EMAIL_GERENTE": "SEM_GERENTE",
            "NOME_APOIO_1": "Joao Souza",
            "EMAIL_APOIO_1": "joao@example.com",
            "NOME_APOIO_2": "",
            "EMAIL_APOIO_2": "",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_localiza_pela_correspondencia_forti(self):
        with patch.object(self.manager, "listar_registros", return_value=[self.registro]):
            result = self.manager.localizar_registro(nome_reg_forti="report_de seguranca-fgt ormec para")
        self.assertEqual(result["NOME_REGIONAL"], "PADRAO SLA")

    def test_monta_destinatarios_com_primeiros_nomes(self):
        result = self.manager.montar_destinatarios(self.registro)
        self.assertEqual(result["emails"], ["maria@example.com", "joao@example.com"])
        self.assertEqual([item["primeiro_nome"] for item in result["contatos"]], ["Maria", "Joao"])


if __name__ == "__main__":
    unittest.main()
