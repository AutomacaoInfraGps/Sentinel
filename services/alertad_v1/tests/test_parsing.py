from __future__ import annotations

import unittest
from pathlib import Path

from alertad.models import Action, GroupScope
from alertad.parsing import EventParseError, UnsupportedEventError, parse_windows_event


FIXTURES = Path(__file__).parent / "fixtures"


class ParsingTests(unittest.TestCase):
    def test_parse_4732_addition(self) -> None:
        event = parse_windows_event((FIXTURES / "event_4732.xml").read_text(encoding="utf-8"))

        self.assertEqual(event.event_id, 4732)
        self.assertEqual(event.action, Action.ADD)
        self.assertEqual(event.group_scope, GroupScope.LOCAL)
        self.assertEqual(event.channel, "Security")
        self.assertEqual(event.source_computer, "DC01.EXAMPLE.LOCAL")
        self.assertEqual(event.target_user_name, "Administrators")
        self.assertIsNone(event.member_name)
        self.assertEqual(event.executor, "EXAMPLE\\operador.teste")

    def test_parse_4733_removal(self) -> None:
        event = parse_windows_event((FIXTURES / "event_4733.xml").read_text(encoding="utf-8"))

        self.assertEqual(event.event_id, 4733)
        self.assertEqual(event.action, Action.REMOVE)
        self.assertEqual(event.group_scope, GroupScope.LOCAL)
        self.assertTrue(event.member_name.startswith("CN=Usuario Teste"))

    def test_reject_unsupported_event(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8").replace(
            "<EventID>4732</EventID>",
            "<EventID>9999</EventID>",
        )
        with self.assertRaises(UnsupportedEventError):
            parse_windows_event(xml)

    def test_supported_event_mapping(self) -> None:
        source = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        expected = {
            4728: (Action.ADD, GroupScope.GLOBAL),
            4729: (Action.REMOVE, GroupScope.GLOBAL),
            4732: (Action.ADD, GroupScope.LOCAL),
            4733: (Action.REMOVE, GroupScope.LOCAL),
            4756: (Action.ADD, GroupScope.UNIVERSAL),
            4757: (Action.REMOVE, GroupScope.UNIVERSAL),
        }

        for event_id, (action, scope) in expected.items():
            with self.subTest(event_id=event_id):
                xml = source.replace("<EventID>4732</EventID>", f"<EventID>{event_id}</EventID>")
                event = parse_windows_event(xml)
                self.assertEqual(event.action, action)
                self.assertEqual(event.group_scope, scope)

    def test_all_six_synthetic_fixtures_parse_independently(self) -> None:
        for event_id in (4728, 4729, 4732, 4733, 4756, 4757):
            with self.subTest(event_id=event_id):
                event = parse_windows_event(
                    (FIXTURES / f"event_{event_id}.xml").read_text(encoding="utf-8")
                )
                self.assertEqual(event.event_id, event_id)
                self.assertTrue(event.source_computer.endswith(".EXAMPLE.LOCAL"))

    def test_reject_missing_member_sid(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8").replace(
            '<Data Name="MemberSid">S-1-5-21-1000000000-2000000000-3000000000-1101</Data>',
            "",
        )
        with self.assertRaisesRegex(EventParseError, "MemberSid"):
            parse_windows_event(xml)

    def test_rejects_wrong_provider_duplicate_field_and_nonpositive_record(self) -> None:
        source = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        wrong_provider = source.replace(
            'Name="Microsoft-Windows-Security-Auditing"',
            'Name="Synthetic-Other-Provider"',
        )
        duplicate = source.replace(
            "</EventData>",
            '<Data Name="MemberSid">S-1-5-18</Data></EventData>',
        )
        invalid_record = source.replace(
            "<EventRecordID>100001</EventRecordID>",
            "<EventRecordID>0</EventRecordID>",
        )

        with self.assertRaisesRegex(EventParseError, "Provider"):
            parse_windows_event(wrong_provider)
        with self.assertRaisesRegex(EventParseError, "duplicado"):
            parse_windows_event(duplicate)
        with self.assertRaisesRegex(EventParseError, "positivo"):
            parse_windows_event(invalid_record)

    def test_rejects_timestamp_without_timezone(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8").replace(
            "2026-09-21T17:11:55.0388367Z",
            "2026-09-21T17:11:55.038836",
        )

        with self.assertRaisesRegex(EventParseError, "fuso horário"):
            parse_windows_event(xml)

    def test_event_key_is_stable(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        first = parse_windows_event(xml)
        second = parse_windows_event(xml)

        self.assertEqual(first.event_key, second.event_key)
        self.assertEqual(len(first.event_key), 64)

    def test_event_key_preserves_seventh_fractional_second_digit(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        first = parse_windows_event(xml)
        second = parse_windows_event(xml.replace(".0388367Z", ".0388368Z"))

        # datetime do Python preserva microssegundos; a identidade usa também o
        # timestamp textual para não perder o sétimo dígito do Event Log.
        self.assertEqual(first.time_created_utc, second.time_created_utc)
        self.assertNotEqual(first.time_created_raw, second.time_created_raw)
        self.assertNotEqual(first.event_key, second.event_key)


if __name__ == "__main__":
    unittest.main()
