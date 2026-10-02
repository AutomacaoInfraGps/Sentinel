from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from alertad.contracts import CheckpointAdvance, EventCheckpoint
from alertad.event_source import (
    EventLogPage,
    EventLogRecord,
    InvalidBookmarkError,
    InvalidCheckpointError,
    PyWin32EventLogBackend,
    WindowsEventLogSource,
)
from alertad.parsing import parse_windows_event
from alertad.persistence import EventStore


FIXTURES = Path(__file__).parent / "fixtures"
BASE_XML = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
SUPPORTED_IDS = {4728, 4729, 4732, 4733, 4756, 4757}


def event_xml(
    ordinal: int,
    *,
    event_id: int = 4732,
    event_record_id: int | None = None,
    computer: str = "DC01.EXAMPLE.LOCAL",
) -> str:
    return (
        BASE_XML.replace("<EventID>4732</EventID>", f"<EventID>{event_id}</EventID>")
        .replace(
            "<EventRecordID>100001</EventRecordID>",
            f"<EventRecordID>{event_record_id or ordinal}</EventRecordID>",
        )
        .replace(
            "<Computer>DC01.EXAMPLE.LOCAL</Computer>",
            f"<Computer>{computer}</Computer>",
        )
    )


def bookmark(ordinal: int) -> str:
    return (
        '<BookmarkList><Bookmark Channel="ForwardedEvents" '
        f'RecordId="{ordinal}" IsCurrent="true" /></BookmarkList>'
    )


class FakeLocalEventLogBackend:
    def __init__(self, records: list[EventLogRecord], identity: str = "log-a") -> None:
        self.records = records
        self.identity = identity
        self.invalid_bookmarks: set[str] = set()
        self.calls: list[dict[str, object]] = []

    @staticmethod
    def _event_id(record: EventLogRecord) -> int:
        root = ElementTree.fromstring(record.xml)
        node = root.find("./{*}System/{*}EventID")
        if node is None or node.text is None:
            return -1
        return int(node.text)

    def _eligible(self) -> list[EventLogRecord]:
        return [record for record in self.records if self._event_id(record) in SUPPORTED_IDS]

    def log_identity(self, channel: str) -> str:
        self.calls.append({"operation": "identity", "channel": channel})
        return self.identity

    def latest_bookmark(self, channel: str, xpath_query: str) -> str | None:
        self.calls.append(
            {
                "operation": "latest",
                "channel": channel,
                "query": xpath_query,
            }
        )
        eligible = self._eligible()
        return eligible[-1].bookmark if eligible else None

    def read_events(
        self,
        channel: str,
        xpath_query: str,
        *,
        after_bookmark: str | None,
        overlap: int,
        limit: int,
    ) -> EventLogPage:
        self.calls.append(
            {
                "operation": "read",
                "channel": channel,
                "query": xpath_query,
                "after": after_bookmark,
                "overlap": overlap,
                "limit": limit,
            }
        )
        eligible = self._eligible()
        if after_bookmark is None:
            start = 0
        else:
            if after_bookmark in self.invalid_bookmarks:
                raise InvalidBookmarkError("fake_invalid_bookmark")
            positions = [
                index
                for index, record in enumerate(eligible)
                if record.bookmark == after_bookmark
            ]
            if not positions:
                raise InvalidBookmarkError("fake_missing_bookmark")
            position = positions[0]
            start = max(0, position - (overlap - 1)) if overlap else position + 1
        page = eligible[start : start + limit + 1]
        return EventLogPage(tuple(page[:limit]), len(page) > limit)


class FakeHandle:
    def __init__(self, kind: str, position: int | None = None) -> None:
        self.kind = kind
        self.position = position
        self.closed = False

    def Close(self) -> None:
        self.closed = True


class FakePyWin32Api:
    EvtOpenChannelPath = 1
    EvtLogCreationTime = 2
    EvtQueryChannelPath = 4
    EvtQueryForwardDirection = 8
    EvtQueryReverseDirection = 16
    EvtSeekRelativeToBookmark = 32
    EvtSeekStrict = 64
    EvtRenderEventXml = 128
    EvtRenderBookmark = 256

    def __init__(self) -> None:
        self.sessions: list[object | None] = []
        self.queries: list[str] = []
        self.handles: list[FakeHandle] = []
        self.xml = [event_xml(1), event_xml(2)]

    def _handle(self, kind: str, position: int | None = None) -> FakeHandle:
        handle = FakeHandle(kind, position)
        self.handles.append(handle)
        return handle

    def EvtOpenLog(self, channel, flags, *, Session):
        self.sessions.append(Session)
        return self._handle("log")

    @staticmethod
    def EvtGetLogInfo(handle, property_id):
        return ("2026-01-01T00:00:00+00:00", 0)

    def EvtQuery(self, channel, flags, query, *, Session):
        self.sessions.append(Session)
        self.queries.append(query)
        direction = "reverse" if flags & self.EvtQueryReverseDirection else "forward"
        return self._handle(direction, -1 if direction == "forward" else len(self.xml))

    def EvtCreateBookmark(self, value):
        position = None
        if value:
            position = int(str(value).split('RecordId="', 1)[1].split('"', 1)[0]) - 1
        return self._handle("bookmark", position)

    @staticmethod
    def EvtSeek(result, position, flags, bookmark_handle, timeout):
        result.position = int(bookmark_handle.position) + position

    def EvtNext(self, result, count, timeout, flags):
        if result.kind == "reverse":
            positions = range(len(self.xml) - 1, -1, -1)
        else:
            positions = range(int(result.position) + 1, len(self.xml))
        selected_positions = list(positions)[:count]
        found = [self._handle("event", position) for position in selected_positions]
        if found:
            result.position = int(found[-1].position)
        return found

    def EvtRender(self, handle, flags):
        if flags == self.EvtRenderEventXml:
            return self.xml[int(handle.position)]
        return bookmark(int(handle.position) + 1)

    @staticmethod
    def EvtUpdateBookmark(bookmark_handle, event_handle):
        bookmark_handle.position = event_handle.position


def records(count: int, *, first: int = 1) -> list[EventLogRecord]:
    return [
        EventLogRecord(event_xml(index), bookmark(index))
        for index in range(first, first + count)
    ]


class WindowsEventLogSourceTests(unittest.TestCase):
    def source(
        self,
        backend: FakeLocalEventLogBackend,
        *,
        overlap: int = 2,
    ) -> WindowsEventLogSource:
        generations = iter(range(1, 100))
        return WindowsEventLogSource(
            backend=backend,
            overlap_size=overlap,
            generation_factory=lambda: f"test-generation-{next(generations)}",
        )

    def test_first_read_filters_ids_and_preserves_xml(self) -> None:
        expected = records(2)
        backend = FakeLocalEventLogBackend(
            [
                expected[0],
                EventLogRecord(event_xml(90, event_id=9999), bookmark(90)),
                expected[1],
            ]
        )
        source = self.source(backend)

        batch = source.read_new_events(None, limit=500)

        self.assertEqual([item.xml for item in batch.events], [item.xml for item in expected])
        self.assertEqual([item.checkpoint.sequence for item in batch.events], [1, 2])
        self.assertFalse(batch.has_more)
        read_call = next(call for call in backend.calls if call["operation"] == "read")
        self.assertEqual(read_call["channel"], "ForwardedEvents")
        for event_id in SUPPORTED_IDS:
            self.assertIn(f"EventID={event_id}", str(read_call["query"]))

    def test_continues_after_checkpoint_without_restarting_overlap_mid_scan(self) -> None:
        backend = FakeLocalEventLogBackend(records(5))
        source = self.source(backend)

        first = source.read_new_events(None, limit=2)
        second = source.read_new_events(first.next_checkpoint, limit=2)

        self.assertTrue(first.has_more)
        self.assertEqual(
            [parse_windows_event(item.xml).event_record_id for item in second.events],
            [3, 4],
        )
        self.assertEqual([item.checkpoint.sequence for item in second.events], [3, 4])
        second_read = [call for call in backend.calls if call["operation"] == "read"][1]
        self.assertEqual(second_read["overlap"], 0)

    def test_reads_multiple_successive_batches(self) -> None:
        backend = FakeLocalEventLogBackend(records(7))
        source = self.source(backend)
        checkpoint = None
        observed: list[int] = []

        while True:
            batch = source.read_new_events(checkpoint, limit=3)
            observed.extend(
                parse_windows_event(item.xml).event_record_id for item in batch.events
            )
            checkpoint = batch.next_checkpoint
            if not batch.has_more:
                break

        self.assertEqual(observed, list(range(1, 8)))
        self.assertEqual(checkpoint.sequence, 7)

    def test_batch_can_contain_exactly_500_events(self) -> None:
        backend = FakeLocalEventLogBackend(records(500))

        batch = self.source(backend).read_new_events(None, limit=500)

        self.assertEqual(len(batch.events), 500)
        self.assertFalse(batch.has_more)
        self.assertEqual(batch.next_checkpoint.sequence, 500)

    def test_overlap_replays_recent_events_before_new_event(self) -> None:
        backend = FakeLocalEventLogBackend(records(4))
        source = self.source(backend, overlap=2)
        first = source.read_new_events(None, limit=10)
        backend.records.append(EventLogRecord(event_xml(5), bookmark(5)))

        second = source.read_new_events(first.next_checkpoint, limit=10)

        self.assertEqual(
            [parse_windows_event(item.xml).event_record_id for item in second.events],
            [3, 4, 5],
        )
        self.assertEqual([item.checkpoint.sequence for item in second.events], [5, 6, 7])

    def test_overlap_can_continue_across_several_small_batches(self) -> None:
        backend = FakeLocalEventLogBackend(records(5))
        source = self.source(backend, overlap=4)
        initial = source.read_new_events(None, limit=10)
        backend.records.extend(records(2, first=6))

        checkpoint = initial.next_checkpoint
        observed: list[int] = []
        while True:
            batch = source.read_new_events(checkpoint, limit=2)
            observed.extend(
                parse_windows_event(item.xml).event_record_id for item in batch.events
            )
            checkpoint = batch.next_checkpoint
            if not batch.has_more:
                break

        self.assertEqual(observed, [2, 3, 4, 5, 6, 7])
        self.assertEqual(checkpoint.sequence, 11)

    def test_overlap_duplicates_are_deduplicated_by_sqlite(self) -> None:
        backend = FakeLocalEventLogBackend(records(3))
        source = self.source(backend, overlap=2)
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            checkpoint: EventCheckpoint | None = None

            first = source.read_new_events(checkpoint, limit=10)
            checkpoint = self._persist_batch(store, first, checkpoint)
            backend.records.append(EventLogRecord(event_xml(4), bookmark(4)))
            second = source.read_new_events(checkpoint, limit=10)
            checkpoint = self._persist_batch(store, second, checkpoint)

            self.assertEqual(store.event_count(), 4)
            self.assertEqual(len(store.pending_deliveries()), 4)
            self.assertEqual(store.get_checkpoint(source.source), checkpoint)

    def test_new_source_instance_resumes_from_persisted_checkpoint(self) -> None:
        backend = FakeLocalEventLogBackend(records(5))
        first_source = self.source(backend)
        first = first_source.read_new_events(None, limit=2)

        restarted_source = self.source(backend)
        resumed = restarted_source.read_new_events(first.next_checkpoint, limit=10)

        self.assertEqual(
            [parse_windows_event(item.xml).event_record_id for item in resumed.events],
            [3, 4, 5],
        )

    def test_invalid_native_bookmark_starts_explicit_new_generation(self) -> None:
        backend = FakeLocalEventLogBackend(records(3))
        source = self.source(backend)
        first = source.read_new_events(None, limit=10)
        backend.invalid_bookmarks.add(bookmark(3))
        backend.records = records(2, first=10)

        reset = source.read_new_events(first.next_checkpoint, limit=10)

        self.assertNotEqual(reset.next_checkpoint.generation, first.next_checkpoint.generation)
        self.assertEqual(reset.events[0].checkpoint.sequence, 1)
        self.assertEqual(
            [parse_windows_event(item.xml).event_record_id for item in reset.events],
            [10, 11],
        )

    def test_log_rotation_changes_generation_and_restarts_at_oldest_available(self) -> None:
        backend = FakeLocalEventLogBackend(records(3), identity="log-a")
        source = self.source(backend)
        first = source.read_new_events(None, limit=10)
        backend.identity = "log-b"
        backend.records = records(2, first=20)

        rotated = source.read_new_events(first.next_checkpoint, limit=10)

        self.assertNotEqual(rotated.next_checkpoint.generation, first.next_checkpoint.generation)
        self.assertEqual(rotated.next_checkpoint.sequence, 2)
        self.assertEqual(
            [parse_windows_event(item.xml).event_record_id for item in rotated.events],
            [20, 21],
        )

    def test_empty_rotated_log_returns_generation_checkpoint_at_sequence_zero(self) -> None:
        backend = FakeLocalEventLogBackend(records(1), identity="log-a")
        source = self.source(backend)
        first = source.read_new_events(None, limit=10)
        backend.identity = "log-b"
        backend.records = []

        rotated = source.read_new_events(first.next_checkpoint, limit=10)

        self.assertEqual(rotated.events, ())
        self.assertIsNotNone(rotated.next_checkpoint)
        self.assertEqual(rotated.next_checkpoint.sequence, 0)
        self.assertNotEqual(rotated.next_checkpoint.generation, first.next_checkpoint.generation)

    def test_empty_rotation_checkpoint_can_be_persisted_by_compare_and_swap(self) -> None:
        backend = FakeLocalEventLogBackend(records(1), identity="log-a")
        source = self.source(backend)
        first = source.read_new_events(None, limit=10)
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "rotation.db")
            persisted = self._persist_batch(store, first, None)
            backend.identity = "log-b"
            backend.records = []

            rotated = source.read_new_events(persisted, limit=10)
            store.advance_checkpoint(
                CheckpointAdvance(
                    persisted,
                    rotated.next_checkpoint,
                    allow_generation_change=True,
                )
            )

            self.assertEqual(store.get_checkpoint(source.source), rotated.next_checkpoint)

    def test_failure_in_middle_resumes_at_first_unconfirmed_item(self) -> None:
        backend = FakeLocalEventLogBackend(records(5))
        source = self.source(backend)
        batch = source.read_new_events(None, limit=10)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "crash.db"
            store = EventStore(database)
            checkpoint = self._persist_batch(
                store,
                type(batch)(batch.events[:2], batch.events[1].checkpoint, True),
                None,
            )

            # O terceiro item falha antes da persistência: seu checkpoint não avança.
            restarted_store = EventStore(database)
            persisted = restarted_store.get_checkpoint(source.source)
            self.assertEqual(persisted, checkpoint)
            resumed = self.source(backend).read_new_events(persisted, limit=10)

            self.assertEqual(
                [parse_windows_event(item.xml).event_record_id for item in resumed.events],
                [3, 4, 5],
            )

    def test_same_record_id_from_different_domain_controllers_is_preserved(self) -> None:
        backend = FakeLocalEventLogBackend(
            [
                EventLogRecord(
                    event_xml(1, event_record_id=77, computer="DC01.EXAMPLE.LOCAL"),
                    bookmark(1),
                ),
                EventLogRecord(
                    event_xml(2, event_record_id=77, computer="DC02.EXAMPLE.LOCAL"),
                    bookmark(2),
                ),
            ]
        )

        batch = self.source(backend).read_new_events(None, limit=10)
        parsed = [parse_windows_event(item.xml) for item in batch.events]

        self.assertEqual([event.event_record_id for event in parsed], [77, 77])
        self.assertNotEqual(parsed[0].source_computer, parsed[1].source_computer)
        self.assertNotEqual(parsed[0].event_key, parsed[1].event_key)

    def test_no_eligible_event_returns_initial_checkpoint(self) -> None:
        backend = FakeLocalEventLogBackend(
            [EventLogRecord(event_xml(1, event_id=9999), bookmark(1))]
        )

        batch = self.source(backend).read_new_events(None, limit=10)

        self.assertEqual(batch.events, ())
        self.assertIsNotNone(batch.next_checkpoint)
        self.assertEqual(batch.next_checkpoint.sequence, 0)

    def test_forward_order_is_deterministic_and_does_not_use_origin_record_id(self) -> None:
        ordered = [
            EventLogRecord(event_xml(1, event_record_id=900), bookmark(1)),
            EventLogRecord(event_xml(2, event_record_id=100), bookmark(2)),
            EventLogRecord(event_xml(3, event_record_id=500), bookmark(3)),
        ]
        backend = FakeLocalEventLogBackend(ordered)

        first = self.source(backend).read_new_events(None, limit=10)
        second = self.source(backend).read_new_events(None, limit=10)

        first_ids = [parse_windows_event(item.xml).event_record_id for item in first.events]
        second_ids = [parse_windows_event(item.xml).event_record_id for item in second.events]
        self.assertEqual(first_ids, [900, 100, 500])
        self.assertEqual(second_ids, first_ids)

    def test_checkpoint_at_end_skips_existing_history_before_first_new_event(self) -> None:
        backend = FakeLocalEventLogBackend(records(3))
        source = self.source(backend, overlap=2)
        checkpoint = source.checkpoint_at_end()

        empty = source.read_new_events(checkpoint, limit=10)
        backend.records.append(EventLogRecord(event_xml(4), bookmark(4)))
        new = source.read_new_events(checkpoint, limit=10)

        self.assertEqual(empty.events, ())
        self.assertEqual(
            [parse_windows_event(item.xml).event_record_id for item in new.events],
            [4],
        )

    def test_initial_cut_remains_lower_bound_across_overlap_cycles_and_restart(self) -> None:
        backend = FakeLocalEventLogBackend(records(10))
        source = self.source(backend, overlap=3)
        checkpoint = source.checkpoint_at_end()
        backend.records.append(EventLogRecord(event_xml(11), bookmark(11)))

        first = source.read_new_events(checkpoint, limit=2)
        checkpoint = first.next_checkpoint
        second = source.read_new_events(checkpoint, limit=2)
        checkpoint = second.next_checkpoint
        backend.records.append(EventLogRecord(event_xml(12), bookmark(12)))
        restarted = self.source(backend, overlap=3)
        third = restarted.read_new_events(checkpoint, limit=2)

        observed = [
            parse_windows_event(item.xml).event_record_id
            for batch in (first, second, third)
            for item in batch.events
        ]
        self.assertTrue(observed)
        self.assertNotIn(9, observed)
        self.assertNotIn(10, observed)
        self.assertIn(11, observed)
        self.assertIn(12, observed)

    def test_initial_cut_survives_new_backlog_split_into_small_batches(self) -> None:
        backend = FakeLocalEventLogBackend(records(5))
        source = self.source(backend, overlap=4)
        checkpoint = source.checkpoint_at_end()
        backend.records.extend(records(5, first=6))
        observed = []

        while True:
            batch = source.read_new_events(checkpoint, limit=2)
            observed.extend(
                parse_windows_event(item.xml).event_record_id for item in batch.events
            )
            checkpoint = batch.next_checkpoint
            if not batch.has_more:
                break

        self.assertEqual(observed, [6, 7, 8, 9, 10])

    def test_rejects_malformed_checkpoint_without_silently_resetting(self) -> None:
        backend = FakeLocalEventLogBackend(records(1))
        source = self.source(backend)
        malformed = EventCheckpoint(source.source, "not-json", "generation", 10)

        with self.assertRaises(InvalidCheckpointError):
            source.read_new_events(malformed, limit=10)

    def test_pywin32_backend_uses_only_local_session_and_closes_handles(self) -> None:
        api = FakePyWin32Api()
        backend = PyWin32EventLogBackend(api=api)

        identity = backend.log_identity("ForwardedEvents")
        latest = backend.latest_bookmark("ForwardedEvents", "*[System[EventID=4732]]")
        page = backend.read_events(
            "ForwardedEvents",
            "*[System[EventID=4732]]",
            after_bookmark=None,
            overlap=0,
            limit=2,
        )

        self.assertTrue(identity)
        self.assertEqual(latest, bookmark(2))
        self.assertEqual([record.xml for record in page.records], api.xml)
        self.assertTrue(all(session is None for session in api.sessions))
        self.assertTrue(all(handle.closed for handle in api.handles))

    @staticmethod
    def _persist_batch(
        store: EventStore,
        batch,
        expected: EventCheckpoint | None,
    ) -> EventCheckpoint | None:
        current = expected
        for collected in batch.events:
            allow_generation_change = (
                current is not None
                and current.generation != collected.checkpoint.generation
            )
            advance = CheckpointAdvance(
                current,
                collected.checkpoint,
                allow_generation_change=allow_generation_change,
            )
            store.add_event(
                parse_windows_event(collected.xml),
                channels=("teams",),
                checkpoint_advance=advance,
            )
            current = collected.checkpoint
        return current


if __name__ == "__main__":
    unittest.main()
