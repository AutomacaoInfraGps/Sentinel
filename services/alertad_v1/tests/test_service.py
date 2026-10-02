from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alertad.persistence import EventStore
from alertad.service import EventProcessor, ProcessStatus


FIXTURES = Path(__file__).parent / "fixtures"


class ServiceTests(unittest.TestCase):
    def test_processes_monitored_event_then_detects_duplicate(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = EventStore(Path(temporary_directory) / "alertad.db")
            processor = EventProcessor(store=store)

            first = processor.process_xml(xml)
            second = processor.process_xml(xml)

        self.assertEqual(first.status, ProcessStatus.READY)
        self.assertIsNotNone(first.message)
        self.assertEqual(second.status, ProcessStatus.DUPLICATE)
        self.assertIsNone(second.message)

    def test_marks_unmonitored_group_out_of_scope(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8").replace(
            "<Data Name=\"TargetUserName\">Administrators</Data>",
            "<Data Name=\"TargetUserName\">Grupo Comum</Data>",
        )
        result = EventProcessor().process_xml(xml)

        self.assertEqual(result.status, ProcessStatus.OUT_OF_SCOPE)
        self.assertIsNone(result.message)

    def test_formatting_failure_does_not_leave_partial_persistence(self) -> None:
        xml = (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "alertad.db"
            store = EventStore(database)
            processor = EventProcessor(store=store)

            with patch(
                "alertad.service.format_alert",
                side_effect=RuntimeError("falha simulada"),
            ):
                with self.assertRaises(RuntimeError):
                    processor.process_xml(xml)

            reopened_store = EventStore(database)
            self.assertEqual(reopened_store.event_count(), 0)
            self.assertEqual(reopened_store.pending_deliveries(), [])


if __name__ == "__main__":
    unittest.main()

