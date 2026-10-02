from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from alertad.config import DirectorySettings, RetentionPolicy, Settings  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_load_example_settings(self) -> None:
        settings = Settings.load(PROJECT_ROOT / "config" / "settings.example.json")

        self.assertIn("Domain Admins", settings.fixed_groups)
        self.assertEqual(settings.group_name_prefix, "GGS_Suporte")
        self.assertEqual(settings.event_log_channel, "ForwardedEvents")
        self.assertEqual(settings.event_batch_size, 500)
        self.assertEqual(settings.event_overlap_size, 10)
        self.assertIsNone(settings.poll_interval_seconds)
        self.assertEqual(settings.max_delivery_attempts, 6)
        self.assertFalse(settings.directory.enabled)
        self.assertEqual(settings.directory.backend, "POWERSHELL_ADWS")
        self.assertIsNone(settings.directory.server)
        self.assertEqual(settings.delivery_channels, ("teams", "email"))
        self.assertFalse(settings.retention.purge_enabled)
        self.assertIsNone(settings.retention.events_and_deliveries_days)

    def test_reject_empty_prefix(self) -> None:
        with self.assertRaisesRegex(ValueError, "group_name_prefix"):
            Settings(group_name_prefix=" ")

    def test_reject_batch_larger_than_scope_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "entre 1 e 500"):
            Settings(event_batch_size=501)

    def test_reject_overlap_larger_than_safe_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_overlap_size.*0 e 500"):
            Settings(event_overlap_size=501)

    def test_reject_unknown_delivery_channel(self) -> None:
        with self.assertRaisesRegex(ValueError, "teams.*email"):
            Settings(delivery_channels=("teams", "canal-inexistente"))

    def test_reject_blank_fixed_group(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixed_groups"):
            Settings(fixed_groups=frozenset({"Domain Admins", " "}))

    def test_worker_requires_poll_interval(self) -> None:
        settings = Settings()

        with self.assertRaisesRegex(ValueError, "poll_interval_seconds"):
            settings.validate_for_worker()

    def test_worker_accepts_positive_poll_interval(self) -> None:
        settings = Settings(
            poll_interval_seconds=10,
            directory=DirectorySettings(
                enabled=True,
            ),
        )

        settings.validate_for_worker()
        self.assertEqual(settings.poll_interval_seconds, 10.0)

    def test_productive_worker_requires_enabled_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "directory.enabled"):
            Settings(poll_interval_seconds=10).validate_for_worker()

    def test_directory_rejects_url_and_invalid_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "nome do servidor"):
            DirectorySettings(server="https://directory.example.invalid")
        with self.assertRaisesRegex(ValueError, "maior que zero"):
            DirectorySettings(query_timeout_seconds=0)

    def test_load_rejects_obsolete_ldaps_settings(self) -> None:
        with self.assertRaisesRegex(ValueError, "LDAPS obsoleta"):
            Settings.load(PROJECT_ROOT / "tests" / "fixtures" / "settings_ldaps.json")

    def test_reject_non_object_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "objeto JSON"):
            Settings.load(PROJECT_ROOT / "tests" / "fixtures" / "settings_list.json")

    def test_retention_periods_are_configurable_but_purge_is_disabled(self) -> None:
        policy = RetentionPolicy(
            events_and_deliveries_days=90,
            occurrences_days=180,
        )

        self.assertEqual(policy.events_and_deliveries_days, 90)
        self.assertFalse(policy.purge_enabled)
        with self.assertRaisesRegex(ValueError, "Expurgo exige"):
            RetentionPolicy(events_and_deliveries_days=90, purge_enabled=True)

        with self.assertRaisesRegex(ValueError, "janela real de replay"):
            RetentionPolicy(
                events_and_deliveries_days=90,
                occurrences_days=180,
                deduplication_guard_days=30,
                purge_enabled=True,
            )

    def test_retry_policy_rejects_any_total_other_than_six(self) -> None:
        for total in (1, 5, 7):
            with self.subTest(total=total):
                with self.assertRaisesRegex(ValueError, "deve ser 6"):
                    Settings(max_delivery_attempts=total)


if __name__ == "__main__":
    unittest.main()

