from __future__ import annotations

import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

from alertad.contracts import (
    CollectedEvent,
    DirectoryObject,
    DirectoryResolution,
    DirectoryResolutionStatus,
    EventBatch,
    EventCheckpoint,
)
from alertad.persistence import EventStore
from alertad.rules import GroupMatcher
from alertad.worker import AlertWorker


FIXTURES = Path(__file__).parent / "fixtures"
BASE_XML = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")


class FiveHundredEventSource:
    source = "forwardedevents"

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.events = [
            BASE_XML.replace(
                "<EventRecordID>100001</EventRecordID>",
                f"<EventRecordID>{100001 + index}</EventRecordID>",
            )
            for index in range(500)
        ]

    @staticmethod
    def checkpoint(sequence: int) -> EventCheckpoint:
        return EventCheckpoint(
            "ForwardedEvents",
            f"bookmark-{sequence}",
            "generation-performance",
            sequence,
        )

    def read_new_events(self, checkpoint, *, limit: int) -> EventBatch:
        start = checkpoint.sequence if checkpoint is not None else 0
        self.calls.append((start, limit))
        selected = self.events[start : start + limit]
        items = tuple(
            CollectedEvent(xml, self.checkpoint(start + offset + 1))
            for offset, xml in enumerate(selected)
        )
        next_checkpoint = items[-1].checkpoint if items else (
            checkpoint or self.checkpoint(0)
        )
        return EventBatch(items, next_checkpoint, start + len(selected) < 500)


class StaticResolver:
    def resolve_sid(self, sid: str) -> DirectoryResolution:
        return DirectoryResolution(
            DirectoryResolutionStatus.RESOLVED,
            DirectoryObject(sid, "usuario.teste", "user", "EXAMPLE"),
        )


class PerformanceTests(unittest.TestCase):
    def test_full_batch_of_500_stays_within_local_safety_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = FiveHundredEventSource()
            store = EventStore(
                Path(temporary_directory) / "performance.db",
                database_mode="dry_run",
            )
            worker = AlertWorker(
                source=source,
                store=store,
                resolver=StaticResolver(),
                matcher=GroupMatcher(),
                channels=("teams", "email"),
                batch_size=500,
                poll_interval_seconds=1,
                dry_run=True,
            )

            tracemalloc.start()
            started = time.perf_counter()
            processed = worker.ingest_available()
            elapsed = time.perf_counter() - started
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            print(
                f"PERF 500 eventos: {elapsed:.3f}s; "
                f"pico Python={peak_bytes / (1024 * 1024):.2f} MiB"
            )

            self.assertEqual(processed, 500)
            self.assertEqual(source.calls, [(0, 500)])
            self.assertEqual(store.event_count(), 500)
            self.assertLess(elapsed, 60, f"lote levou {elapsed:.2f}s")
            self.assertLess(peak_bytes, 128 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
