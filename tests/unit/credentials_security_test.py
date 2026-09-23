import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import credentials


class CredentialsSecurityTests(unittest.TestCase):
    def test_master_password_is_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(credentials.CredentialConfigurationError):
                credentials.get_encryption_key()

    def test_short_master_password_is_rejected(self):
        with patch.dict(
            os.environ,
            {credentials.MASTER_PASSWORD_ENV: "curta"},
            clear=True,
        ):
            with self.assertRaises(credentials.CredentialConfigurationError):
                credentials.get_encryption_key()

    def test_credentials_round_trip_with_strong_master_password(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            password = "senha-mestra-de-teste-com-mais-de-32-caracteres"
            with (
                patch.object(credentials, "CREDENTIALS_FILE", root / "credentials.bin"),
                patch.object(credentials, "SALT_FILE", root / "salt.bin"),
                patch.dict(
                    os.environ,
                    {credentials.MASTER_PASSWORD_ENV: password},
                    clear=True,
                ),
            ):
                expected = {"servico": {"username": "teste", "password": "segredo"}}
                credentials.encrypt_credentials(expected)
                self.assertEqual(credentials.decrypt_credentials(), expected)


if __name__ == "__main__":
    unittest.main()
