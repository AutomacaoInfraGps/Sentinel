import unittest
from unittest.mock import MagicMock, patch

import verificar_servidores_v2 as verifier_module


class ServerVerifierConnectionTests(unittest.TestCase):
    def setUp(self):
        self.verifier = verifier_module.VerificadorServidoresV2(gerenciador=MagicMock())

    @patch("verificar_servidores_v2.requests.get")
    @patch("verificar_servidores_v2.socket.create_connection")
    def test_vm_uses_configured_tcp_port(self, create_connection, requests_get):
        create_connection.return_value.__enter__.return_value = MagicMock()

        result = self.verifier.verificar_servidor(
            {"nome": "Merak", "ip": "10.119.14.12", "tipo": "vm", "porta": 443},
            "REG_ARARAS",
        )

        self.assertEqual(result["status"], "online")
        self.assertIsNone(result["erro"])
        create_connection.assert_called_once_with(("10.119.14.12", 443), timeout=20.0)
        requests_get.assert_not_called()

    @patch("verificar_servidores_v2.socket.create_connection")
    def test_vm_reports_closed_port(self, create_connection):
        create_connection.side_effect = ConnectionRefusedError()

        result = self.verifier.verificar_servidor(
            {"nome": "VM SSH", "ip": "10.0.0.10", "tipo": "vm", "porta": 22},
            "REG_TESTE",
        )

        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["erro"], "Conexão recusada")

    @patch("verificar_servidores_v2.requests.get")
    def test_idrac_keeps_redfish_check(self, requests_get):
        requests_get.return_value.status_code = 401

        result = self.verifier.verificar_servidor(
            {"nome": "iDRAC", "ip": "10.0.0.20", "tipo": "idrac"},
            "REG_TESTE",
        )

        self.assertEqual(result["status"], "online")
        requests_get.assert_called_once_with(
            "https://10.0.0.20/redfish/v1/",
            timeout=(5, 20),
            verify=False,
        )


if __name__ == "__main__":
    unittest.main()
