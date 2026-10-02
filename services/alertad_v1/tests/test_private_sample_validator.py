from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from alertad.persistence import EventStore
from .manual.validate_private_xml_samples import (
    _import_valid_samples,
    _validate_samples,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class PrivateSampleValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.samples = self.root / "samples"
        self.samples.mkdir()

        for event_id in (4728, 4729, 4732, 4756, 4757):
            content = (FIXTURES / f"event_{event_id}.xml").read_text(
                encoding="utf-8"
            )
            if event_id == 4732:
                content = content.replace(
                    ">Administrators<",
                    ">Synthetic Unmonitored Group<",
                )
            (self.samples / f"{event_id}.xml").write_text(
                content,
                encoding="utf-8",
            )
        (self.samples / "4733.xml").write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_synthetic_matrix_matches_private_homologation_without_sensitive_data(self):
        output = io.StringIO()
        with redirect_stdout(output):
            valid_samples, failures = _validate_samples(self.samples)

        self.assertEqual([], failures)
        self.assertEqual(
            {"4728.xml", "4729.xml", "4756.xml", "4757.xml"},
            set(valid_samples),
        )
        rendered = output.getvalue()
        self.assertNotIn("EXAMPLE.LOCAL", rendered)
        self.assertNotIn("operador.teste", rendered)
        self.assertNotIn("S-1-5-21-", rendered)

    def test_only_four_in_scope_samples_are_imported_and_deduplicated(self):
        database = self.root / "alertad.db"
        EventStore(database, database_mode="dry_run")
        with redirect_stdout(io.StringIO()):
            valid_samples, failures = _validate_samples(self.samples)
            _import_valid_samples(database, valid_samples)
            _import_valid_samples(database, valid_samples)

        self.assertEqual([], failures)
        status = EventStore(database, database_mode="dry_run").operational_status()
        self.assertEqual(4, status["events"])
        self.assertEqual(0, status["pending"])


if __name__ == "__main__":
    unittest.main()
