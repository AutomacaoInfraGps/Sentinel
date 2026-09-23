from datetime import datetime, timezone
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from services.switch_update_v01.main import UpdateAssessment, UpdateNeedsReview, WebIdentity
from services.switch_update_v01.scheduler import (
    DpapiCredentialProtector,
    LATE_SUCCESS_MESSAGE,
    ScheduleError,
    SchedulerSettings,
    SwitchUpdateScheduler,
)


class XorProtector:
    key = 0xA7

    def protect(self, secret: str) -> bytes:
        return bytes(value ^ self.key for value in secret.encode("utf-8"))

    def unprotect(self, protected: bytes) -> str:
        return bytes(value ^ self.key for value in protected).decode("utf-8")


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "InstantOn_1930_3.4.0.6.swi"
        self.source.write_bytes(b"firmware-test-content")
        self.clock = MutableClock(datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))
        self.executions = []
        self.validated_credentials = []
        self.decision = "update"

        def assessor(url, firmware, **kwargs):
            identity = WebIdentity(
                url=url,
                title="Instant On 1930 Switch",
                sys_name="LAB-SW",
                sys_descr="InstantOn_1930_3.3.0.0 (9)",
                model="1930",
            )
            return UpdateAssessment(
                url=url,
                host="192.0.2.10",
                firmware=Path(firmware).resolve(),
                expected_model=kwargs.get("expected_model") or "1930",
                expected_version=kwargs.get("expected_version") or "3.4.0.6",
                current_model="1930",
                current_version="3.3.0.9",
                decision=self.decision,
                identity=identity,
            )

        def credential_validator(assessment, username, password):
            self.validated_credentials.append((assessment.host, username, password))

        def executor(args, *, switch_password, reporter):
            self.executions.append((args, switch_password))
            reporter.emit("transfer", 50, "Transferindo firmware")
            reporter.emit("complete", 100, "Concluido")

        settings = SchedulerSettings(
            database_path=self.root / "runtime" / "schedules.sqlite3",
            firmware_dir=self.root / "runtime" / "firmware",
            poll_interval_seconds=0.01,
        )
        self.scheduler = SwitchUpdateScheduler(
            settings,
            protector=XorProtector(),
            assessor=assessor,
            credential_validator=credential_validator,
            executor=executor,
            now=self.clock,
        )

    def create(self, **overrides):
        values = {
            "owner": "operador.teste",
            "scheduled_at": "2026-09-18T09:01:00",
            "url": "https://192.0.2.10",
            "username": "admin",
            "password": "segredo-de-teste",
            "firmware": self.source,
            "confirmed_decision": "update",
            "expected_model": "1930",
            "expected_version": "3.4.0.6",
        }
        values.update(overrides)
        return self.scheduler.create_schedule(**values)

    def test_naive_datetime_is_interpreted_as_brasilia(self):
        value = self.scheduler.normalize_scheduled_at("2026-09-18T09:30:00")
        self.assertEqual(value.isoformat(), "2026-09-18T12:30:00+00:00")

    def test_schedule_encrypts_password_and_hides_internal_paths(self):
        created = self.create()
        self.assertEqual(created["status"], "scheduled")
        self.assertEqual(created["scheduled_at_brasilia"], "2026-09-18T09:01:00-03:00")
        self.assertNotIn("credential_blob", created)
        self.assertNotIn("firmware_path", created)

        with closing(sqlite3.connect(self.scheduler.settings.database_path)) as connection:
            blob, managed_path = connection.execute(
                "SELECT credential_blob, firmware_path FROM scheduled_updates WHERE id = ?",
                (created["id"],),
            ).fetchone()
        self.assertNotIn(b"segredo-de-teste", blob)
        self.assertTrue(Path(managed_path).is_file())
        self.assertEqual(
            self.validated_credentials,
            [("192.0.2.10", "admin", "segredo-de-teste")],
        )

    def test_due_schedule_executes_and_removes_secret_and_firmware(self):
        created = self.create()
        self.clock.value = datetime(2026, 9, 18, 12, 2, tzinfo=timezone.utc)
        self.assertEqual(self.scheduler.run_due_once(), created["id"])
        result = self.scheduler.get_schedule(created["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["percent"], 100)
        self.assertEqual(len(self.executions), 1)
        self.assertEqual(self.executions[0][1], "segredo-de-teste")

        with closing(sqlite3.connect(self.scheduler.settings.database_path)) as connection:
            blob, managed_path = connection.execute(
                "SELECT credential_blob, firmware_path FROM scheduled_updates WHERE id = ?",
                (created["id"],),
            ).fetchone()
        self.assertIsNone(blob)
        self.assertIsNone(managed_path)
        self.assertEqual(list(self.scheduler.settings.firmware_dir.rglob("*.swi")), [])
        logs = list(
            (self.root / "runtime" / "SwitchUpdateLogs" / "Set-26" / "Logs").glob(
                "SwitchUpdateLog_SWU000_18092026_090200*.log"
            )
        )
        self.assertEqual(len(logs), 1)
        log_text = logs[0].read_text(encoding="utf-8")
        self.assertIn(created["id"], log_text)
        self.assertIn("ATUALIZAÇÃO DE SWITCH", log_text)
        self.assertIn("RESULTADO: SUCESSO", log_text)
        self.assertIn("CÓDIGO DO RESULTADO: SWU000", log_text)
        self.assertIn("Orientação: nenhuma ação adicional é necessária.", log_text)
        self.assertNotIn("segredo-de-teste", log_text)
        self.assertEqual(
            result["log_relative_path"],
            f"Set-26/Logs/{logs[0].name}",
        )
        self.assertEqual(result["result_code"], "SWU000")

    def test_log_creation_failure_blocks_execution_before_upload(self):
        created = self.create()
        self.clock.value = datetime(2026, 9, 18, 12, 2, tzinfo=timezone.utc)
        with patch(
            "services.switch_update_v01.scheduler.logging.FileHandler",
            side_effect=PermissionError("negado"),
        ):
            self.scheduler.run_due_once()
        result = self.scheduler.get_schedule(created["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("criar o log", result["message"])
        self.assertEqual(result["result_code"], "SWU500")
        self.assertEqual(self.executions, [])

    def test_log_retention_removes_expired_logs_but_keeps_latest_per_switch(self):
        def register_log(host, timestamp, relative_path, scheduled_at):
            created = self.create(scheduled_at=scheduled_at)
            path = self.scheduler.log_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("relatorio de teste", encoding="utf-8")
            with closing(self.scheduler._connect()) as connection:
                connection.execute(
                    """
                    UPDATE scheduled_updates
                       SET host = ?, status = 'completed', stage = 'complete',
                           percent = 100, started_at_utc = ?, finished_at_utc = ?,
                           log_relative_path = ?, credential_blob = NULL,
                           firmware_path = NULL
                     WHERE id = ?
                    """,
                    (host, timestamp, timestamp, relative_path, created["id"]),
                )
            return created["id"], path

        old_a_id, old_a = register_log(
            "192.0.2.11",
            "2024-01-10T12:00:00+00:00",
            "Jan-24/Logs/SwitchUpdateLog_SWU000_10012024_090000.log",
            "2026-09-18T09:01:00",
        )
        _, recent_a = register_log(
            "192.0.2.11",
            "2026-03-10T12:00:00+00:00",
            "Mar-26/Logs/SwitchUpdateLog_SWU000_10032026_090000.log",
            "2026-09-18T09:02:00",
        )
        older_b_id, older_b = register_log(
            "192.0.2.12",
            "2023-01-10T12:00:00+00:00",
            "Jan-23/Logs/SwitchUpdateLog_SWU000_10012023_090000.log",
            "2026-09-18T09:03:00",
        )
        latest_b_id, latest_b = register_log(
            "192.0.2.12",
            "2024-01-10T12:00:00+00:00",
            "Jan-24/Logs/SwitchUpdateLog_SWU000_10012024_090001.log",
            "2026-09-18T09:04:00",
        )

        self.clock.value = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(self.scheduler.cleanup_expired_logs(), 2)
        self.assertFalse(old_a.exists())
        self.assertFalse(older_b.exists())
        self.assertTrue(recent_a.exists())
        self.assertTrue(latest_b.exists())
        with closing(self.scheduler._connect()) as connection:
            paths = dict(
                connection.execute(
                    "SELECT id, log_relative_path FROM scheduled_updates WHERE id IN (?, ?, ?)",
                    (old_a_id, older_b_id, latest_b_id),
                ).fetchall()
            )
        self.assertIsNone(paths[old_a_id])
        self.assertIsNone(paths[older_b_id])
        self.assertIsNotNone(paths[latest_b_id])

    def test_log_header_contains_only_requester_username(self):
        created = self.create()
        self.clock.value = datetime(2026, 9, 18, 12, 2, tzinfo=timezone.utc)
        self.scheduler.run_due_once()
        result = self.scheduler.get_schedule(created["id"])
        log_text = (self.scheduler.log_root / result["log_relative_path"]).read_text(
            encoding="utf-8"
        )
        self.assertIn("Solicitado por: operador.teste", log_text)
        self.assertNotIn("segredo-de-teste", log_text)
        self.assertNotIn("credential_blob", log_text)

    def test_failure_preserves_last_progress_and_removes_secret(self):
        def failing_executor(args, *, switch_password, reporter):
            reporter.emit("transfer", 50, "Transferindo firmware")
            raise RuntimeError("falha simulada")

        self.scheduler.executor = failing_executor
        created = self.create()
        self.clock.value = datetime(2026, 9, 18, 12, 2, tzinfo=timezone.utc)
        self.scheduler.run_due_once()
        result = self.scheduler.get_schedule(created["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["percent"], 50)
        self.assertNotIn("falha simulada\n", result["error"])
        log_path = self.scheduler.log_root / result["log_relative_path"]
        log_text = log_path.read_text(encoding="utf-8")
        self.assertIn("RESULTADO: NÃO CONCLUÍDO", log_text)
        self.assertIn("CÓDIGO DO RESULTADO: SWU320", log_text)
        self.assertIn("O envio do arquivo de atualização não foi concluído.", log_text)
        self.assertNotIn("falha simulada", log_text)
        self.assertEqual(result["result_code"], "SWU320")
        with closing(sqlite3.connect(self.scheduler.settings.database_path)) as connection:
            blob = connection.execute(
                "SELECT credential_blob FROM scheduled_updates WHERE id = ?", (created["id"],)
            ).fetchone()[0]
        self.assertIsNone(blob)

    def test_ping_timeout_requires_review_and_late_recheck_confirms_success(self):
        def timeout_executor(args, *, switch_password, reporter):
            reporter.emit("waiting_ping", 70, "Aguardando retorno do switch")
            raise UpdateNeedsReview("Retorno nao confirmado em ate sete minutos.")

        self.scheduler.executor = timeout_executor
        created = self.create()
        self.clock.value = datetime(2026, 9, 18, 12, 2, tzinfo=timezone.utc)
        self.scheduler.run_due_once()
        pending = self.scheduler.get_schedule(created["id"])
        self.assertEqual(pending["status"], "needs_review")
        self.assertEqual(pending["percent"], 70)
        self.assertEqual(list(self.scheduler.settings.firmware_dir.rglob("*.swi")), [])

        returned = WebIdentity(
            url="https://192.0.2.10/login.htm",
            title="Instant On 1930 Switch",
            sys_name="LAB-SW",
            sys_descr="InstantOn_1930_3.4.0.0 (6)",
            model="1930",
        )
        with patch(
            "services.switch_update_v01.scheduler.fetch_web_identity",
            return_value=returned,
        ):
            completed = self.scheduler.recheck_review(
                created["id"], owner="operador.teste"
            )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["stage"], "completed_after_review")
        self.assertEqual(completed["percent"], 100)
        self.assertEqual(completed["message"], LATE_SUCCESS_MESSAGE)
        self.assertEqual(completed["result_code"], "SWU411")
        self.assertIn("SwitchUpdateLog_SWU411_", completed["log_relative_path"])
        log_text = (self.scheduler.log_root / completed["log_relative_path"]).read_text(
            encoding="utf-8"
        )
        self.assertIn("RESULTADO: VERIFICAÇÃO NECESSÁRIA", log_text)
        self.assertIn("RESULTADO APÓS NOVA VERIFICAÇÃO: SUCESSO", log_text)
        self.assertIn("CÓDIGO DO RESULTADO: SWU411", log_text)
        self.assertIn(LATE_SUCCESS_MESSAGE, log_text)

    def test_result_code_catalog_maps_authentication_and_attachment(self):
        self.assertEqual(
            self.scheduler._classify_result_code(
                "authentication", "Login nao confirmado no switch"
            ),
            "SWU210",
        )
        self.assertEqual(
            self.scheduler._classify_result_code(
                "upload_setup", "Falha ao anexar o arquivo no campo de upload"
            ),
            "SWU310",
        )

    def test_confirmed_same_version_and_downgrade_map_to_executor_flags(self):
        self.decision = "same_version"
        same = self.create(confirmed_decision="same_version")
        self.clock.value = datetime(2026, 9, 18, 12, 2, tzinfo=timezone.utc)
        self.scheduler.run_due_once()
        self.assertEqual(self.scheduler.get_schedule(same["id"])["status"], "completed")
        same_args = self.executions[-1][0]
        self.assertTrue(same_args.allow_same_version)
        self.assertFalse(same_args.allow_downgrade)

        self.decision = "downgrade"
        downgrade = self.create(
            confirmed_decision="downgrade",
            scheduled_at="2026-09-18T09:03:00",
        )
        self.clock.value = datetime(2026, 9, 18, 12, 4, tzinfo=timezone.utc)
        self.scheduler.run_due_once()
        self.assertEqual(self.scheduler.get_schedule(downgrade["id"])["status"], "completed")
        downgrade_args = self.executions[-1][0]
        self.assertFalse(downgrade_args.allow_same_version)
        self.assertTrue(downgrade_args.allow_downgrade)

    def test_cancel_removes_secret_and_firmware(self):
        created = self.create()
        result = self.scheduler.cancel_schedule(created["id"], owner="operador.teste")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(list(self.scheduler.settings.firmware_dir.rglob("*.swi")), [])
        with closing(sqlite3.connect(self.scheduler.settings.database_path)) as connection:
            blob = connection.execute(
                "SELECT credential_blob FROM scheduled_updates WHERE id = ?", (created["id"],)
            ).fetchone()[0]
        self.assertIsNone(blob)

    def test_duplicate_pending_switch_is_blocked(self):
        self.create()
        with self.assertRaises(ScheduleError):
            self.create(scheduled_at="2026-09-18T10:00:00")

    def test_decision_change_is_blocked(self):
        with self.assertRaises(ScheduleError):
            self.create(confirmed_decision="downgrade")

    def test_interrupted_job_requires_manual_review_and_is_not_retried(self):
        created = self.create()
        with closing(sqlite3.connect(self.scheduler.settings.database_path)) as connection:
            connection.execute(
                "UPDATE scheduled_updates SET status = 'running' WHERE id = ?", (created["id"],)
            )
            connection.commit()
        self.assertEqual(self.scheduler.recover_interrupted(), 1)
        result = self.scheduler.get_schedule(created["id"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(self.scheduler.run_due_once(), None)
        self.assertEqual(self.executions, [])
        with self.assertRaises(ScheduleError):
            self.create(scheduled_at="2026-09-18T10:00:00")
        reviewed = self.scheduler.acknowledge_review(created["id"], owner="operador.teste")
        self.assertEqual(reviewed["status"], "reviewed")
        replacement = self.create(scheduled_at="2026-09-18T10:00:00")
        self.assertEqual(replacement["status"], "scheduled")

    def test_owner_cannot_cancel_another_users_schedule(self):
        created = self.create()
        with self.assertRaises(ScheduleError):
            self.scheduler.cancel_schedule(created["id"], owner="outro.usuario")

    def test_draft_contains_no_credentials_and_becomes_schedule(self):
        draft = self.scheduler.create_draft(
            owner="operador.teste",
            url="https://192.0.2.10",
            firmware=self.source,
            original_name=self.source.name,
        )
        self.assertEqual(draft["decision"], "update")
        self.assertNotIn("firmware_path", draft)
        schedule = self.scheduler.schedule_from_draft(
            draft_id=draft["draft_token"],
            owner="operador.teste",
            scheduled_at="2026-09-18T09:01:00",
            username="admin",
            password="segredo-de-teste",
            confirmed_decision="update",
        )
        self.assertEqual(schedule["status"], "scheduled")
        with self.assertRaises(ScheduleError):
            self.scheduler.get_draft(draft["draft_token"], owner="operador.teste")

    def test_expired_draft_is_removed_with_its_file(self):
        draft = self.scheduler.create_draft(
            owner="operador.teste",
            url="https://192.0.2.10",
            firmware=self.source,
        )
        self.clock.value = datetime(2026, 9, 18, 12, 20, tzinfo=timezone.utc)
        self.assertEqual(self.scheduler.cleanup_expired_drafts(), 1)
        self.assertEqual(list(self.scheduler.draft_dir.glob("*.swi")), [])
        with self.assertRaises(ScheduleError):
            self.scheduler.get_draft(draft["draft_token"], owner="operador.teste")


@unittest.skipUnless(os.name == "nt", "DPAPI existe somente no Windows")
class DpapiTests(unittest.TestCase):
    def test_roundtrip_does_not_return_plaintext(self):
        protector = DpapiCredentialProtector()
        protected = protector.protect("segredo-dpapi")
        self.assertNotIn(b"segredo-dpapi", protected)
        self.assertEqual(protector.unprotect(protected), "segredo-dpapi")


if __name__ == "__main__":
    unittest.main()
