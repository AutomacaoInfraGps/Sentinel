from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from alertad import cli
from alertad.contracts import (
    CheckpointAdvance,
    DirectoryObject,
    DirectoryResolution,
    DirectoryResolutionStatus,
    EventCheckpoint,
)
from alertad.event_source import EventLogReadError
from alertad.persistence import EventStore
from alertad.sentinel_environment import load_sentinel_graph_environment


PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHER = PROJECT_ROOT / "alertad.py"


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LAUNCHER), *(str(value) for value in arguments)],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_init_and_status_respect_dry_run_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "dry-run.db"

            initialized = self.run_cli("init-db", database, "--dry-run")
            status = self.run_cli("status", database, "--dry-run")
            wrong_mode = self.run_cli("status", database)

        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["events"], 0)
        self.assertEqual(wrong_mode.returncode, 2)
        self.assertIn("Modo do banco incompatível", wrong_mode.stdout)

    def test_read_only_command_does_not_create_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.db"
            output = Path(directory) / "report.csv"

            result = self.run_cli("report", database, output)

            self.assertEqual(result.returncode, 2)
            self.assertFalse(database.exists())
            self.assertFalse(output.exists())

    def test_worker_rejects_missing_explicit_environment_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_cli(
                "worker",
                root / "worker.db",
                "--settings",
                PROJECT_ROOT / "config" / "settings.example.json",
                "--env-file",
                root / "missing.env",
                "--once",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Arquivo de ambiente não encontrado", result.stdout)

    def test_status_exposes_sanitized_checkpoint_progress_without_bookmark(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "status.db"
            store = EventStore(database)
            store.advance_checkpoint(
                CheckpointAdvance(
                    None,
                    EventCheckpoint(
                        "ForwardedEvents",
                        "SYNTHETIC-OPAQUE-BOOKMARK",
                        "generation-synthetic",
                        42,
                    ),
                )
            )

            result = self.run_cli("status", database)

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["checkpoints"][0]["logical_sequence"], 42)
        self.assertEqual(payload["checkpoints"][0]["source"], "forwardedevents")
        self.assertNotIn("SYNTHETIC-OPAQUE-BOOKMARK", result.stdout)

    def test_loads_sentinel_graph_values_without_overriding_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment_file = Path(directory) / "environment.json"
            environment_file.write_text(
                json.dumps(
                    {
                        "microsoft_graph": {
                            "tenant_id": "synthetic-tenant",
                            "client_id": "synthetic-client",
                            "client_secret": "synthetic-secret",
                            "sender_upn": "sender@example.invalid",
                        }
                    }
                ),
                encoding="utf-8",
            )
            environment = {"M365_CLIENT_ID": "process-client"}
            load_sentinel_graph_environment(environment_file, environ=environment)

        self.assertEqual(environment["M365_TENANT_ID"], "synthetic-tenant")
        self.assertEqual(environment["M365_CLIENT_ID"], "process-client")
        self.assertEqual(environment["M365_CLIENT_SECRET"], "synthetic-secret")
        self.assertEqual(environment["M365_SENDER_UPN"], "sender@example.invalid")

    def test_sentinel_environment_errors_do_not_expose_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment_file = Path(directory) / "environment.json"
            environment_file.write_text(
                '{"client_secret":"SYNTHETIC_MUST_NOT_LEAK"',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                "Arquivo de ambiente do Sentinel invalido",
            ) as raised:
                load_sentinel_graph_environment(environment_file, environ={})

        self.assertNotIn("SYNTHETIC_MUST_NOT_LEAK", str(raised.exception))

    def test_cli_returns_failure_when_controlled_read_fails(self) -> None:
        output = io.StringIO()
        arguments = [
            "alertad",
            "worker",
            "synthetic.db",
            "--settings",
            "synthetic.json",
            "--once",
        ]
        with patch.object(cli, "_run_worker", side_effect=EventLogReadError("synthetic")):
            with patch.object(sys, "argv", arguments):
                with redirect_stdout(output):
                    return_code = cli.main()

        self.assertEqual(return_code, 2)
        self.assertIn("synthetic", output.getvalue())

    def test_simulation_forces_missing_member_and_uses_interactive_resolver(self) -> None:
        class FakeResolver:
            def resolve_sid(self, sid):
                return DirectoryResolution(
                    DirectoryResolutionStatus.RESOLVED,
                    DirectoryObject(sid, "usuario.resolvido", "user", "EXAMPLE"),
                )

        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "poll_interval_seconds": 10,
                        "directory": {
                            "enabled": True,
                            "backend": "POWERSHELL_ADWS",
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            arguments = [
                "alertad",
                "simulate-missing-member",
                str(PROJECT_ROOT / "tests" / "fixtures" / "event_4733.xml"),
                "--settings",
                str(settings),
            ]
            with patch.object(cli, "_directory_resolver", return_value=FakeResolver()) as factory:
                with patch.object(sys, "argv", arguments):
                    with redirect_stdout(output):
                        return_code = cli.main()

        self.assertEqual(return_code, 0)
        self.assertIn('"directory_status": "resolved"', output.getvalue())
        self.assertIn("Usuário: EXAMPLE\\usuario.resolvido", output.getvalue())
        self.assertTrue(factory.call_args.kwargs["interactive_credentials"])


if __name__ == "__main__":
    unittest.main()
