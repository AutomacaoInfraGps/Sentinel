from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from alertad.contracts import (
    CheckpointAdvance,
    DirectoryObject,
    DirectoryResolution,
    DirectoryResolutionStatus,
    EventCheckpoint,
    OccurrenceCategory,
    OperationalOccurrence,
)
from alertad.formatting import format_alert
from alertad.parsing import parse_windows_event
from alertad.persistence import (
    CURRENT_SCHEMA_VERSION,
    CheckpointConflictError,
    EventIdentityConflictError,
    EventStore,
)
from alertad.reporting import export_attention_report


FIXTURES = Path(__file__).parent / "fixtures"


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "alertad.db"
        self.store = EventStore(self.database, max_delivery_attempts=6)
        self.event = parse_windows_event(
            (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        )

    @staticmethod
    def checkpoint(sequence: int, value: str | None = None) -> EventCheckpoint:
        return EventCheckpoint(
            "ForwardedEvents",
            value or f"bookmark-{sequence}",
            "generation-a",
            sequence,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_duplicate_event_is_not_inserted_twice(self) -> None:
        self.assertTrue(self.store.add_event(self.event))
        self.assertFalse(self.store.add_event(self.event))
        self.assertEqual(self.store.event_count(), 1)
        self.assertEqual(len(self.store.pending_deliveries()), 2)

    def test_dry_run_store_never_creates_deliveries_even_with_default_argument(self) -> None:
        dry_database = Path(self.temporary_directory.name) / "dry.db"
        dry_store = EventStore(dry_database, database_mode="dry_run")

        self.assertTrue(dry_store.add_event(self.event))

        self.assertEqual(dry_store.event_count(), 1)
        self.assertEqual(dry_store.pending_deliveries(), [])
        with self.assertRaisesRegex(RuntimeError, "Modo do banco incompatível"):
            EventStore(dry_database, database_mode="production")

    def test_store_rejects_delivery_attempt_limit_incompatible_with_v1(self) -> None:
        for total in (1, 5, 7):
            with self.subTest(total=total):
                with self.assertRaisesRegex(ValueError, "deve ser 6"):
                    EventStore(
                        Path(self.temporary_directory.name) / f"invalid-{total}.db",
                        max_delivery_attempts=total,
                    )

    def test_pending_state_survives_store_restart(self) -> None:
        self.store.add_event(self.event)

        reopened_store = EventStore(self.database, max_delivery_attempts=6)

        self.assertFalse(reopened_store.add_event(self.event))
        pending = reopened_store.pending_deliveries()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0].alert_message, format_alert(self.event))

    def test_persists_complete_normalized_snapshot(self) -> None:
        resolution = DirectoryResolution(
            DirectoryResolutionStatus.RESOLVED,
            DirectoryObject(
                sid=self.event.member_sid,
                account_name="usuario.teste",
                object_type="user",
                domain_name="EXAMPLE",
                display_name="Usuário Teste",
            ),
        )

        self.store.add_event(self.event, directory_resolution=resolution)
        snapshot = self.store.get_event_snapshot(self.event.event_key)

        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot.complete)
        self.assertEqual(snapshot.action, "add")
        self.assertEqual(snapshot.group_scope, "local")
        self.assertEqual(snapshot.subject_user_name, "operador.teste")
        self.assertEqual(snapshot.directory_resolution_status, "resolved")
        self.assertEqual(snapshot.directory_account_name, "usuario.teste")
        self.assertIn("Grupo: Administrators", snapshot.message)

    def test_event_deliveries_and_checkpoint_commit_together(self) -> None:
        checkpoint = self.checkpoint(100001)

        self.store.add_event(
            self.event,
            checkpoint_advance=CheckpointAdvance(None, checkpoint),
        )
        reopened_store = EventStore(self.database)

        self.assertEqual(
            reopened_store.get_checkpoint("ForwardedEvents"),
            checkpoint,
        )
        self.assertEqual(reopened_store.event_count(), 1)
        self.assertEqual(len(reopened_store.pending_deliveries()), 2)

    def test_failure_before_checkpoint_rolls_back_whole_event(self) -> None:
        checkpoint = self.checkpoint(100001)

        with patch.object(
            self.store,
            "_advance_checkpoint",
            side_effect=sqlite3.OperationalError("falha simulada"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.add_event(
                    self.event,
                    checkpoint_advance=CheckpointAdvance(None, checkpoint),
                )

        reopened_store = EventStore(self.database)
        self.assertEqual(reopened_store.event_count(), 0)
        self.assertEqual(reopened_store.pending_deliveries(), [])
        self.assertIsNone(reopened_store.get_checkpoint("ForwardedEvents"))

    def test_abrupt_process_exit_does_not_commit_partial_ingestion(self) -> None:
        crash_database = Path(self.temporary_directory.name) / "crash.db"
        source_root = Path(__file__).parent.parent / "src"
        fixture = FIXTURES / "event_4732.xml"
        child_code = """
import os
import sqlite3
import sys

sys.path.insert(0, sys.argv[3])
from alertad.contracts import CheckpointAdvance, EventCheckpoint
from alertad.parsing import parse_windows_event
from alertad.persistence import EventStore

class CrashStore(EventStore):
    def _connect(self):
        connection = super()._connect()
        connection.create_function("crash_process", 0, lambda: os._exit(23))
        return connection

store = CrashStore(sys.argv[1])
with store._connection() as connection:
    connection.execute(
        '''
        CREATE TRIGGER crash_before_checkpoint
        BEFORE INSERT ON collection_checkpoints
        BEGIN
            SELECT crash_process();
        END
        '''
    )
event = parse_windows_event(open(sys.argv[2], encoding="utf-8").read())
store.add_event(
    event,
    checkpoint_advance=CheckpointAdvance(
        None,
        EventCheckpoint("ForwardedEvents", "bookmark-crash", "generation-a", 1),
    ),
)
"""
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                child_code,
                str(crash_database),
                str(fixture),
                str(source_root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 23, process.stderr)
        reopened_store = EventStore(crash_database)
        self.assertEqual(reopened_store.event_count(), 0)
        self.assertEqual(reopened_store.pending_deliveries(), [])
        self.assertIsNone(reopened_store.get_checkpoint("ForwardedEvents"))

    def test_duplicate_advances_checkpoint_without_duplicate_delivery(self) -> None:
        first = self.checkpoint(1)
        second = self.checkpoint(2)

        self.assertTrue(
            self.store.add_event(
                self.event,
                checkpoint_advance=CheckpointAdvance(None, first),
            )
        )
        self.assertFalse(
            self.store.add_event(
                self.event,
                checkpoint_advance=CheckpointAdvance(first, second),
            )
        )

        self.assertEqual(self.store.get_checkpoint("ForwardedEvents"), second)
        self.assertEqual(self.store.event_count(), 1)
        self.assertEqual(len(self.store.pending_deliveries()), 2)

    def test_checkpoint_rejects_regression_during_overlap(self) -> None:
        current = self.checkpoint(100)
        self.store.advance_checkpoint(CheckpointAdvance(None, current))

        with self.assertRaisesRegex(ValueError, "exatamente uma sequência"):
            CheckpointAdvance(current, self.checkpoint(99))

        self.assertEqual(self.store.get_checkpoint(" forwardedEVENTS "), current)

    def test_checkpoint_does_not_skip_failed_intermediate_item(self) -> None:
        current = self.checkpoint(100)
        self.store.add_event(self.event)
        self.store.advance_checkpoint(CheckpointAdvance(None, current))

        with self.assertRaisesRegex(ValueError, "exatamente uma sequência"):
            self.store.add_event(
                self.event,
                checkpoint_advance=CheckpointAdvance(current, self.checkpoint(102)),
            )

        self.assertEqual(self.store.get_checkpoint("ForwardedEvents"), current)
        self.assertEqual(self.store.event_count(), 1)
        self.assertEqual(len(self.store.pending_deliveries()), 2)

    def test_checkpoint_rejects_stale_expected_state(self) -> None:
        first = self.checkpoint(100)
        second = self.checkpoint(101)
        self.store.advance_checkpoint(CheckpointAdvance(None, first))
        self.store.advance_checkpoint(CheckpointAdvance(first, second))

        with self.assertRaises(CheckpointConflictError):
            self.store.advance_checkpoint(
                CheckpointAdvance(first, self.checkpoint(101, "outro-bookmark"))
            )

        self.assertEqual(self.store.get_checkpoint("ForwardedEvents"), second)

    def test_checkpoint_source_is_canonical_on_write_and_read(self) -> None:
        checkpoint = EventCheckpoint(
            "  ForwardedEvents  ",
            "bookmark-1",
            "generation-a",
            1,
        )

        self.store.advance_checkpoint(CheckpointAdvance(None, checkpoint))

        persisted = self.store.get_checkpoint(" FORWARDEDEVENTS ")
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.source, "forwardedevents")

    def test_channels_have_independent_status(self) -> None:
        self.store.add_event(self.event)
        sent = self.store.record_delivery_attempt(
            self.event.event_key,
            "email",
            success=True,
        )
        pending = self.store.pending_deliveries()

        self.assertEqual(sent.status, "sent")
        self.assertEqual([delivery.channel for delivery in pending], ["teams"])

    def test_delivery_fails_after_six_attempts(self) -> None:
        self.store.add_event(self.event)
        delivery = None
        for attempt in range(6):
            delivery = self.store.record_delivery_attempt(
                self.event.event_key,
                "teams",
                success=False,
                error=f"falha {attempt + 1}",
            )

        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.attempts, 6)
        self.assertEqual(delivery.last_error, "falha 6")

    def test_delivery_schedule_and_failure_kind_survive_restart(self) -> None:
        self.store.add_event(self.event)
        next_attempt = datetime.now(timezone.utc) + timedelta(seconds=30)
        self.store.record_delivery_attempt(
            self.event.event_key,
            "teams",
            success=False,
            error="timeout",
            next_attempt_at_utc=next_attempt,
            failure_kind="temporary",
        )

        reopened_store = EventStore(self.database)
        pending = {
            delivery.channel: delivery
            for delivery in reopened_store.pending_deliveries(
                now=next_attempt + timedelta(seconds=1)
            )
        }

        self.assertEqual(pending["teams"].attempts, 1)
        self.assertEqual(pending["teams"].last_error, "timeout")
        self.assertEqual(pending["teams"].failure_kind, "temporary")
        self.assertEqual(pending["teams"].next_attempt_at_utc, next_attempt)

    def test_future_delivery_is_not_ready_before_due_time(self) -> None:
        self.store.add_event(self.event, channels=("teams",))
        due = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.store.record_delivery_attempt(
            self.event.event_key,
            "teams",
            success=False,
            next_attempt_at_utc=due,
        )

        self.assertEqual(self.store.pending_deliveries(now=due - timedelta(seconds=1)), [])
        self.assertEqual(len(self.store.pending_deliveries(now=due)), 1)

    def test_pending_delivery_query_is_limited(self) -> None:
        self.store.add_event(self.event)

        self.assertEqual(len(self.store.pending_deliveries(limit=1)), 1)
        with self.assertRaisesRegex(ValueError, "entre 1 e 500"):
            self.store.pending_deliveries(limit=501)

    def test_incomplete_and_whitespace_snapshots_are_blocked(self) -> None:
        self.store.add_event(self.event, channels=("teams",))
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE events SET alert_message = '   ' WHERE event_key = ?",
                (self.event.event_key,),
            )

        snapshot = self.store.get_event_snapshot(self.event.event_key)
        self.assertIsNotNone(snapshot)
        self.assertFalse(snapshot.complete)
        self.assertEqual(self.store.pending_deliveries(), [])
        self.assertEqual(len(self.store.blocked_deliveries()), 1)

    def test_concurrent_delivery_attempts_finish_in_consistent_state(self) -> None:
        self.store.add_event(self.event, channels=("teams",))
        for attempt in range(3):
            self.store.record_delivery_attempt(
                self.event.event_key,
                "teams",
                success=False,
                error=f"falha {attempt + 1}",
            )

        def fail_once(number: int):
            return self.store.record_delivery_attempt(
                self.event.event_key,
                "teams",
                success=False,
                error=f"concorrente {number}",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(fail_once, (1, 2)))

        final = self.store.record_delivery_attempt(
            self.event.event_key,
            "teams",
            success=False,
        )
        self.assertEqual(final.status, "failed")
        self.assertEqual(final.attempts, 6)
        self.assertEqual({result.attempts for result in results}, {4, 5})

    def test_occurrence_and_checkpoint_are_atomic_and_deduplicated(self) -> None:
        first = self.checkpoint(1, "bookmark-invalid-1")
        second = self.checkpoint(2, "bookmark-invalid-2")
        occurrence = OperationalOccurrence(
            category=OccurrenceCategory.INVALID_EVENT,
            component="parser",
            reason_code="invalid_xml",
            fingerprint="event-fingerprint",
            occurred_at_utc=datetime.now(timezone.utc),
            source="ForwardedEvents",
        )

        self.assertTrue(
            self.store.record_occurrence(
                occurrence,
                checkpoint_advance=CheckpointAdvance(None, first),
            )
        )
        self.assertFalse(
            self.store.record_occurrence(
                occurrence,
                checkpoint_advance=CheckpointAdvance(first, second),
            )
        )

        reopened_store = EventStore(self.database)
        self.assertEqual(reopened_store.occurrence_count(), 1)
        self.assertEqual(
            reopened_store.get_checkpoint("ForwardedEvents"),
            second,
        )

    def test_occurrence_is_rolled_back_when_checkpoint_cannot_be_saved(self) -> None:
        checkpoint = self.checkpoint(1, "bookmark-invalid")
        occurrence = OperationalOccurrence(
            category=OccurrenceCategory.INVALID_EVENT,
            component="parser",
            reason_code="invalid_xml",
            fingerprint="event-fingerprint",
            occurred_at_utc=datetime.now(timezone.utc),
        )

        with patch.object(
            self.store,
            "_advance_checkpoint",
            side_effect=sqlite3.OperationalError("falha simulada"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.record_occurrence(
                    occurrence,
                    checkpoint_advance=CheckpointAdvance(None, checkpoint),
                )

        reopened_store = EventStore(self.database)
        self.assertEqual(reopened_store.occurrence_count(), 0)
        self.assertIsNone(reopened_store.get_checkpoint("ForwardedEvents"))

    def test_migrates_legacy_database_without_inventing_snapshot(self) -> None:
        legacy_database = Path(self.temporary_directory.name) / "legacy.db"
        self._create_legacy_database(legacy_database)

        migrated_store = EventStore(legacy_database)
        snapshot = migrated_store.get_event_snapshot(self.event.legacy_event_key)

        self.assertEqual(migrated_store.schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNotNone(snapshot)
        self.assertFalse(snapshot.complete)
        self.assertIsNone(snapshot.message)
        self.assertEqual(migrated_store.pending_deliveries(), [])
        self.assertEqual(len(migrated_store.blocked_deliveries()), 1)

        # Sem timestamp textual integral, equivalência com a chave v2 não pode
        # ser comprovada e a aplicação falha explicitamente.
        with self.assertRaises(EventIdentityConflictError):
            migrated_store.add_event(self.event)
        self.assertEqual(migrated_store.event_count(), 1)
        self.assertEqual(migrated_store.pending_deliveries(), [])
        self.assertEqual(len(migrated_store.blocked_deliveries()), 1)

    def test_migrates_v2_identity_without_reidentifying_existing_event(self) -> None:
        v2_database = Path(self.temporary_directory.name) / "v2.db"
        self._create_v2_database(v2_database)

        migrated_store = EventStore(v2_database)

        self.assertEqual(migrated_store.event_count(), 1)
        with self.assertRaises(EventIdentityConflictError):
            migrated_store.add_event(self.event)
        self.assertEqual(migrated_store.event_count(), 1)
        self.assertEqual(len(migrated_store.pending_deliveries()), 1)
        snapshot = migrated_store.get_event_snapshot(self.event.legacy_event_key)
        self.assertIsNotNone(snapshot)
        sent = migrated_store.record_delivery_attempt(
            self.event.legacy_event_key,
            "teams",
            success=True,
        )
        self.assertEqual(sent.event_key, self.event.legacy_event_key)
        self.assertEqual(sent.status, "sent")

    def test_precise_legacy_alias_accepts_legitimate_replay_and_binds_v2_key(self) -> None:
        database = Path(self.temporary_directory.name) / "precise-v3.db"
        self._create_v2_database(database)
        connection = sqlite3.connect(database)
        try:
            connection.row_factory = sqlite3.Row
            EventStore._migrate_to_v3(connection)
            connection.execute(
                "UPDATE events SET time_created_raw = ?",
                (self.event.time_created_raw,),
            )
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
        finally:
            connection.close()

        migrated = EventStore(database)

        self.assertFalse(migrated.add_event(self.event))
        self.assertEqual(migrated.event_count(), 1)
        snapshot = migrated.get_event_snapshot(self.event.event_key)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.event_key, self.event.legacy_event_key)

    def test_legacy_alias_collision_on_seventh_digit_is_explicit(self) -> None:
        first_xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        first_xml = first_xml.replace(".0388367Z", ".1234561Z")
        second_xml = first_xml.replace(".1234561Z", ".1234562Z")
        first = parse_windows_event(first_xml)
        second = parse_windows_event(second_xml)
        self.assertEqual(first.legacy_event_key, second.legacy_event_key)
        self.assertNotEqual(first.event_key, second.event_key)
        database = Path(self.temporary_directory.name) / "collision-v2.db"
        original_event = self.event
        self.event = first
        try:
            self._create_v2_database(database)
        finally:
            self.event = original_event
        migrated = EventStore(database)

        with self.assertRaisesRegex(EventIdentityConflictError, "ambíguo"):
            migrated.add_event(second)

        self.assertEqual(migrated.event_count(), 1)
        self.assertIsNone(migrated.get_event_snapshot(second.event_key))

    def test_exact_identity_rejects_divergent_snapshot(self) -> None:
        self.store.add_event(self.event)
        divergent = replace(self.event, member_sid="S-1-5-21-9-9-9-9999")

        with self.assertRaisesRegex(EventIdentityConflictError, "snapshot"):
            self.store.add_event(divergent)

        self.assertEqual(self.store.event_count(), 1)

    def test_migrates_v3_to_current_as_production_without_changing_checkpoint(self) -> None:
        v3_database = Path(self.temporary_directory.name) / "v3.db"
        connection = sqlite3.connect(v3_database)
        connection.row_factory = sqlite3.Row
        try:
            EventStore._migrate_to_v1(connection)
            EventStore._migrate_to_v2(connection)
            EventStore._migrate_to_v3(connection)
            checkpoint = self.checkpoint(7)
            connection.execute(
                """
                INSERT INTO collection_checkpoints (
                    source, value, updated_at_utc, generation, sequence
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.source,
                    checkpoint.value,
                    datetime.now(timezone.utc).isoformat(),
                    checkpoint.generation,
                    checkpoint.sequence,
                ),
            )
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
        finally:
            connection.close()

        migrated = EventStore(v3_database)

        self.assertEqual(migrated.schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertEqual(migrated.database_mode, "production")
        self.assertEqual(migrated.get_checkpoint("ForwardedEvents"), checkpoint)
        with self.assertRaisesRegex(RuntimeError, "Modo do banco incompatível"):
            EventStore(v3_database, database_mode="dry_run")

    def test_rejects_legacy_database_missing_deliveries_table(self) -> None:
        database = Path(self.temporary_directory.name) / "legacy-incomplete.db"
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE events (event_key TEXT PRIMARY KEY)")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "legado incompleto"):
            EventStore(database)

    def test_rejects_schema_with_columns_but_without_required_foreign_key(self) -> None:
        database = Path(self.temporary_directory.name) / "no-fk.db"
        connection = sqlite3.connect(database)
        try:
            connection.executescript(
                """
                CREATE TABLE events (
                    event_key TEXT PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    event_record_id INTEGER NOT NULL,
                    source_computer TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    time_created_utc TEXT NOT NULL,
                    target_user_name TEXT NOT NULL,
                    member_sid TEXT NOT NULL,
                    attentions_json TEXT NOT NULL,
                    received_at_utc TEXT NOT NULL
                );
                CREATE TABLE deliveries (
                    event_key TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'sent', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (event_key, channel)
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "foreign key"):
            EventStore(database)

    def test_rejects_current_schema_missing_required_index(self) -> None:
        with self.store._connection() as connection:
            connection.execute("DROP INDEX idx_deliveries_pending")

        with self.assertRaisesRegex(RuntimeError, "índice ausente"):
            EventStore(self.database)

    def test_rejects_current_schema_without_occurrence_uniqueness(self) -> None:
        with self.store._connection() as connection:
            connection.executescript(
                """
                ALTER TABLE operational_occurrences RENAME TO old_occurrences;
                CREATE TABLE operational_occurrences (
                    occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    component TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL,
                    source TEXT,
                    resolved_at_utc TEXT,
                    created_at_utc TEXT NOT NULL
                );
                DROP TABLE old_occurrences;
                CREATE INDEX idx_occurrences_open
                ON operational_occurrences(category, resolved_at_utc, occurred_at_utc);
                """
            )

        with self.assertRaisesRegex(RuntimeError, "unicidade obrigatória"):
            EventStore(self.database)

    def test_rejects_current_schema_event_without_identity_alias(self) -> None:
        self.store.add_event(self.event)
        with self.store._connection() as connection:
            connection.execute(
                "DELETE FROM event_identity_aliases WHERE alias_key = ?",
                (self.event.event_key,),
            )

        with self.assertRaisesRegex(RuntimeError, "sem alias de identidade"):
            EventStore(self.database)

    def test_rejects_database_from_newer_application_version(self) -> None:
        future_database = Path(self.temporary_directory.name) / "future.db"
        connection = sqlite3.connect(future_database)
        try:
            connection.execute("PRAGMA user_version = 999")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "superior ao suportado"):
            EventStore(future_database)

    def test_failed_migration_does_not_advance_schema_version(self) -> None:
        malformed_database = Path(self.temporary_directory.name) / "malformed.db"
        connection = sqlite3.connect(malformed_database)
        try:
            connection.execute("CREATE TABLE events (event_key TEXT PRIMARY KEY)")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "legado incompleto"):
            EventStore(malformed_database)

        connection = sqlite3.connect(malformed_database)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(events)")
            }
        finally:
            connection.close()
        self.assertEqual(version, 0)
        self.assertEqual(columns, {"event_key"})

    def test_v5_migration_rolls_back_column_and_version_on_failure(self) -> None:
        database = Path(self.temporary_directory.name) / "migration-v4.db"
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            EventStore._migrate_to_v1(connection)
            EventStore._migrate_to_v2(connection)
            EventStore._migrate_to_v3(connection)
            EventStore._migrate_to_v4(connection, "production")
            connection.execute("PRAGMA user_version = 4")
            connection.commit()
        finally:
            connection.close()

        def fail_after_schema_change(target: sqlite3.Connection) -> None:
            EventStore._add_column(target, "deliveries", "claim_token", "TEXT")
            raise sqlite3.OperationalError("synthetic interrupted migration")

        with patch.object(
            EventStore,
            "_migrate_to_v5",
            side_effect=fail_after_schema_change,
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "interrupted"):
                EventStore(database)

        connection = sqlite3.connect(database)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(deliveries)")
            }
        finally:
            connection.close()
        self.assertEqual(version, 4)
        self.assertNotIn("claim_token", columns)

        migrated = EventStore(database)
        self.assertEqual(migrated.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_rejects_unc_database_path_before_creating_files(self) -> None:
        with self.assertRaisesRegex(ValueError, "compartilhamento de rede"):
            EventStore(r"\\servidor-ficticio\compartilhamento\alertad.db")

    def test_relative_database_path_is_fixed_when_store_is_created(self) -> None:
        first_directory = Path(self.temporary_directory.name) / "first"
        second_directory = Path(self.temporary_directory.name) / "second"
        first_directory.mkdir()
        second_directory.mkdir()
        original_directory = Path.cwd()
        try:
            os.chdir(first_directory)
            store = EventStore("relative.db")
            os.chdir(second_directory)
            store.add_event(self.event)
        finally:
            os.chdir(original_directory)

        self.assertEqual(store.event_count(), 1)
        self.assertTrue((first_directory / "relative.db").exists())
        self.assertFalse((second_directory / "relative.db").exists())

    @unittest.skipUnless(os.name == "nt", "GetDriveTypeW existe somente no Windows")
    def test_rejects_inconclusive_windows_drive_type(self) -> None:
        database = Path(self.temporary_directory.name) / "unknown-drive.db"
        with patch(
            "alertad.persistence.ctypes.windll.kernel32.GetDriveTypeW",
            return_value=0,
        ):
            with self.assertRaisesRegex(ValueError, "confirmar.*armazenamento local"):
                EventStore(database)

    def test_event_identity_distinguishes_domain_controllers(self) -> None:
        other_dc = replace(self.event, source_computer="DC02.EXAMPLE.LOCAL")

        self.assertNotEqual(self.event.event_key, other_dc.event_key)
        self.assertTrue(self.store.add_event(self.event, channels=("teams",)))
        self.assertTrue(self.store.add_event(other_dc, channels=("teams",)))
        self.assertEqual(self.store.event_count(), 2)

    def test_exports_event_with_missing_data_to_attention_report(self) -> None:
        self.store.add_event(self.event)
        report = Path(self.temporary_directory.name) / "attention.csv"

        total = export_attention_report(self.store, report)
        content = report.read_text(encoding="utf-8-sig")

        self.assertEqual(total, 1)
        self.assertIn("alert_id;event_id", content)
        self.assertIn("Nome do usuário não informado", content)

    def _create_legacy_database(self, database: Path) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection = sqlite3.connect(database)
        try:
            connection.executescript(
                """
                CREATE TABLE events (
                    event_key TEXT PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    event_record_id INTEGER NOT NULL,
                    source_computer TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    time_created_utc TEXT NOT NULL,
                    target_user_name TEXT NOT NULL,
                    member_sid TEXT NOT NULL,
                    attentions_json TEXT NOT NULL,
                    received_at_utc TEXT NOT NULL
                );
                CREATE TABLE deliveries (
                    event_key TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'sent', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (event_key, channel),
                    FOREIGN KEY (event_key) REFERENCES events(event_key)
                );
                """
            )
            connection.execute(
                """
                INSERT INTO events (
                    event_key, event_id, event_record_id, source_computer, channel,
                    time_created_utc, target_user_name, member_sid,
                    attentions_json, received_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)
                """,
                (
                    self.event.legacy_event_key,
                    self.event.event_id,
                    self.event.event_record_id,
                    self.event.source_computer,
                    self.event.channel,
                    self.event.time_created_utc.isoformat(),
                    self.event.target_user_name,
                    self.event.member_sid,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO deliveries (
                    event_key, channel, status, attempts, updated_at_utc
                ) VALUES (?, 'teams', 'pending', 0, ?)
                """,
                (self.event.legacy_event_key, now),
            )
            connection.commit()
        finally:
            connection.close()

    def _create_v2_database(self, database: Path) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            EventStore._migrate_to_v1(connection)
            EventStore._migrate_to_v2(connection)
            connection.execute("PRAGMA user_version = 2")
            connection.execute(
                """
                INSERT INTO events (
                    event_key, event_id, event_record_id, source_computer, channel,
                    time_created_utc, target_user_name, member_sid,
                    attentions_json, received_at_utc, action, group_scope,
                    alert_message, snapshot_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, 1)
                """,
                (
                    self.event.legacy_event_key,
                    self.event.event_id,
                    self.event.event_record_id,
                    self.event.source_computer,
                    self.event.channel,
                    self.event.time_created_utc.isoformat(),
                    self.event.target_user_name,
                    self.event.member_sid,
                    now,
                    self.event.action.value,
                    self.event.group_scope.value,
                    format_alert(self.event),
                ),
            )
            connection.execute(
                """
                INSERT INTO deliveries (
                    event_key, channel, status, attempts, updated_at_utc
                ) VALUES (?, 'teams', 'pending', 0, ?)
                """,
                (self.event.legacy_event_key, now),
            )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
