import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from notification_center import (
    build_notifications,
    decorate_with_read_state,
    dismiss_notifications,
    mark_notifications_seen,
    snapshot_is_fresh,
)


class NotificationCenterTests(unittest.TestCase):
    def test_stale_snapshot_is_not_accepted(self):
        now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(snapshot_is_fresh((now - timedelta(hours=2)).isoformat(), now=now))
        self.assertFalse(snapshot_is_fresh((now - timedelta(days=5)).isoformat(), now=now))

    def test_builds_infrastructure_and_orphan_vpn_alerts(self):
        records = {
            "links": [{
                "nome": "WAN1",
                "regional": "REG_TESTE",
                "status": "offline",
                "changed_at": "2026-09-16T10:00:00",
            }],
            "vpns": [{
                "tunel": "T999_SEM_REGIONAL",
                "regional": "SEM_REGIONAL",
                "status": "down",
                "changed_at": "2026-09-16T10:01:00",
            }],
            "aps": [{"nome": "AP-OK", "status": "online"}],
            "switches": [{
                "nome": "SW-MANUTENCAO",
                "status": "offline",
                "em_manutencao": True,
            }],
            "firewalls": [{
                "nome": "FW-TESTE",
                "regional": "REG_TESTE",
                "status": "warning",
                "changed_at": "2026-09-16T10:02:00",
            }],
            "admins": [{
                "nome": "FW-ADMIN",
                "regional": "REG_TESTE",
                "status": "alerta",
                "changed_at": "2026-09-16T10:03:00",
            }],
            "servidores": [{
                "nome": "Servidor São Paulo",
                "regional": "REG_SÃO_PAULO",
                "status": "offline",
                "changed_at": "2026-09-16T10:04:00",
            }],
        }

        notifications = build_notifications(records, {"T999_SEM_REGIONAL"})

        self.assertEqual(len(notifications), 6)
        self.assertEqual(sum(1 for item in notifications if item["type"] == "vpn_orphan"), 1)
        self.assertEqual(sum(1 for item in notifications if item["type"] == "vpns"), 1)
        self.assertEqual(sum(1 for item in notifications if item["type"] == "links"), 1)
        self.assertTrue(any(item["type"] == "admins" for item in notifications))
        self.assertTrue(any(item["title"] == "Licença de firewall requer atenção" for item in notifications))
        self.assertTrue(any(item["url"] == "/links?q=WAN1" for item in notifications))
        self.assertTrue(any(item["url"] == "/vpn?q=T999_SEM_REGIONAL" for item in notifications))
        self.assertTrue(any(
            item["url"] == "/regional/REG_S%C3%83O_PAULO?q=Servidor+S%C3%A3o+Paulo#regional-servidores-section"
            for item in notifications
        ))
        self.assertFalse(any(item["device"] == "AP-OK" for item in notifications))
        self.assertFalse(any(item["device"] == "SW-MANUTENCAO" for item in notifications))

    def test_read_state_is_kept_per_user(self):
        notifications = build_notifications({
            "links": [{
                "nome": "WAN1",
                "regional": "REG_TESTE",
                "status": "offline",
                "changed_at": "2026-09-16T10:00:00",
            }]
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "notification_state.json"
            first_user, first_unread = decorate_with_read_state("user.one", notifications, path)
            self.assertEqual(first_unread, 1)
            self.assertFalse(first_user[0]["read"])

            mark_notifications_seen("user.one", [notifications[0]["id"]], path)
            first_user, first_unread = decorate_with_read_state("user.one", notifications, path)
            second_user, second_unread = decorate_with_read_state("user.two", notifications, path)

            self.assertEqual(first_unread, 0)
            self.assertTrue(first_user[0]["read"])
            self.assertEqual(second_unread, 1)
            self.assertFalse(second_user[0]["read"])

            dismiss_notifications("user.one", [notifications[0]["id"]], path)
            first_user, first_unread = decorate_with_read_state("user.one", notifications, path)
            second_user, second_unread = decorate_with_read_state("user.two", notifications, path)
            self.assertEqual(first_user, [])
            self.assertEqual(first_unread, 0)
            self.assertEqual(second_unread, 1)

            new_occurrence = build_notifications({
                "links": [{
                    "nome": "WAN1",
                    "regional": "REG_TESTE",
                    "status": "offline",
                    "changed_at": "2026-09-16T11:00:00",
                }]
            })
            first_user, first_unread = decorate_with_read_state("user.one", new_occurrence, path)
            self.assertEqual(len(first_user), 1)
            self.assertEqual(first_unread, 1)

    def test_unresolved_orphan_vpn_cannot_be_permanently_dismissed(self):
        notifications = build_notifications({
            "vpns": [{
                "tunel": "T999_NOVAUNIDADE_01",
                "regional": "SEM_REGIONAL",
                "status": "online",
                "changed_at": "2026-09-16T10:00:00",
            }]
        }, {"T999_NOVAUNIDADE_01"})
        orphan = notifications[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "notification_state.json"
            mark_notifications_seen("user.one", [orphan["id"]], path)
            dismiss_notifications("user.one", [orphan["id"]], path)
            visible, unread = decorate_with_read_state("user.one", notifications, path)

        self.assertEqual(1, len(visible))
        self.assertTrue(visible[0]["read"])
        self.assertEqual(0, unread)


if __name__ == "__main__":
    unittest.main()
