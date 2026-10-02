from __future__ import annotations

import tempfile
import threading
import unittest
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from alertad.contracts import (
    CollectedEvent,
    DeliveryResult,
    DirectoryObject,
    DirectoryResolution,
    DirectoryResolutionStatus,
    EventBatch,
    EventCheckpoint,
    OccurrenceCategory,
    OperationalOccurrence,
)
from alertad.parsing import parse_windows_event
from alertad.persistence import DeliveryConflictError, EventStore
from alertad.rules import GroupMatcher
from alertad.event_source import EventLogReadError
from alertad.worker import (
    AlertWorker,
    RetryPolicy,
    WorkerAlreadyRunningError,
    WorkerInstanceLock,
)


FIXTURES = Path(__file__).parent / "fixtures"
BASE_XML = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def xml_event(ordinal: int, *, group: str = "Administrators") -> str:
    return (
        BASE_XML.replace(
            "<EventRecordID>100001</EventRecordID>",
            f"<EventRecordID>{100000 + ordinal}</EventRecordID>",
        )
        .replace(
            '<Data Name="TargetUserName">Administrators</Data>',
            f'<Data Name="TargetUserName">{group}</Data>',
        )
    )


class FakeSource:
    source = "forwardedevents"

    def __init__(self, xml_items: list[str]) -> None:
        self.xml_items = xml_items
        self.calls: list[tuple[int, int]] = []

    @staticmethod
    def checkpoint(sequence: int) -> EventCheckpoint:
        return EventCheckpoint(
            "ForwardedEvents",
            f"bookmark-{sequence}",
            "generation-a",
            sequence,
        )

    def read_new_events(self, checkpoint, *, limit: int) -> EventBatch:
        start = checkpoint.sequence if checkpoint is not None else 0
        self.calls.append((start, limit))
        selected = self.xml_items[start : start + limit]
        events = tuple(
            CollectedEvent(xml, self.checkpoint(start + index + 1))
            for index, xml in enumerate(selected)
        )
        has_more = start + len(selected) < len(self.xml_items)
        next_checkpoint = events[-1].checkpoint if events else (
            checkpoint or self.checkpoint(0)
        )
        return EventBatch(events, next_checkpoint, has_more)


class FakeResolver:
    def __init__(self, result: DirectoryResolution | None = None) -> None:
        self.result = result or DirectoryResolution(
            DirectoryResolutionStatus.RESOLVED,
            DirectoryObject(
                "S-1-5-21-1000000000-2000000000-3000000000-1101",
                "usuario.teste",
                "user",
                "EXAMPLE",
            ),
        )
        self.calls: list[str] = []

    def resolve_sid(self, sid: str) -> DirectoryResolution:
        self.calls.append(sid)
        return self.result


class FakeNotifier:
    def __init__(self, channel: str, results: list[DeliveryResult]) -> None:
        self.channel = channel
        self.results = results
        self.calls = 0

    def send(self, event, message: str) -> DeliveryResult:
        self.calls += 1
        return self.results.pop(0)


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "alertad.db"
        self.clock_value = NOW

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def worker(
        self,
        source: FakeSource,
        store: EventStore,
        *,
        resolver: FakeResolver | None = None,
        notifiers=None,
        batch_size: int = 500,
        poll_interval_seconds: float = 1,
        dry_run: bool = False,
        output=None,
    ) -> AlertWorker:
        return AlertWorker(
            source=source,
            store=store,
            resolver=resolver or FakeResolver(),
            matcher=GroupMatcher(),
            channels=("teams", "email"),
            notifiers=notifiers,
            batch_size=batch_size,
            poll_interval_seconds=poll_interval_seconds,
            dry_run=dry_run,
            clock=lambda: self.clock_value,
            on_dry_run_message=output,
        )

    def test_pipeline_filters_before_directory_and_quarantines_invalid_event(self) -> None:
        invalid = xml_event(3).replace("<Data Name=\"MemberSid\">", "<Data Name=\"MissingSid\">")
        source = FakeSource(
            [
                xml_event(1),
                xml_event(2, group="Grupo Comum"),
                invalid,
                xml_event(4, group="GGS_Suporte_Regional"),
            ]
        )
        store = EventStore(self.database)
        resolver = FakeResolver()

        processed = self.worker(source, store, resolver=resolver, batch_size=2).ingest_available()

        self.assertEqual(processed, 4)
        self.assertEqual(store.event_count(), 2)
        self.assertEqual(store.occurrence_count(), 1)
        self.assertEqual(store.get_checkpoint(source.source).sequence, 4)
        self.assertEqual(len(resolver.calls), 2)

    def test_member_name_from_event_skips_directory_and_is_preserved(self) -> None:
        source = FakeSource(
            [(FIXTURES / "event_4733.xml").read_text(encoding="utf-8")]
        )
        store = EventStore(self.database, database_mode="dry_run")
        resolver = FakeResolver(
            DirectoryResolution(
                DirectoryResolutionStatus.TEMPORARY_FAILURE,
                error_code="synthetic",
            )
        )
        output: list[str] = []

        self.worker(
            source,
            store,
            resolver=resolver,
            dry_run=True,
            output=output.append,
        ).run_once()

        self.assertEqual(resolver.calls, [])
        self.assertEqual(store.event_count(), 1)
        self.assertEqual(len(output), 1)
        self.assertIn(
            "Usuário: CN=Usuario Teste,OU=Usuarios,DC=example,DC=local",
            output[0],
        )
        self.assertNotIn("exibindo o SID", output[0])

    def test_failure_during_persistence_does_not_advance_failed_item(self) -> None:
        source = FakeSource([xml_event(1), xml_event(2)])
        store = EventStore(self.database)
        worker = self.worker(source, store, batch_size=1)
        original = store.add_event
        calls = [0]

        def fail_second(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("simulated persistence failure")
            return original(*args, **kwargs)

        store.add_event = fail_second  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            worker.ingest_available()

        reopened = EventStore(self.database)
        self.assertEqual(reopened.event_count(), 1)
        self.assertEqual(reopened.get_checkpoint(source.source).sequence, 1)

        resumed = self.worker(source, reopened, batch_size=1)
        self.assertEqual(resumed.ingest_available(), 1)
        self.assertEqual(reopened.event_count(), 2)
        self.assertEqual(reopened.get_checkpoint(source.source).sequence, 2)

    def test_dry_run_persists_without_delivery_and_database_mode_isolated(self) -> None:
        source = FakeSource([xml_event(1)])
        output: list[str] = []
        store = EventStore(self.database, database_mode="dry_run")

        worker = self.worker(source, store, dry_run=True, output=output.append)
        worker.run_once()

        self.assertEqual(store.event_count(), 1)
        self.assertEqual(store.pending_deliveries(), [])
        self.assertEqual(len(output), 1)
        with self.assertRaisesRegex(RuntimeError, "Modo do banco incompatível"):
            EventStore(self.database, database_mode="production")

    def test_lock_rejects_second_instance_and_can_be_reacquired(self) -> None:
        first = WorkerInstanceLock(self.database)
        second = WorkerInstanceLock(self.database)
        first.acquire()
        try:
            with self.assertRaises(WorkerAlreadyRunningError):
                second.acquire()
        finally:
            first.release()

        second.acquire()
        second.release()

    def test_lock_rejects_hard_link_alias_to_same_database(self) -> None:
        EventStore(self.database)
        alias = Path(self.temporary_directory.name) / "database-alias.db"
        os.link(self.database, alias)

        with self.assertRaisesRegex(ValueError, "hard links"):
            WorkerInstanceLock(alias).acquire()

    @unittest.skipUnless(os.name == "nt", "Case-insensitive path is a Windows invariant")
    def test_lock_normalizes_path_case_on_windows(self) -> None:
        EventStore(self.database)
        first = WorkerInstanceLock(self.database)
        differently_cased = WorkerInstanceLock(str(self.database).upper())

        first.acquire()
        try:
            with self.assertRaises(WorkerAlreadyRunningError):
                differently_cased.acquire()
        finally:
            first.release()

    def test_lock_normalizes_relative_absolute_and_symlink_paths(self) -> None:
        EventStore(self.database)
        original_directory = Path.cwd()
        try:
            os.chdir(self.database.parent)
            relative = WorkerInstanceLock(self.database.name)
            absolute = WorkerInstanceLock(self.database)
            relative.acquire()
            with self.assertRaises(WorkerAlreadyRunningError):
                absolute.acquire()
            relative.release()
        finally:
            os.chdir(original_directory)

        symlink = self.database.parent / "database-symlink.db"
        try:
            symlink.symlink_to(self.database)
        except OSError:
            return
        first = WorkerInstanceLock(self.database)
        second = WorkerInstanceLock(symlink)
        first.acquire()
        try:
            with self.assertRaises(WorkerAlreadyRunningError):
                second.acquire()
        finally:
            first.release()

    def test_os_releases_worker_lock_after_abrupt_process_exit(self) -> None:
        project_root = Path(__file__).parent.parent
        script = (
            "import os; "
            "from alertad.worker import WorkerInstanceLock; "
            f"lock = WorkerInstanceLock({str(self.database)!r}); "
            "lock.acquire(); os._exit(23)"
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(project_root / "src")

        result = subprocess.run(
            [sys.executable, "-c", script],
            # Evita que o lançador alertad.py na raiz sombreie o pacote src/alertad.
            cwd=self.temporary_directory.name,
            env=environment,
            check=False,
            timeout=10,
        )

        self.assertEqual(result.returncode, 23)
        recovered = WorkerInstanceLock(self.database)
        recovered.acquire()
        recovered.release()

    def test_backlog_above_500_is_consumed_in_successive_bounded_batches(self) -> None:
        source = FakeSource(
            [xml_event(number, group="Grupo Comum") for number in range(1, 502)]
        )
        store = EventStore(self.database)

        processed = self.worker(source, store, batch_size=500).ingest_available()

        self.assertEqual(processed, 501)
        self.assertEqual(source.calls, [(0, 500), (500, 500)])
        self.assertEqual(store.get_checkpoint(source.source).sequence, 501)
        self.assertEqual(store.event_count(), 0)

    def test_graceful_stop_before_cycle_does_not_read_or_send(self) -> None:
        source = FakeSource([xml_event(1)])
        store = EventStore(self.database)
        stop_event = threading.Event()
        stop_event.set()

        self.worker(source, store).run(stop_event)

        self.assertEqual(source.calls, [])
        self.assertEqual(store.event_count(), 0)

    def test_slow_notification_does_not_block_the_next_collection_cycle(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockingNotifier:
            channel = "teams"

            def send(self, event, message: str) -> DeliveryResult:
                del event, message
                started.set()
                release.wait(2)
                return DeliveryResult(True)

        source = FakeSource([xml_event(1)])
        store = EventStore(self.database)
        worker = self.worker(
            source,
            store,
            notifiers={"teams": BlockingNotifier()},
            poll_interval_seconds=0.02,
        )
        stop_event = threading.Event()
        thread = threading.Thread(target=worker.run, args=(stop_event,))
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            source.xml_items.append(xml_event(2))
            deadline = time.monotonic() + 2
            while store.event_count() < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(store.event_count(), 2)
        finally:
            release.set()
            stop_event.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_dry_run_output_failure_does_not_invalidate_committed_event(self) -> None:
        source = FakeSource([xml_event(1)])
        store = EventStore(self.database, database_mode="dry_run")

        def broken_output(message: str) -> None:
            del message
            raise OSError("synthetic console failure")

        processed = self.worker(
            source,
            store,
            dry_run=True,
            output=broken_output,
        ).ingest_available()

        self.assertEqual(processed, 1)
        self.assertEqual(store.event_count(), 1)
        self.assertEqual(store.get_checkpoint(source.source).sequence, 1)

    def test_retry_policy_exact_schedule_and_retry_after(self) -> None:
        policy = RetryPolicy()

        self.assertEqual(
            [policy.delay_after_failure(number) for number in range(1, 7)],
            [30, 30, 30, 300, 900, None],
        )
        self.assertEqual(
            policy.delay_after_failure(2, retry_after_seconds=120),
            120,
        )

    def test_channels_are_dispatched_independently(self) -> None:
        store = EventStore(self.database, max_delivery_attempts=6)
        source = FakeSource([xml_event(1)])
        teams = FakeNotifier(
            "teams",
            [DeliveryResult(False, True, "temporary", failure_kind="temporary")],
        )
        email = FakeNotifier("email", [DeliveryResult(True)])
        worker = self.worker(
            source,
            store,
            notifiers={"teams": teams, "email": email},
        )
        worker.ingest_available()

        worker.dispatch_due()

        pending = store.pending_deliveries(
            now=self.clock_value + timedelta(seconds=30)
        )
        self.assertEqual([(item.channel, item.attempts) for item in pending], [("teams", 1)])
        self.assertEqual(store.status_counts()["sent"], 1)
        self.assertEqual(teams.calls, 1)
        self.assertEqual(email.calls, 1)

    def test_six_attempts_follow_exact_intervals_and_survive_restart(self) -> None:
        store = EventStore(self.database, max_delivery_attempts=6)
        event = parse_windows_event(xml_event(1))
        store.add_event(event, channels=("teams",))
        notifier = FakeNotifier(
            "teams",
            [
                DeliveryResult(False, True, f"failure-{number}", failure_kind="temporary")
                for number in range(1, 7)
            ],
        )
        worker = self.worker(
            FakeSource([]),
            store,
            notifiers={"teams": notifier},
        )
        expected_delays = [30, 30, 30, 300, 900]
        for expected_delay in expected_delays:
            worker.dispatch_due()
            reopened = EventStore(self.database, max_delivery_attempts=6)
            delivery = reopened.pending_deliveries(
                now=self.clock_value + timedelta(seconds=expected_delay)
            )[0]
            self.assertEqual(
                delivery.next_attempt_at_utc,
                self.clock_value + timedelta(seconds=expected_delay),
            )
            self.clock_value += timedelta(seconds=expected_delay)

        worker.dispatch_due()

        self.assertEqual(store.status_counts()["failed"], 1)
        self.assertEqual(notifier.calls, 6)
        self.assertEqual(store.occurrence_count(), 1)

    def test_retry_after_uses_larger_delay(self) -> None:
        store = EventStore(self.database)
        store.add_event(parse_windows_event(xml_event(1)), channels=("teams",))
        notifier = FakeNotifier(
            "teams",
            [
                DeliveryResult(
                    False,
                    True,
                    "throttled",
                    retry_after_seconds=120,
                    failure_kind="temporary",
                )
            ],
        )
        worker = self.worker(FakeSource([]), store, notifiers={"teams": notifier})

        worker.dispatch_due()

        delivery = store.pending_deliveries(
            now=self.clock_value + timedelta(seconds=120)
        )[0]
        self.assertEqual(delivery.next_attempt_at_utc, self.clock_value + timedelta(seconds=120))

    def test_retry_delay_starts_when_slow_attempt_finishes(self) -> None:
        store = EventStore(self.database)
        store.add_event(parse_windows_event(xml_event(1)), channels=("teams",))

        class SlowFailure:
            channel = "teams"

            def send(inner_self, event, message: str) -> DeliveryResult:
                del inner_self, event, message
                self.clock_value += timedelta(seconds=60)
                return DeliveryResult(
                    False,
                    True,
                    "synthetic timeout",
                    failure_kind="temporary",
                )

        worker = self.worker(
            FakeSource([]),
            store,
            notifiers={"teams": SlowFailure()},
        )

        worker.dispatch_due()

        delivery = store.pending_deliveries(
            now=self.clock_value + timedelta(seconds=30)
        )[0]
        self.assertEqual(
            delivery.next_attempt_at_utc,
            NOW + timedelta(seconds=90),
        )

    def test_claim_cas_prevents_two_threads_from_sending_same_attempt(self) -> None:
        store = EventStore(self.database)
        store.add_event(parse_windows_event(xml_event(1)), channels=("teams",))
        delivery = store.pending_deliveries(now=self.clock_value)[0]

        def claim():
            return store.claim_delivery_attempt(
                delivery,
                started_at_utc=self.clock_value,
                uncertainty_retry_at_utc=self.clock_value + timedelta(seconds=30),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: claim(), range(2)))

        self.assertEqual(sum(result is not None for result in results), 1)

    def test_active_claim_does_not_expire_while_notifier_is_still_running(self) -> None:
        store = EventStore(self.database)
        store.add_event(parse_windows_event(xml_event(1)), channels=("teams",))
        entered = threading.Event()
        release = threading.Event()

        class BlockingNotifier:
            channel = "teams"
            calls = 0

            def send(inner_self, event, message: str) -> DeliveryResult:
                del event, message
                inner_self.calls += 1
                entered.set()
                release.wait(2)
                return DeliveryResult(True)

        notifier = BlockingNotifier()
        worker = self.worker(
            FakeSource([]),
            store,
            notifiers={"teams": notifier},
        )
        thread = threading.Thread(target=worker.dispatch_due)
        thread.start()
        self.assertTrue(entered.wait(1))
        self.clock_value += timedelta(seconds=31)

        worker.dispatch_due()
        release.set()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(notifier.calls, 1)
        self.assertEqual(store.status_counts()["sent"], 1)

    def test_attempt_completion_is_consumed_only_once(self) -> None:
        store = EventStore(self.database)
        event = parse_windows_event(xml_event(1))
        store.add_event(event, channels=("teams",))
        delivery = store.pending_deliveries(now=self.clock_value)[0]
        claimed = store.claim_delivery_attempt(
            delivery,
            started_at_utc=self.clock_value,
            uncertainty_retry_at_utc=self.clock_value + timedelta(seconds=30),
        )
        self.assertIsNotNone(claimed)
        store.complete_delivery_attempt(
            claimed.event_key,
            claimed.channel,
            attempt_number=claimed.attempts,
            success=True,
            claim_token=claimed.claim_token,
        )

        with self.assertRaises(DeliveryConflictError):
            store.complete_delivery_attempt(
                claimed.event_key,
                claimed.channel,
                attempt_number=claimed.attempts,
                success=True,
                claim_token=claimed.claim_token,
            )

        self.assertEqual(store.status_counts()["sent"], 1)

    def test_crash_after_external_acceptance_is_retried_as_uncertain(self) -> None:
        store = EventStore(self.database)
        store.add_event(parse_windows_event(xml_event(1)), channels=("teams",))
        delivery = store.pending_deliveries(now=self.clock_value)[0]
        claimed = store.claim_delivery_attempt(
            delivery,
            started_at_utc=self.clock_value,
            uncertainty_retry_at_utc=self.clock_value + timedelta(seconds=30),
        )
        self.assertIsNotNone(claimed)
        # Simula: Graph aceitou e o processo terminou antes de gravar sucesso.

        reopened = EventStore(self.database)
        reopened.recover_abandoned_claims()
        self.assertEqual(reopened.pending_deliveries(now=self.clock_value), [])
        uncertain = reopened.pending_deliveries(
            now=self.clock_value + timedelta(seconds=30)
        )[0]
        self.assertEqual(uncertain.attempts, 1)
        self.assertEqual(uncertain.failure_kind, "uncertain")

    def test_terminal_delivery_and_occurrence_roll_back_together(self) -> None:
        store = EventStore(self.database)
        source = FakeSource([xml_event(1)])
        notifier = FakeNotifier(
            "teams",
            [DeliveryResult(False, False, "permanent", failure_kind="permanent")],
        )
        worker = AlertWorker(
            source=source,
            store=store,
            resolver=FakeResolver(),
            matcher=GroupMatcher(),
            channels=("teams",),
            notifiers={"teams": notifier},
            clock=lambda: self.clock_value,
        )
        worker.ingest_available()

        with patch.object(
            store,
            "_insert_occurrence",
            side_effect=sqlite3.OperationalError("synthetic crash window"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                worker.dispatch_due()

        reopened = EventStore(self.database)
        self.assertEqual(reopened.status_counts()["failed"], 0)
        self.assertEqual(reopened.status_counts()["pending"], 1)
        self.assertEqual(reopened.occurrence_count(), 0)

    def test_process_crash_between_terminal_update_and_occurrence_rolls_back(self) -> None:
        store = EventStore(self.database)
        event = parse_windows_event(xml_event(1))
        store.add_event(event, channels=("teams",))
        project_root = Path(__file__).parent.parent
        script = "\n".join(
            (
                "import os",
                "from datetime import datetime, timedelta, timezone",
                "from alertad.contracts import OccurrenceCategory, OperationalOccurrence",
                "from alertad.persistence import EventStore",
                f"database = {str(self.database)!r}",
                f"event_key = {event.event_key!r}",
                f"now = datetime.fromisoformat({self.clock_value.isoformat()!r})",
                "store = EventStore(database)",
                "delivery = store.pending_deliveries(now=now)[0]",
                "claimed = store.claim_delivery_attempt(delivery, started_at_utc=now, uncertainty_retry_at_utc=now + timedelta(seconds=30))",
                "occurrence = OperationalOccurrence(OccurrenceCategory.PERMANENT_DELIVERY_ERROR, 'teams', 'synthetic_terminal', 'synthetic-terminal-fingerprint', now)",
                "store._insert_occurrence = lambda *args: os._exit(29)",
                "store.complete_delivery_attempt(event_key, 'teams', attempt_number=claimed.attempts, success=False, retryable=False, error='synthetic', failure_kind='permanent', claim_token=claimed.claim_token, terminal_occurrence=occurrence)",
            )
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(project_root / "src")

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=self.temporary_directory.name,
            env=environment,
            check=False,
            timeout=10,
        )

        self.assertEqual(result.returncode, 29)
        reopened = EventStore(self.database)
        self.assertEqual(reopened.status_counts()["failed"], 0)
        self.assertEqual(reopened.status_counts()["pending"], 1)
        self.assertEqual(reopened.occurrence_count(), 0)
        self.assertEqual(reopened.status_counts()["active_claims"], 1)
        self.assertEqual(reopened.recover_abandoned_claims(), 1)
        recovered = reopened.pending_deliveries(
            now=self.clock_value + timedelta(seconds=30)
        )[0]
        self.assertEqual(recovered.attempts, 1)
        self.assertEqual(recovered.failure_kind, "uncertain")

    def test_run_once_propagates_event_source_failure(self) -> None:
        class BrokenSource(FakeSource):
            def read_new_events(self, checkpoint, *, limit: int):
                del checkpoint, limit
                raise EventLogReadError("synthetic_access_denied")

        store = EventStore(self.database, database_mode="dry_run")
        worker = self.worker(BrokenSource([]), store, dry_run=True)

        with self.assertRaises(EventLogReadError):
            worker.run_once()

        self.assertEqual(worker.metrics.source_failures, 1)


if __name__ == "__main__":
    unittest.main()
