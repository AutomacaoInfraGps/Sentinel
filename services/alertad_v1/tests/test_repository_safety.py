from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ALERTAD_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = ALERTAD_ROOT.parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRIVATE_FIXTURES = FIXTURES / "XMLEXAMPLE_test"


class RepositorySafetyTests(unittest.TestCase):
    def test_private_xml_samples_are_ignored_by_alertad_and_sentinel(self) -> None:
        package_ignore = (ALERTAD_ROOT / ".gitignore").read_text(encoding="utf-8")
        repository_ignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("tests/fixtures/XMLEXAMPLE_test/", package_ignore)
        self.assertIn(
            "/services/alertad_v1/tests/fixtures/XMLEXAMPLE_test/",
            repository_ignore,
        )

    def test_private_xml_samples_are_not_tracked(self) -> None:
        if not (REPOSITORY_ROOT / ".git").is_dir():
            self.skipTest("checkout sem metadados Git")
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "--",
                PRIVATE_FIXTURES.relative_to(REPOSITORY_ROOT).as_posix(),
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", result.stdout.strip())

    def test_versionable_event_fixtures_are_explicitly_synthetic(self) -> None:
        fixtures = sorted(FIXTURES.glob("event_*.xml"))
        self.assertEqual(6, len(fixtures))
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                content = fixture.read_text(encoding="utf-8")
                self.assertIn("EXAMPLE.LOCAL", content)
                self.assertIn(
                    "S-1-5-21-1000000000-2000000000-3000000000-",
                    content,
                )

    def test_no_secret_bearing_artifacts_exist_in_versionable_tests(self) -> None:
        forbidden_names = {
            ".env",
            "settings.json",
            "graph.env",
            "token_cache.bin",
        }
        forbidden_suffixes = {
            ".db",
            ".sqlite",
            ".sqlite3",
            ".p12",
            ".pem",
            ".pfx",
            ".key",
        }
        unsafe = []
        for path in Path(__file__).resolve().parent.rglob("*"):
            if not path.is_file() or PRIVATE_FIXTURES in path.parents:
                continue
            if path.name.casefold() in forbidden_names:
                unsafe.append(path.name)
            elif path.suffix.casefold() in forbidden_suffixes:
                unsafe.append(path.name)
        self.assertEqual([], unsafe)


if __name__ == "__main__":
    unittest.main()
