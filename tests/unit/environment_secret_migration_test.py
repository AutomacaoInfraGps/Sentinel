import io
from contextlib import redirect_stdout
import unittest

from core.environment_loader import resolve_credential_references
from core.secret_store import SecretNotFoundError
from scripts.security.migrate_environment_secrets import (
    build_migration_plan,
    main,
    migrate_payload,
    rollback_payload,
    verify_payload,
)


class FakeSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def put(self, reference: str, secret: str) -> None:
        self.values[reference] = secret

    def get(self, reference: str) -> str:
        try:
            return self.values[reference]
        except KeyError as exc:
            raise SecretNotFoundError("missing") from exc


class EnvironmentSecretMigrationTests(unittest.TestCase):
    def test_plan_never_exposes_values(self):
        secret = "SYNTHETIC_MUST_NOT_BE_RENDERED"
        payload = {
            "zabbix": {"username": "operator", "password": secret},
            "timeouts": {"connection_timeout": 10},
        }

        plan = build_migration_plan(payload)

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].reference, "environment/zabbix/password")
        self.assertNotIn(secret, repr(plan[0]))

    def test_migration_roundtrip_preserves_complete_configuration(self):
        payload = {
            "fortigate": {
                "RJ": {"host": "192.0.2.10", "password": "forti-secret"},
            },
            "microsoft_graph": {"client_secret": "graph-secret"},
            "empty": {"password": ""},
        }
        store = FakeSecretStore()

        migrated, items = migrate_payload(payload, secret_store=store)

        self.assertEqual(len(items), 2)
        self.assertEqual(
            migrated["fortigate"]["RJ"]["password"],
            {"credential_ref": "environment/fortigate/rj/password"},
        )
        self.assertNotIn("forti-secret", str(migrated))
        self.assertEqual(
            resolve_credential_references(migrated, secret_store=store),
            payload,
        )
        self.assertEqual(verify_payload(migrated, secret_store=store), 2)

    def test_existing_reference_is_not_migrated_again(self):
        payload = {
            "zabbix": {
                "password": {"credential_ref": "environment/zabbix/password"},
            }
        }

        self.assertEqual(build_migration_plan(payload), [])

    def test_rollback_restores_values_without_deleting_store(self):
        reference = "environment/zabbix/password"
        store = FakeSecretStore({reference: "restored-secret"})
        payload = {"zabbix": {"password": {"credential_ref": reference}}}

        restored, count = rollback_payload(payload, secret_store=store)

        self.assertEqual(count, 1)
        self.assertEqual(restored["zabbix"]["password"], "restored-secret")
        self.assertEqual(store.get(reference), "restored-secret")

    def test_default_cli_mode_is_preview_only(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--file", "missing-environment.json"])

        self.assertEqual(result, 0)
        self.assertIn("Nenhum segredo preenchido", output.getvalue())


if __name__ == "__main__":
    unittest.main()
