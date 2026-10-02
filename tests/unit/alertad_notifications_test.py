from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from services.alertad_notifications import (
    AlertADNotificationSettings,
    load_alertad_notifications,
)
from services.alertad_v1.src.alertad.parsing import parse_windows_event
from services.alertad_v1.src.alertad.persistence import EventStore
from services.alertad_v1.src.alertad.sentinel_read import (
    SentinelAlert,
)


class FakeReader:
    def __init__(self, alerts):
        self.alerts = alerts
        self.limits = []

    def list_recent(self, *, limit):
        self.limits.append(limit)
        return self.alerts[:limit]


def synthetic_alert(index=1, occurred_at="2026-10-02T12:00:00+00:00"):
    return SentinelAlert(
        notification_id=f"alertad:synthetic-{index}",
        alert_id=f"synthetic-{index}",
        severity="critical",
        title="Usuário adicionado a grupo crítico",
        message="Mensagem sanitizada",
        action="add",
        group_name="Domain Admins",
        member_label="EXAMPLE\\usuario",
        actor_label="EXAMPLE\\operador",
        source_computer="DC01.EXAMPLE.LOCAL",
        event_id=4728,
        event_record_id=index,
        occurred_at_utc=occurred_at,
        received_at_utc=occurred_at,
    )


class AlertADNotificationTests(unittest.TestCase):
    def test_unauthorized_user_does_not_consult_source_or_parse_config(self):
        factory = Mock(side_effect=AssertionError("reader must not be called"))

        result = load_alertad_notifications(
            {"alertad": {"enabled": True, "sqlite_path": None}},
            authorized=False,
            reader_factory=factory,
            environ={},
        )

        self.assertEqual([], result)
        factory.assert_not_called()

    def test_authorized_user_receives_only_sanitized_bell_fields_and_limit(self):
        reader = FakeReader((synthetic_alert(), synthetic_alert(2)))
        factory = Mock(return_value=reader)
        config = {
            "alertad": {
                "enabled": True,
                "sqlite_path": str(Path.cwd() / "synthetic.db"),
                "recent_limit": 1,
            }
        }

        result = load_alertad_notifications(
            config,
            authorized=True,
            reader_factory=factory,
            environ={},
        )

        self.assertEqual([1], reader.limits)
        self.assertEqual(1, len(result))
        self.assertEqual("alertad", result[0]["type"])
        self.assertEqual("Domain Admins", result[0]["device"])
        self.assertEqual(
            "\n".join(
                (
                    "Grupo: Domain Admins",
                    "Usuário: EXAMPLE\\usuario",
                    "Executor: EXAMPLE\\operador",
                    "Origem: DC01.EXAMPLE.LOCAL",
                    "Data/hora: 02/10/2026 09:00:00 (Brasília)",
                )
            ),
            result[0]["message"],
        )
        self.assertNotIn("Ação:", result[0]["message"])
        self.assertNotIn("Evento:", result[0]["message"])
        self.assertNotIn("Registro:", result[0]["message"])
        serialized = json.dumps(result, ensure_ascii=False).casefold()
        for forbidden in (
            "raw_xml",
            "bookmark",
            "client_secret",
            "directory_error_code",
            "event_record_id",
            "source_computer",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_notification_css_preserves_message_line_breaks(self):
        stylesheet = (
            Path(__file__).parents[2]
            / "static"
            / "notifications"
            / "notifications.css"
        ).read_text(encoding="utf-8")

        self.assertIn(".notification-item-copy p", stylesheet)
        self.assertIn("white-space: pre-line", stylesheet)

    def test_member_distinguished_name_is_reduced_to_common_name(self):
        alert = replace(
            synthetic_alert(),
            member_label=(
                "CN=Sobrenome\\, Nome,OU=Usuários,OU=Empresa,"
                "DC=example,DC=local"
            ),
        )
        reader = FakeReader((alert,))

        result = load_alertad_notifications(
            {
                "alertad": {
                    "enabled": True,
                    "sqlite_path": str(Path.cwd() / "synthetic.db"),
                }
            },
            authorized=True,
            reader_factory=Mock(return_value=reader),
            environ={},
        )

        self.assertIn("Usuário: Sobrenome, Nome", result[0]["message"])
        self.assertNotIn("CN=", result[0]["message"])
        self.assertNotIn("OU=", result[0]["message"])
        self.assertNotIn("DC=", result[0]["message"])

    def test_missing_database_and_incompatible_schema_do_not_break_existing_bell(self):
        baseline = [{"id": "existing"}]
        logger = Mock()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.db"
            incompatible = Path(directory) / "incompatible.db"
            connection = sqlite3.connect(incompatible)
            try:
                connection.execute("PRAGMA user_version = 99")
                connection.commit()
            finally:
                connection.close()

            for database in (missing, incompatible):
                with self.subTest(database=database.name):
                    alerts = load_alertad_notifications(
                        {
                            "alertad": {
                                "enabled": True,
                                "sqlite_path": str(database),
                            }
                        },
                        authorized=True,
                        logger=logger,
                        environ={},
                    )
                    self.assertEqual(baseline, baseline + alerts)

        self.assertFalse(missing.exists())
        self.assertEqual(2, logger.warning.call_count)
        self.assertNotIn(str(missing), str(logger.warning.call_args_list))
        self.assertNotIn(str(incompatible), str(logger.warning.call_args_list))

    def test_environment_overrides_are_external_and_validated(self):
        settings = AlertADNotificationSettings.from_external_config(
            {"alertad": {"enabled": False}},
            environ={
                "SENTINEL_ALERTAD_ENABLED": "true",
                "SENTINEL_ALERTAD_SQLITE_PATH": str(Path.cwd() / "external.db"),
                "SENTINEL_ALERTAD_RECENT_LIMIT": "7",
            },
        )

        self.assertTrue(settings.enabled)
        self.assertEqual(7, settings.recent_limit)

    def test_real_reader_preserves_sqlite_bytes_and_timestamp(self):
        fixture = (
            Path(__file__).parents[2]
            / "services"
            / "alertad_v1"
            / "tests"
            / "fixtures"
            / "event_4732.xml"
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "alertad.db"
            store = EventStore(database, database_mode="dry_run")
            store.add_event(parse_windows_event(fixture.read_text(encoding="utf-8")))
            before = database.read_bytes()
            before_mtime = database.stat().st_mtime_ns

            result = load_alertad_notifications(
                {
                    "alertad": {
                        "enabled": True,
                        "sqlite_path": str(database),
                        "recent_limit": 10,
                    }
                },
                authorized=True,
                environ={},
            )

            self.assertEqual(1, len(result))
            self.assertEqual(before, database.read_bytes())
            self.assertEqual(before_mtime, database.stat().st_mtime_ns)

    def test_real_reader_order_and_limit_remain_deterministic(self):
        fixture = (
            Path(__file__).parents[2]
            / "services"
            / "alertad_v1"
            / "tests"
            / "fixtures"
            / "event_4732.xml"
        )
        event = parse_windows_event(fixture.read_text(encoding="utf-8"))
        newer = replace(
            event,
            event_record_id=event.event_record_id + 1,
            time_created_utc=event.time_created_utc + timedelta(seconds=1),
            time_created_raw=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "alertad.db"
            store = EventStore(database, database_mode="dry_run")
            store.add_event(event)
            store.add_event(newer)

            result = load_alertad_notifications(
                {
                    "alertad": {
                        "enabled": True,
                        "sqlite_path": str(database),
                        "recent_limit": 1,
                    }
                },
                authorized=True,
                environ={},
            )

        self.assertEqual(1, len(result))
        self.assertEqual(f"alertad:{newer.event_key}", result[0]["id"])

    def test_read_path_never_starts_alertad_worker(self):
        reader = FakeReader((synthetic_alert(),))
        with patch(
            "services.alertad_v1.src.alertad.worker.AlertWorker.run"
        ) as worker_run:
            result = load_alertad_notifications(
                {
                    "alertad": {
                        "enabled": True,
                        "sqlite_path": str(Path.cwd() / "synthetic.db"),
                    }
                },
                authorized=True,
                reader_factory=Mock(return_value=reader),
                environ={},
            )

        self.assertEqual(1, len(result))
        worker_run.assert_not_called()
if __name__ == "__main__":
    unittest.main()
