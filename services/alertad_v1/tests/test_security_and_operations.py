from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alertad.contracts import OccurrenceCategory, OperationalOccurrence
from alertad.logging_setup import JsonLogFormatter, sanitize_text
from alertad.parsing import parse_windows_event
from alertad.persistence import EventStore
from alertad.reporting import export_attention_report


FIXTURES = Path(__file__).parent / "fixtures"


class SecurityAndOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "alertad.db"
        self.store = EventStore(self.database)
        self.event = parse_windows_event(
            (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_log_sanitizer_removes_artificial_secrets(self) -> None:
        source = (
            "Authorization: Bearer abc.def.ghi "
            "client_secret=synthetic-secret password:example-password"
        )

        sanitized = sanitize_text(source)

        self.assertNotIn("abc.def.ghi", sanitized)
        self.assertNotIn("synthetic-secret", sanitized)
        self.assertNotIn("example-password", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_log_sanitizer_covers_json_repr_tokens_and_values_with_spaces(self) -> None:
        samples = (
            '{"password": "SYNTHETIC_JSON"}',
            "{'client_secret': 'SYNTHETIC_REPR'}",
            "access_token=SYNTHETIC_ACCESS",
            "refresh_token: SYNTHETIC REFRESH VALUE",
            "Authorization=Basic SYNTHETIC AUTH VALUE",
            "token=SYNTHETIC_TOKEN secret=SYNTHETIC_SECRET",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                sanitized = sanitize_text(sample)
                self.assertIn("[REDACTED]", sanitized)
                self.assertNotIn("SYNTHETIC", sanitized)

    def test_json_formatter_does_not_emit_exception_message_or_secret(self) -> None:
        formatter = JsonLogFormatter()
        try:
            raise RuntimeError("token=synthetic-token")
        except RuntimeError:
            record = logging.LogRecord(
                "alertad.test",
                logging.ERROR,
                __file__,
                1,
                "password=synthetic-password",
                (),
                __import__("sys").exc_info(),
            )

        payload = json.loads(formatter.format(record))

        self.assertEqual(payload["exception_type"], "RuntimeError")
        self.assertNotIn("synthetic-password", payload["message"])
        self.assertNotIn("synthetic-token", json.dumps(payload))

    def test_occurrences_can_be_listed_and_resolved(self) -> None:
        occurrence = OperationalOccurrence(
            OccurrenceCategory.INVALID_EVENT,
            "parser",
            "invalid_event_xml",
            "synthetic-fingerprint",
            datetime.now(timezone.utc),
            "forwardedevents",
        )
        self.store.record_occurrence(occurrence)

        rows = self.store.list_occurrences()
        changed = self.store.resolve_occurrence(rows[0].occurrence_id)

        self.assertTrue(changed)
        self.assertEqual(self.store.list_occurrences(), [])
        self.assertIsNotNone(self.store.list_occurrences(open_only=False)[0].resolved_at_utc)

    def test_purge_is_rejected_and_preserves_pending_and_open_occurrence(self) -> None:
        now = datetime.now(timezone.utc)
        self.store.add_event(self.event, channels=("teams",))
        occurrence = OperationalOccurrence(
            OccurrenceCategory.INVALID_EVENT,
            "parser",
            "invalid_event_xml",
            "open-fingerprint",
            now - timedelta(days=365),
        )
        self.store.record_occurrence(occurrence)
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE events SET received_at_utc = ?",
                ((now - timedelta(days=365)).isoformat(),),
            )

        with self.assertRaisesRegex(RuntimeError, "janela segura de replay"):
            self.store.purge_completed(
                events_before_utc=now - timedelta(days=90),
                resolved_occurrences_before_utc=now - timedelta(days=180),
            )
        self.assertEqual(self.store.event_count(), 1)
        self.assertEqual(self.store.occurrence_count(), 1)

    def test_purge_is_rejected_even_for_terminal_event(self) -> None:
        now = datetime.now(timezone.utc)
        self.store.add_event(self.event, channels=("teams",))
        self.store.record_delivery_attempt(self.event.event_key, "teams", success=True)
        occurrence = OperationalOccurrence(
            OccurrenceCategory.PERMANENT_DELIVERY_ERROR,
            "notifier.teams",
            "permanent_delivery_error",
            "resolved-fingerprint",
            now - timedelta(days=365),
        )
        self.store.record_occurrence(occurrence)
        occurrence_id = self.store.list_occurrences()[0].occurrence_id
        self.store.resolve_occurrence(
            occurrence_id,
            resolved_at_utc=now - timedelta(days=365),
        )
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE events SET received_at_utc = ?",
                ((now - timedelta(days=365)).isoformat(),),
            )

        with self.assertRaisesRegex(RuntimeError, "janela segura de replay"):
            self.store.purge_completed(
                events_before_utc=now - timedelta(days=90),
                resolved_occurrences_before_utc=now - timedelta(days=180),
                batch_size=1,
            )

        self.assertEqual(self.store.event_count(), 1)
        self.assertIsNone(self.store.get_checkpoint("ForwardedEvents"))

    def test_csv_neutralizes_formula_prefix(self) -> None:
        malicious = self.event.__class__(
            **{
                **self.event.__dict__,
                "source_computer": "=SYNTHETIC_FORMULA",
            }
        )
        self.store.add_event(malicious)
        output = Path(self.temporary_directory.name) / "report.csv"

        export_attention_report(self.store, output)
        content = output.read_text(encoding="utf-8-sig")

        self.assertIn("'=SYNTHETIC_FORMULA", content)

    def test_report_rejects_database_and_alias_without_changing_bytes(self) -> None:
        self.store.add_event(self.event)
        before = self.database.read_bytes()

        with self.assertRaisesRegex(ValueError, "arquivos protegidos"):
            export_attention_report(self.store, self.database)

        self.assertEqual(self.database.read_bytes(), before)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            connection.close()

        alias = Path(self.temporary_directory.name) / "database-alias.db"
        os.link(self.database, alias)
        try:
            with self.assertRaisesRegex(ValueError, "alias"):
                export_attention_report(self.store, alias)
            self.assertEqual(self.database.read_bytes(), before)
        finally:
            alias.unlink()


if __name__ == "__main__":
    unittest.main()
