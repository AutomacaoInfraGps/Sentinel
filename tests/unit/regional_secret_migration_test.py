import json
import tempfile
import unittest
from pathlib import Path

from core.environment_loader import EnvironmentConfigError
from core.secret_store import SecretNotFoundError
from gerenciar_regionais import GerenciadorRegionais, REGIONAL_CREDENTIAL_STORAGE
from scripts.security.migrate_regional_secrets import (
    build_plan,
    migrate_payload,
    rollback_payload,
    verify_payload,
)


class FakeSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.put_calls = []

    def put(self, reference, secret):
        self.values[reference] = secret
        self.put_calls.append(reference)

    def put_many(self, secrets):
        self.values.update(secrets)
        self.put_calls.extend(secrets)

    def get(self, reference):
        try:
            return self.values[reference]
        except KeyError as exc:
            raise SecretNotFoundError("missing") from exc


def sample_payload():
    return {
        "regionais": {
            "REG_TESTE": {
                "nome": "Teste",
                "servidores": [{
                    "id": "srv-01",
                    "nome": "Servidor",
                    "tipo": "vm",
                    "ip": "192.0.2.10",
                    "usuario": "operator",
                    "senha": "synthetic-secret",
                }],
                "links": [],
            }
        },
        "configuracao": {"versao": "2.0"},
    }


class RegionalSecretMigrationTests(unittest.TestCase):
    def test_migration_roundtrip(self):
        payload = sample_payload()
        store = FakeSecretStore()

        migrated, items = migrate_payload(payload, secret_store=store)

        self.assertEqual(len(items), 1)
        self.assertNotIn("synthetic-secret", json.dumps(migrated))
        self.assertEqual(verify_payload(migrated, secret_store=store), 1)
        restored, count = rollback_payload(migrated, secret_store=store)
        self.assertEqual(count, 1)
        self.assertEqual(restored, payload)

    def test_plan_uses_stable_server_reference(self):
        plan = build_plan(sample_payload())
        self.assertEqual(
            plan[0].reference,
            "regionals/reg_teste/servers/srv-01/senha",
        )
        self.assertNotIn("synthetic-secret", repr(plan[0]))

    def test_manager_resolves_and_persists_references(self):
        store = FakeSecretStore()
        migrated, _ = migrate_payload(sample_payload(), secret_store=store)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regionais.json"
            path.write_text(json.dumps(migrated), encoding="utf-8")

            manager = GerenciadorRegionais(str(path), secret_store=store)
            server = manager.obter_servidor("REG_TESTE", "srv-01")
            self.assertEqual(server["senha"], "synthetic-secret")

            calls_before = len(store.put_calls)
            server["status"] = "online"
            manager.atualizar_servidor("REG_TESTE", "srv-01", server)
            raw = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(len(store.put_calls), calls_before)
            self.assertEqual(
                raw["regionais"]["REG_TESTE"]["servidores"][0]["senha"],
                {"credential_ref": "regionals/reg_teste/servers/srv-01/senha"},
            )

    def test_new_server_is_written_to_vault_after_migration(self):
        store = FakeSecretStore()
        payload = {
            "regionais": {"REG_TESTE": {"servidores": [], "links": []}},
            "configuracao": {"credential_storage": REGIONAL_CREDENTIAL_STORAGE},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regionais.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            manager = GerenciadorRegionais(str(path), secret_store=store)
            manager.adicionar_servidor("REG_TESTE", {
                "id": "srv-new",
                "nome": "Novo",
                "tipo": "vm",
                "ip": "192.0.2.20",
                "usuario": "operator",
                "senha": "new-secret",
            })

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("new-secret", json.dumps(raw))
            self.assertEqual(
                store.get("regionals/reg_teste/servers/srv-new/senha"),
                "new-secret",
            )

    def test_missing_vault_entry_fails_without_replacing_regional_data(self):
        payload = sample_payload()
        store = FakeSecretStore()
        migrated, _ = migrate_payload(payload, secret_store=store)
        store.values.clear()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regionais.json"
            path.write_text(json.dumps(migrated), encoding="utf-8")

            with self.assertRaises(EnvironmentConfigError):
                GerenciadorRegionais(str(path), secret_store=store)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), migrated)


if __name__ == "__main__":
    unittest.main()
