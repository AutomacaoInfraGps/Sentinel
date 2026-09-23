from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.switch_update_v01.worker import (
    WorkerAlreadyRunning,
    WorkerFileLock,
    load_project_config,
    run_once,
)


class FakeScheduler:
    def __init__(self) -> None:
        self.calls = []

    def recover_interrupted(self) -> int:
        self.calls.append("recover")
        return 0

    def perform_maintenance(self) -> None:
        self.calls.append("maintenance")

    def run_all_due(self) -> list[str]:
        self.calls.append("run")
        return ["job-1", "job-2"]


class WorkerTests(unittest.TestCase):
    def test_run_once_recovers_maintains_and_drains_queue(self) -> None:
        scheduler = FakeScheduler()
        with tempfile.TemporaryDirectory() as temporary_directory:
            processed = run_once(
                scheduler,
                lock_path=Path(temporary_directory) / "worker.lock",
            )

        self.assertEqual(processed, ["job-1", "job-2"])
        self.assertEqual(
            scheduler.calls,
            ["recover", "maintenance", "run", "maintenance"],
        )

    def test_process_lock_rejects_second_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "worker.lock"
            with WorkerFileLock(lock_path):
                with self.assertRaises(WorkerAlreadyRunning):
                    with WorkerFileLock(lock_path):
                        pass

    def test_project_config_reads_only_switch_update_section(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_file = Path(temporary_directory) / "environment.json"
            config_file.write_text(
                '{"switch_update": {"insecure_tls": false, "http_timeout": 12}, '
                '"secret": "ignored"}',
                encoding="utf-8",
            )

            config = load_project_config(config_file)

        self.assertEqual(config, {"insecure_tls": False, "http_timeout": 12})


if __name__ == "__main__":
    unittest.main()
