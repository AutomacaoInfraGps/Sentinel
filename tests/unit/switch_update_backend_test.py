from datetime import datetime, timezone
import io
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager, UserMixin

from services.switch_update_v01.main import UpdateAssessment, WebIdentity
from services.switch_update_v01.scheduler import SchedulerSettings, SwitchUpdateScheduler
from services.switch_update_v01.sentinel_backend import install_switch_update_backend


class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id


class XorProtector:
    def protect(self, secret):
        return bytes(value ^ 0xA7 for value in secret.encode())

    def unprotect(self, protected):
        return bytes(value ^ 0xA7 for value in protected).decode()


class SentinelBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)

        def assessor(url, firmware, **kwargs):
            identity = WebIdentity(
                url=url,
                title="Instant On 1930 Switch",
                sys_name="LAB",
                sys_descr="InstantOn_1930_3.3.0.0 (9)",
                model="1930",
            )
            return UpdateAssessment(
                url=url,
                host="192.0.2.10",
                firmware=Path(firmware),
                expected_model=kwargs.get("expected_model") or "1930",
                expected_version=kwargs.get("expected_version") or "3.4.0.6",
                current_model="1930",
                current_version="3.3.0.9",
                decision="update",
                identity=identity,
            )

        self.scheduler = SwitchUpdateScheduler(
            SchedulerSettings(
                database_path=root / "schedules.sqlite3",
                firmware_dir=root / "firmware",
            ),
            protector=XorProtector(),
            assessor=assessor,
            credential_validator=lambda assessment, username, password: None,
            executor=lambda *args, **kwargs: None,
            now=lambda: datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )

        app = Flask(__name__)
        app.secret_key = "test-only-secret"
        app.config.update(TESTING=True)
        login = LoginManager(app)

        @login.user_loader
        def load_user(user_id):
            return User(user_id)

        def resolver(host):
            if host != "SW-LAB":
                return None
            return {
                "host": host,
                "ip": "192.0.2.10",
                "modelo": "HPE Networking Instant On 1930",
                "local": "Laboratorio",
                "status": "online",
                "ultima_verificacao_formatada": "18/09/2026 as 09:00:00",
            }

        self.trigger_calls = 0

        def trigger_worker():
            self.trigger_calls += 1
            return True

        install_switch_update_backend(
            app,
            self.scheduler,
            resolve_switch=resolver,
            is_authorized=lambda user_id: user_id == "allowed.user",
            start_scheduler=False,
            trigger_worker=trigger_worker,
            worker_health=lambda: {
                "task_name": "SentinelSwitchUpdateWorker",
                "available": True,
            },
        )
        self.app = app
        self.client = app.test_client()

    def login(self, user_id="allowed.user"):
        with self.client.session_transaction() as session:
            session["_user_id"] = user_id
            session["_fresh"] = True

    def csrf(self):
        response = self.client.get("/api/switches/firmware/csrf")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def test_requires_login_and_operator_authorization(self):
        self.assertEqual(self.client.get("/api/switches/firmware/csrf").status_code, 401)
        self.login("unauthorized.user")
        self.assertEqual(self.client.get("/api/switches/firmware/csrf").status_code, 403)

    def test_health_reports_backend_version(self):
        self.login()
        response = self.client.get("/api/switches/firmware/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["version"], "0.1.0")
        self.assertFalse(payload["scheduler_running"])
        self.assertEqual(payload["execution_mode"], "windows_task")
        self.assertTrue(payload["worker"]["available"])

    def test_backend_registration_is_idempotent(self):
        original = self.app.extensions["switch_update_backend_v01"]["blueprint"]
        repeated = install_switch_update_backend(
            self.app,
            self.scheduler,
            resolve_switch=lambda host: None,
            is_authorized=lambda user_id: False,
            start_scheduler=False,
        )
        self.assertIs(repeated, original)

    def test_mutation_requires_csrf(self):
        self.login()
        response = self.client.post(
            "/api/switches/SW-LAB/firmware/preflight",
            data={"firmware": (io.BytesIO(b"firmware"), "InstantOn_1930_3.4.0.6.swi")},
        )
        self.assertEqual(response.status_code, 403)

    def test_preflight_and_scheduled_job_contract(self):
        self.login()
        token = self.csrf()
        preflight = self.client.post(
            "/api/switches/SW-LAB/firmware/preflight",
            headers={"X-CSRF-Token": token},
            data={"firmware": (io.BytesIO(b"firmware"), "InstantOn_1930_3.4.0.6.swi")},
        )
        self.assertEqual(preflight.status_code, 200)
        result = preflight.get_json()
        self.assertEqual(result["draft"]["decision"], "update")
        self.assertEqual(result["switch"]["ip"], "192.0.2.10")

        created_response = self.client.post(
            "/api/switches/SW-LAB/firmware/jobs",
            headers={"X-CSRF-Token": token},
            json={
                "draft_token": result["draft"]["draft_token"],
                "username": "admin",
                "password": "segredo",
                "confirmed_decision": "update",
                "scheduled_at": "2026-09-18T10:00:00",
            },
        )
        self.assertEqual(created_response.status_code, 202)
        created_payload = created_response.get_json()
        job = created_payload["job"]
        self.assertIsNone(created_payload["worker_triggered"])
        self.assertEqual(self.trigger_calls, 0)
        self.assertEqual(job["status"], "scheduled")
        self.assertNotIn("credential_blob", job)
        self.assertNotIn("firmware_path", job)

        status = self.client.get(f"/api/switches/firmware/jobs/{job['id']}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["job"]["owner"], "allowed.user")

    def test_unknown_switch_is_rejected_before_network_access(self):
        self.login()
        response = self.client.post(
            "/api/switches/UNKNOWN/firmware/preflight",
            headers={"X-CSRF-Token": self.csrf()},
            data={"firmware": (io.BytesIO(b"firmware"), "InstantOn_1930_3.4.0.6.swi")},
        )
        self.assertEqual(response.status_code, 404)

    def test_immediate_job_is_due_and_can_complete(self):
        self.login()
        token = self.csrf()
        preflight = self.client.post(
            "/api/switches/SW-LAB/firmware/preflight",
            headers={"X-CSRF-Token": token},
            data={"firmware": (io.BytesIO(b"firmware"), "InstantOn_1930_3.4.0.6.swi")},
        ).get_json()
        created_response = self.client.post(
            "/api/switches/SW-LAB/firmware/jobs",
            headers={"X-CSRF-Token": token},
            json={
                "draft_token": preflight["draft"]["draft_token"],
                "username": "admin",
                "password": "segredo",
                "confirmed_decision": "update",
            },
        ).get_json()
        created = created_response["job"]
        self.assertTrue(created_response["worker_triggered"])
        self.assertEqual(self.trigger_calls, 1)
        self.assertEqual(self.scheduler.run_due_once(), created["id"])
        status = self.client.get(f"/api/switches/firmware/jobs/{created['id']}").get_json()
        self.assertEqual(status["job"]["status"], "completed")
        self.assertEqual(status["job"]["result_code"], "SWU000")
        self.assertIn("SwitchUpdateLog_SWU000_", status["job"]["log_relative_path"])

    def test_recheck_confirms_late_return_after_ping_timeout(self):
        self.login()
        token = self.csrf()
        preflight = self.client.post(
            "/api/switches/SW-LAB/firmware/preflight",
            headers={"X-CSRF-Token": token},
            data={"firmware": (io.BytesIO(b"firmware"), "InstantOn_1930_3.4.0.6.swi")},
        ).get_json()
        created = self.client.post(
            "/api/switches/SW-LAB/firmware/jobs",
            headers={"X-CSRF-Token": token},
            json={
                "draft_token": preflight["draft"]["draft_token"],
                "username": "admin",
                "password": "segredo",
                "confirmed_decision": "update",
            },
        ).get_json()["job"]
        with closing(sqlite3.connect(self.scheduler.settings.database_path)) as connection:
            connection.execute(
                "UPDATE scheduled_updates SET status = 'needs_review', stage = 'needs_review' "
                "WHERE id = ?",
                (created["id"],),
            )
            connection.commit()

        returned = WebIdentity(
            url="https://192.0.2.10/login.htm",
            title="Instant On 1930 Switch",
            sys_name="LAB",
            sys_descr="InstantOn_1930_3.4.0.0 (6)",
            model="1930",
        )
        with patch(
            "services.switch_update_v01.scheduler.fetch_web_identity",
            return_value=returned,
        ):
            response = self.client.post(
                f"/api/switches/firmware/jobs/{created['id']}/recheck",
                headers={"X-CSRF-Token": token},
            )
        self.assertEqual(response.status_code, 200)
        job = response.get_json()["job"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["stage"], "completed_after_review")
        self.assertEqual(job["result_code"], "SWU411")
        self.assertEqual(
            job["message"],
            "Update realizado porém o retorno foi após o tempo esperado, "
            "consulte a integridade do switch",
        )


if __name__ == "__main__":
    unittest.main()
