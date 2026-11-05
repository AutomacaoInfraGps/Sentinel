import unittest
from unittest.mock import Mock, patch

import verificar_servidores_v2


class ServerVerifierCliTests(unittest.TestCase):
    @patch("verificar_servidores_v2.VerificadorServidoresV2")
    @patch("builtins.input", side_effect=AssertionError("modo rapido nao pode solicitar entrada"))
    def test_quick_mode_runs_once_without_interaction(self, input_mock, verifier_class):
        verifier = Mock()
        verifier_class.return_value = verifier

        result = verificar_servidores_v2.main(["--modo", "rapido"])

        self.assertEqual(result, 0)
        verifier.verificar_todas_regionais.assert_called_once_with()
        verifier.salvar_resultados.assert_called_once_with()
        verifier.gerar_html_status.assert_called_once_with()
        input_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
