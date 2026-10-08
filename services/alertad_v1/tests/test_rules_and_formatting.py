from __future__ import annotations

import unittest
from pathlib import Path

from alertad.contracts import DirectoryObject, DirectoryResolution, DirectoryResolutionStatus
from alertad.formatting import event_attentions, format_alert, format_alert_html
from alertad.parsing import parse_windows_event
from alertad.rules import GroupMatcher


FIXTURES = Path(__file__).parent / "fixtures"


class RulesAndFormattingTests(unittest.TestCase):
    def test_fixed_group_is_case_insensitive(self) -> None:
        self.assertTrue(GroupMatcher().matches_name("domain admins"))

    def test_prefix_group_is_case_insensitive(self) -> None:
        matcher = GroupMatcher()
        self.assertTrue(matcher.matches_name("GGS_SUPORTE_REGIONAL"))
        self.assertTrue(matcher.matches_name("ggs_suporte_teste"))

    def test_unrelated_group_is_rejected(self) -> None:
        self.assertFalse(GroupMatcher().matches_name("Usuarios do Dominio"))

    def test_missing_member_name_creates_attention(self) -> None:
        event = parse_windows_event((FIXTURES / "event_4732.xml").read_text(encoding="utf-8"))
        attentions = event_attentions(event)

        self.assertEqual(len(attentions), 1)
        self.assertIn("SID", attentions[0])

    def test_alert_contains_required_information(self) -> None:
        event = parse_windows_event((FIXTURES / "event_4732.xml").read_text(encoding="utf-8"))
        message = format_alert(event)

        self.assertIn("SENTINEL | ALERTA DO ACTIVE DIRECTORY", message)
        self.assertIn("Movimentação detectada", message)
        self.assertIn("Se a alteração não for reconhecida", message)
        self.assertIn("Ação: usuário adicionado", message)
        self.assertIn("Grupo: Administrators", message)
        self.assertIn("Executor: EXAMPLE\\operador.teste", message)
        self.assertIn("Data/hora: 21/09/2026 14:11:55", message)
        self.assertIn("Pontos de atenção", message)
        self.assertIn("Mensagem automática do Sentinel | AlertAD", message)
        self.assertNotIn("Evento:", message)
        self.assertNotIn("Registro:", message)
        self.assertNotIn("Alert ID:", message)

        html = format_alert_html(message)
        self.assertIn("<strong>Ação:</strong>", html)
        self.assertIn("<strong>Grupo:</strong>", html)

    def test_resolved_directory_user_replaces_sid_in_snapshot(self) -> None:
        event = parse_windows_event((FIXTURES / "event_4732.xml").read_text(encoding="utf-8"))
        resolution = DirectoryResolution(
            DirectoryResolutionStatus.RESOLVED,
            DirectoryObject(event.member_sid, "usuario.teste", "user", "EXAMPLE"),
        )

        message = format_alert(event, resolution)

        self.assertIn("Usuário: EXAMPLE\\usuario.teste", message)
        self.assertNotIn("Nome do usuário não informado", message)

    def test_member_name_is_preserved_when_directory_resolution_fails(self) -> None:
        with_name = parse_windows_event(
            (FIXTURES / "event_4733.xml").read_text(encoding="utf-8")
        )
        resolution = DirectoryResolution(
            DirectoryResolutionStatus.TEMPORARY_FAILURE,
            error_code="synthetic",
        )

        message = format_alert(with_name, resolution)

        self.assertIn("Usuário: Usuario Teste", message)
        self.assertNotIn("OU=Usuarios", message)
        self.assertNotIn("exibindo o SID", message)

    def test_unsuccessful_directory_states_fall_back_to_member_sid(self) -> None:
        without_name = parse_windows_event(
            (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        )
        for status in (
            DirectoryResolutionStatus.NOT_FOUND,
            DirectoryResolutionStatus.TEMPORARY_FAILURE,
            DirectoryResolutionStatus.PERMANENT_FAILURE,
        ):
            with self.subTest(status=status):
                message = format_alert(
                    without_name,
                    DirectoryResolution(status, error_code="synthetic"),
                )
                self.assertIn(f"Usuário: {without_name.member_sid}", message)
                self.assertIn("exibindo o SID", message)


if __name__ == "__main__":
    unittest.main()

