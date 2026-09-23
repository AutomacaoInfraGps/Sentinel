import unittest
from pathlib import Path
from unittest.mock import patch

from sofia import engine


class SofiaTextTest(unittest.TestCase):
    def tearDown(self):
        engine._carregar_conhecimento.cache_clear()

    def _reply(self, message):
        with patch.object(engine, "identificar_regional", return_value=None):
            return engine.processar_mensagem_sofia(
                usuario="teste",
                mensagem=message,
                allowed_regionals=set(),
            )

    def test_switch_message_has_valid_portuguese_accents(self):
        with (
            patch.object(engine, "identificar_regional", return_value=None),
            patch.object(engine, "alertas_switches_ativos", return_value=[]),
        ):
            reply = engine.processar_mensagem_sofia(
                usuario="teste",
                mensagem="tem alerta de switch?",
                allowed_regionals=set(),
            )

        self.assertIn("Não há alertas ativos", reply)
        self.assertNotIn("Ã", reply)

    def test_guided_help_and_knowledge_use_accented_text(self):
        help_reply = self._reply("qual e a cor do sistema?")
        dashboard_reply = self._reply("me explica o dashboard")
        security_reply = self._reply("como funciona a seguranca da sofia?")

        self.assertIn("Ainda não entendi", help_reply)
        self.assertIn("não executo ações reais", help_reply)
        self.assertIn("informações operacionais", dashboard_reply)
        self.assertIn("Segurança da SofIA", security_reply)
        self.assertIn("segura por padrão", security_reply)

    def test_warning_status_is_presented_as_atencao(self):
        with (
            patch.object(engine, "identificar_regional", return_value=None),
            patch.object(
                engine,
                "resumo_servidores",
                return_value={"total": 1, "warning": 1},
            ),
        ):
            reply = engine.processar_mensagem_sofia(
                usuario="teste",
                mensagem="como estao os servidores?",
                allowed_regionals=set(),
            )

        self.assertIn("1 em atenção", reply)

    def test_user_facing_sofia_files_do_not_contain_mojibake(self):
        root = Path(__file__).resolve().parents[2]
        paths = [
            root / "sofia" / "engine.py",
            root / "sofia" / "routes.py",
            root / "static" / "sofia" / "sofia.js",
            root / "templates" / "components" / "sofia_chat.html",
            *(root / "sofia" / "knowledge").glob("*.md"),
        ]

        for path in paths:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("Ã", text)
                self.assertNotIn("Â", text)
                self.assertNotIn("�", text)


if __name__ == "__main__":
    unittest.main()
