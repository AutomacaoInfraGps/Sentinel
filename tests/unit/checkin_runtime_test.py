"""Exercise the scheduled BAT entry points using isolated, synthetic Python jobs."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import venv


ROOT = Path(__file__).resolve().parents[2]
JOBS = [
    ("executar_checkin_diario.bat", "executar_tudo.py", "checkin_diario.log", "--no-browser"),
    ("executar_envio_dashboard_consolidado.bat", "enviar_dashboard_consolidado_email.py",
     "envio_dashboard_consolidado_task.log", ""),
]


@unittest.skipUnless(os.name == "nt", "Windows scheduled BAT entry points")
class CheckinRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sentinel runtime ")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for batch, script, _, _ in JOBS:
            shutil.copyfile(ROOT / batch, self.directory / batch)
            (self.directory / script).write_text(
                "import sys\nfrom pathlib import Path\n"
                "print('RUNTIME=' + sys.executable)\n"
                "print('ARGUMENTS=' + ' '.join(sys.argv[1:]))\n"
                "sys.exit(int(Path('exit_code.txt').read_text()))\n", encoding="utf-8")
        (self.directory / "exit_code.txt").write_text("0", encoding="ascii")
        venv.EnvBuilder(with_pip=False).create(self.directory / ".venv")

    def run_jobs(self, environment, expected_exit):
        for batch, _, log, arguments in JOBS:
            with self.subTest(batch=batch):
                result = subprocess.run(
                    [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", batch],
                    cwd=self.directory, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                output = (self.directory / "logs" / log).read_text(encoding="utf-8", errors="replace")
                self.assertIn(str(self.directory / environment / "Scripts" / "python.exe"), output)
                self.assertIn("ARGUMENTS=" + arguments, output)

    def test_preferred_runtime_is_used_when_both_environments_exist(self):
        venv.EnvBuilder(with_pip=False).create(self.directory / ".venv31410")
        self.run_jobs(".venv31410", 0)

    def test_existing_environment_remains_supported(self):
        self.run_jobs(".venv", 0)

    def test_python_failure_returns_failure_to_task_scheduler(self):
        venv.EnvBuilder(with_pip=False).create(self.directory / ".venv31410")
        (self.directory / "exit_code.txt").write_text("17", encoding="ascii")
        self.run_jobs(".venv31410", 1)
