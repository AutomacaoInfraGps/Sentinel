from __future__ import annotations

import unittest
from datetime import datetime, timezone

from alertad.contracts import (
    CheckpointAdvance,
    CollectedEvent,
    DirectoryObject,
    DirectoryResolution,
    DirectoryResolutionStatus,
    EventBatch,
    EventCheckpoint,
    OccurrenceCategory,
    OperationalOccurrence,
)


class FakeEventSource:
    def __init__(self, batch: EventBatch) -> None:
        self.batch = batch
        self.calls: list[tuple[EventCheckpoint | None, int]] = []

    def read_new_events(
        self,
        checkpoint: EventCheckpoint | None,
        *,
        limit: int,
    ) -> EventBatch:
        self.calls.append((checkpoint, limit))
        return self.batch


class CollectionContractTests(unittest.TestCase):
    def test_batch_carries_per_item_and_next_checkpoints(self) -> None:
        first = EventCheckpoint("ForwardedEvents", "bookmark-1")
        second = EventCheckpoint("ForwardedEvents", "bookmark-2")

        batch = EventBatch(
            events=(
                CollectedEvent("<Event />", first),
                CollectedEvent("<Event />", second),
            ),
            next_checkpoint=second,
            has_more=True,
        )

        self.assertEqual(batch.events[0].checkpoint, first)
        self.assertEqual(batch.next_checkpoint, second)
        self.assertTrue(batch.has_more)

    def test_event_source_can_be_replaced_by_fake(self) -> None:
        checkpoint = EventCheckpoint("ForwardedEvents", "bookmark")
        expected = EventBatch((), checkpoint)
        source = FakeEventSource(expected)

        result = source.read_new_events(None, limit=500)

        self.assertIs(result, expected)
        self.assertEqual(source.calls, [(None, 500)])

    def test_reject_batch_above_500_events(self) -> None:
        checkpoint = EventCheckpoint("ForwardedEvents", "bookmark")
        events = tuple(CollectedEvent("<Event />", checkpoint) for _ in range(501))

        with self.assertRaisesRegex(ValueError, "500"):
            EventBatch(events, checkpoint)

    def test_reject_events_without_next_checkpoint(self) -> None:
        checkpoint = EventCheckpoint("ForwardedEvents", "bookmark")

        with self.assertRaisesRegex(ValueError, "next_checkpoint"):
            EventBatch((CollectedEvent("<Event />", checkpoint),), None)

    def test_checkpoint_source_has_canonical_representation(self) -> None:
        checkpoint = EventCheckpoint("  ForwardedEvents  ", "bookmark", "generation", 1)

        self.assertEqual(checkpoint.source, "forwardedevents")

    def test_checkpoint_advance_must_be_contiguous(self) -> None:
        current = EventCheckpoint("ForwardedEvents", "bookmark-10", "generation", 10)
        skipped = EventCheckpoint("ForwardedEvents", "bookmark-12", "generation", 12)

        with self.assertRaisesRegex(ValueError, "exatamente uma sequência"):
            CheckpointAdvance(current, skipped)

    def test_checkpoint_generation_change_requires_explicit_confirmation(self) -> None:
        current = EventCheckpoint("ForwardedEvents", "old", "generation-a", 10)
        reset = EventCheckpoint("ForwardedEvents", "new", "generation-b", 0)

        with self.assertRaisesRegex(ValueError, "confirmação explícita"):
            CheckpointAdvance(current, reset)

        advance = CheckpointAdvance(current, reset, allow_generation_change=True)
        self.assertEqual(advance.next, reset)


class DirectoryContractTests(unittest.TestCase):
    def test_resolved_result_requires_directory_object(self) -> None:
        with self.assertRaisesRegex(ValueError, "directory_object"):
            DirectoryResolution(DirectoryResolutionStatus.RESOLVED)

    def test_resolved_result_carries_user_details(self) -> None:
        directory_object = DirectoryObject(
            sid="S-1-5-21-1",
            account_name="usuario.teste",
            object_type="user",
            domain_name="EXAMPLE",
            display_name="Usuário Teste",
        )

        result = DirectoryResolution(
            DirectoryResolutionStatus.RESOLVED,
            directory_object,
        )

        self.assertEqual(result.directory_object, directory_object)


class OccurrenceContractTests(unittest.TestCase):
    def test_occurrence_requires_timezone_aware_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "fuso horário"):
            OperationalOccurrence(
                category=OccurrenceCategory.INVALID_EVENT,
                component="parser",
                reason_code="invalid_xml",
                fingerprint="fixture",
                occurred_at_utc=datetime(2026, 9, 30),
            )

    def test_valid_occurrence_contains_no_raw_payload_field(self) -> None:
        occurrence = OperationalOccurrence(
            category=OccurrenceCategory.INVALID_EVENT,
            component="parser",
            reason_code="invalid_xml",
            fingerprint="fixture",
            occurred_at_utc=datetime.now(timezone.utc),
        )

        self.assertFalse(hasattr(occurrence, "raw_xml"))


if __name__ == "__main__":
    unittest.main()
