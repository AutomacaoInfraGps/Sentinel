import json
from pathlib import Path
from unittest.mock import patch
import unittest

import coleta_dados_acraby


class SecureRegionalConsumersTests(unittest.TestCase):
    def test_consolidated_collector_uses_secure_regional_manager(self):
        source = Path("executar_tudo.py").read_text(encoding="utf-8")
        function_source = source.split(
            "def _carregar_servidores_da_estrutura():", 1
        )[1].split("def _carregar_servidores_configurados():", 1)[0]

        self.assertIn("GerenciadorRegionais", function_source)
        self.assertNotIn("json.loads", function_source)
        self.assertNotIn("read_text", function_source)

    @patch("coleta_dados_acraby.subprocess.run")
    def test_certificate_collector_keeps_password_out_of_command_line(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({"Subject": "CN=example"})
        run.return_value.stderr = ""
        secret = "SYNTHETIC_COMMAND_LINE_SECRET"

        coleta_dados_acraby.run_remote_powershell(
            "server.example", "operator", secret, "Get-Item Env:TEMP"
        )

        args, kwargs = run.call_args
        command = " ".join(args[0])
        self.assertNotIn(secret, command)
        self.assertNotIn("operator", command)
        self.assertIn(secret, kwargs["input"])
        self.assertTrue(kwargs["text"])

    def test_certificate_collector_no_longer_reads_plaintext_backup(self):
        source = Path("coleta_dados_acraby.py").read_text(encoding="utf-8")

        self.assertNotIn("BACKUP_FILE", source)
        self.assertNotIn("load_credentials_from_backup", source)
        self.assertIn("GerenciadorRegionais", source)


if __name__ == "__main__":
    unittest.main()
