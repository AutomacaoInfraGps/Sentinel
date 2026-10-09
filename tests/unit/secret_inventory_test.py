import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "security"
    / "inventory_secret_fields.py"
)
SPEC = importlib.util.spec_from_file_location("inventory_secret_fields", MODULE_PATH)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


class SecretInventoryTest(unittest.TestCase):
    def test_inventory_reports_paths_without_values(self):
        secret_value = "never-print-this-secret"
        payload = {
            "environment": {"password": secret_value, "token_cache_path": "cache.bin"},
            "regionais": {
                "REG_EXAMPLE": {
                    "servidores": [
                        {"usuario": "operator", "senha": secret_value},
                    ]
                }
            },
        }

        findings = inventory.inventory_payload(payload)
        rendered = "\n".join(path for (_, path), _ in findings.items())

        self.assertIn("$.environment.password", rendered)
        self.assertIn("$.regionais.*.servidores[*].senha", rendered)
        self.assertNotIn("token_cache_path", rendered)
        self.assertNotIn(secret_value, rendered)

    def test_classifies_common_secret_and_identity_names(self):
        self.assertEqual("secret", inventory.classify_field("client_secret"))
        self.assertEqual("secret", inventory.classify_field("api-key"))
        self.assertEqual("identity", inventory.classify_field("username"))
        self.assertIsNone(inventory.classify_field("token_cache_path"))
        self.assertIsNone(inventory.classify_field("timeout"))


if __name__ == "__main__":
    unittest.main()
