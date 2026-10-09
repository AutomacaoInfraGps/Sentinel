import os
import unittest
from unittest.mock import Mock, patch

from sofia.n8n_client import SofiaN8nError, consultar_sofia


class SofiaN8nClientTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "SENTINEL_SOFIA_N8N_WEBHOOK_URL": "http://127.0.0.1:15678/webhook/sofia-alertas-v1",
                "SENTINEL_SOFIA_N8N_WEBHOOK_TOKEN": "t" * 32,
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    @patch("sofia.n8n_client.requests.post")
    def test_sends_only_message_and_authorized_regionals(self, post):
        post.return_value = Mock(
            status_code=200,
            json=lambda: {"reply": "RESUMO OPERACIONAL\nTotal: 2"},
        )

        reply = consultar_sofia(
            mensagem="Resumo dos alertas atuais",
            allowed_regionals={"REG_UBERLANDIA", "REG_ABC"},
        )

        self.assertEqual(reply, "RESUMO OPERACIONAL\nTotal: 2")
        request = post.call_args
        self.assertEqual(
            request.kwargs["json"]["allowed_regionals"],
            ["REG_ABC", "REG_UBERLANDIA"],
        )
        self.assertEqual(request.kwargs["headers"]["X-Sentinel-Sofia-Token"], "t" * 32)
        self.assertFalse(request.kwargs["allow_redirects"])

    def test_denies_plain_http_outside_the_local_tunnel(self):
        with patch.dict(
            os.environ,
            {"SENTINEL_SOFIA_N8N_WEBHOOK_URL": "http://10.254.12.66:5678/webhook/test"},
        ):
            with self.assertRaises(SofiaN8nError):
                consultar_sofia(
                    mensagem="Resumo dos alertas atuais",
                    allowed_regionals={"REG_ABC"},
                )

    def test_empty_scope_does_not_call_the_orchestrator(self):
        with patch("sofia.n8n_client.requests.post") as post:
            reply = consultar_sofia(
                mensagem="Resumo dos alertas atuais",
                allowed_regionals=set(),
            )
        self.assertIn("Nao ha regionais", reply)
        post.assert_not_called()

    @patch("sofia.n8n_client.requests.post")
    def test_removes_space_entities_from_reply(self, post):
        post.return_value = Mock(
            status_code=200,
            json=lambda: {"reply": "Linha 1.&#x20;  \nLinha 2.&nbsp;"},
        )

        reply = consultar_sofia(
            mensagem="Resumo",
            allowed_regionals={"REG_ABC"},
        )

        self.assertEqual(reply, "Linha 1.\nLinha 2.")


if __name__ == "__main__":
    unittest.main()
