from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

from alertad.contracts import DirectoryObject, DirectoryResolution, DirectoryResolutionStatus
from alertad.parsing import parse_windows_event
from alertad.persistence import EventStore
from alertad.sentinel_read import SentinelAlertReader


FIXTURES = Path(__file__).parent / "fixtures"


class SentinelAlertReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "alertad.db"
        self.store = EventStore(self.database, database_mode="dry_run")
        self.event = parse_windows_event(
            (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_lists_sanitized_alert_with_resolved_labels(self) -> None:
        resolution = DirectoryResolution(
            DirectoryResolutionStatus.RESOLVED,
            DirectoryObject(
                self.event.member_sid,
                "usuario.teste",
                "user",
                "EXAMPLE",
                "Usuário Teste",
            ),
        )
        self.store.add_event(self.event, directory_resolution=resolution)

        alert = SentinelAlertReader(self.database).list_recent(limit=1)[0]
        payload = asdict(alert)

        self.assertEqual("EXAMPLE\\usuario.teste", alert.member_label)
        self.assertEqual("EXAMPLE\\operador.teste", alert.actor_label)
        self.assertEqual("Administrators", alert.group_name)
        self.assertEqual("critical", alert.severity)
        self.assertTrue(alert.notification_id.startswith("alertad:"))
        self.assertEqual(self.event.event_key[:12], alert.alert_id)
        self.assertNotIn("raw_xml", payload)
        self.assertNotIn("collection_checkpoint", payload)
        self.assertNotIn("directory_error_code", payload)

    def test_orders_deterministically_and_limits_results(self) -> None:
        newer = replace(
            self.event,
            event_record_id=self.event.event_record_id + 1,
            time_created_utc=self.event.time_created_utc + timedelta(seconds=1),
            time_created_raw=None,
        )
        self.store.add_event(self.event)
        self.store.add_event(newer)

        alerts = SentinelAlertReader(self.database).list_recent(limit=1)

        self.assertEqual(1, len(alerts))
        self.assertEqual(newer.event_record_id, alerts[0].event_record_id)

    def test_status_exposes_only_operational_summary(self) -> None:
        self.store.add_event(self.event)

        status = SentinelAlertReader(self.database).status()

        self.assertEqual(5, status.schema_version)
        self.assertEqual("dry_run", status.database_mode)
        self.assertEqual(1, status.events)
        self.assertEqual(0, status.pending_deliveries)
        self.assertEqual(0, status.failed_deliveries)
        self.assertEqual(0, status.open_occurrences)

    def test_read_does_not_modify_database(self) -> None:
        self.store.add_event(self.event)
        before = self.database.read_bytes()
        before_mtime = self.database.stat().st_mtime_ns

        SentinelAlertReader(self.database).list_recent()

        self.assertEqual(before, self.database.read_bytes())
        self.assertEqual(before_mtime, self.database.stat().st_mtime_ns)

    def test_missing_database_is_not_created(self) -> None:
        missing = Path(self.temporary_directory.name) / "missing.db"

        with self.assertRaisesRegex(ValueError, "não encontrado"):
            SentinelAlertReader(missing)

        self.assertFalse(missing.exists())

    def test_rejects_incompatible_schema_and_invalid_limit(self) -> None:
        incompatible = Path(self.temporary_directory.name) / "future.db"
        connection = sqlite3.connect(incompatible)
        try:
            connection.execute("PRAGMA user_version = 99")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "incompatível"):
            SentinelAlertReader(incompatible).list_recent()
        with self.assertRaisesRegex(ValueError, "entre 1 e 500"):
            SentinelAlertReader(self.database).list_recent(limit=501)

    def test_rejects_corrupted_action_instead_of_mislabeling_alert(self) -> None:
        self.store.add_event(self.event)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE events SET action = 'unexpected' WHERE event_key = ?",
                (self.event.event_key,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "ação inválida"):
            SentinelAlertReader(self.database).list_recent()

    @unittest.skipUnless(os.name == "nt", "hard links do Windows")
    def test_rejects_hard_link_alias(self) -> None:
        alias = Path(self.temporary_directory.name) / "alias.db"
        os.link(self.database, alias)

        with self.assertRaisesRegex(ValueError, "identidade física ambígua"):
            SentinelAlertReader(alias)
