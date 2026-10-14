import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


os.environ.setdefault("AUTOMACAO_PUBLIC_BASE", tempfile.mkdtemp())

import config  # noqa: E402


class ConfigValidationTests(unittest.TestCase):
    def test_legacy_connections_file_is_optional(self):
        missing_file = Path(tempfile.mkdtemp()) / "Conexoes.txt"

        with patch.object(config, "CONEXOES_FILE", missing_file):
            self.assertEqual(config.validate_config(), [])


if __name__ == "__main__":
    unittest.main()
