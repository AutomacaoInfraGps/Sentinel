import json
from pathlib import Path
import tempfile
import unittest

from core.environment_loader import (
    EnvironmentConfigError,
    contains_credential_reference,
    load_environment_file,
    redact_environment_secrets,
    resolve_credential_references,
    save_environment_file,
)
from core.secret_store import SecretNotFoundError


class FakeSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, reference: str) -> str:
        try:
            return self.values[reference]
        except KeyError as exc:
            raise SecretNotFoundError("missing") from exc


class EnvironmentLoaderTests(unittest.TestCase):
    def test_detects_references_without_treating_regular_dicts_as_references(self):
        self.assertTrue(
            contains_credential_reference(
                {"zabbix": {"password": {"credential_ref": "environment/zabbix/password"}}}
            )
        )
        self.assertFalse(
            contains_credential_reference(
                {"metadata": {"credential_ref": "label", "enabled": True}}
            )
        )

    def test_keeps_existing_inline_values_compatible(self):
        payload = {
            "zabbix": {
                "username": "operator",
                "password": "senha-atual",
            }
        }

        resolved = resolve_credential_references(
            payload,
            secret_store=FakeSecretStore(),
        )

        self.assertEqual(resolved, payload)
        self.assertIsNot(resolved, payload)

    def test_resolves_reference_only_in_memory(self):
        reference = "environment/zabbix/password"
        payload = {
            "zabbix": {
                "password": {"credential_ref": reference},
            }
        }

        resolved = resolve_credential_references(
            payload,
            secret_store=FakeSecretStore({reference: "segredo-resolvido"}),
        )

        self.assertEqual(resolved["zabbix"]["password"], "segredo-resolvido")
        self.assertEqual(payload["zabbix"]["password"], {"credential_ref": reference})

    def test_missing_reference_fails_without_exposing_reference(self):
        reference = "environment/sistema-muito-sensivel/password"
        with self.assertRaises(EnvironmentConfigError) as raised:
            resolve_credential_references(
                {"password": {"credential_ref": reference}},
                secret_store=FakeSecretStore(),
            )

        self.assertNotIn(reference, str(raised.exception))

    def test_load_can_return_raw_configuration_for_safe_editing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "environment.json"
            reference = "environment/zabbix/password"
            path.write_text(
                json.dumps({"zabbix": {"password": {"credential_ref": reference}}}),
                encoding="utf-8",
            )

            raw = load_environment_file(path, resolve_secrets=False)

        self.assertEqual(raw["zabbix"]["password"]["credential_ref"], reference)

    def test_redaction_covers_nested_secret_fields(self):
        payload = {
            "fortigate": {
                "RJ": {"host": "192.0.2.10", "password": "nao-expor"},
            },
            "microsoft_graph": {"client_secret": {"credential_ref": "environment/graph"}},
        }

        redacted = redact_environment_secrets(payload)

        self.assertEqual(redacted["fortigate"]["RJ"]["password"], "")
        self.assertEqual(redacted["microsoft_graph"]["client_secret"], "")
        self.assertEqual(redacted["fortigate"]["RJ"]["host"], "192.0.2.10")
        self.assertEqual(payload["fortigate"]["RJ"]["password"], "nao-expor")

    def test_save_is_compatible_with_raw_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "environment.json"
            payload = {"zabbix": {"password": "valor-legado"}}

            save_environment_file(path, payload)

            self.assertEqual(
                load_environment_file(path, resolve_secrets=False),
                payload,
            )


if __name__ == "__main__":
    unittest.main()
