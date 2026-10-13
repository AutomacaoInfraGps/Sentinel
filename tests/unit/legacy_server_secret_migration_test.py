import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.secret_store import SecretNotFoundError
from gerenciar_servidores import GerenciadorServidores
from scripts.security.migrate_legacy_server_secrets import (
    migrate_payload,
    rollback_payload,
    verify_payload,
)


class FakeSecretStore:
    def __init__(self):
        self.values = {}

    def put(self, reference, secret):
        self.values[reference] = secret

    def put_many(self, secrets):
        self.values.update(secrets)

    def get(self, reference):
        try:
            return self.values[reference]
        except KeyError as exc:
            raise SecretNotFoundError("missing") from exc


def sample_payload():
    return {
        "servidores": [{
            "id": "idrac-01",
            "nome": "iDRAC Teste",
            "tipo": "idrac",
            "ip": "192.0.2.30",
            "usuario": "operator",
            "senha": "synthetic-secret",
            "ativo": True,
        }],
        "configuracao": {"versao": "1.0"},
    }


class LegacyServerSecretMigrationTests(unittest.TestCase):
    def test_migration_manager_and_rollback(self):
        payload = sample_payload()
        store = FakeSecretStore()
        migrated, items = migrate_payload(payload, secret_store=store)

        self.assertEqual(len(items), 1)
        self.assertNotIn("synthetic-secret", json.dumps(migrated))
        self.assertEqual(verify_payload(migrated, secret_store=store), 1)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "servidores.json"
            path.write_text(json.dumps(migrated), encoding="utf-8")
            manager = GerenciadorServidores(path, secret_store=store)
            self.assertEqual(
                manager.listar_servidores()[0]["senha"], "synthetic-secret"
            )
            with patch("builtins.print"):
                self.assertFalse(manager.gerar_arquivo_conexoes_legado())

        restored, count = rollback_payload(migrated, secret_store=store)
        self.assertEqual(count, 1)
        self.assertEqual(restored, payload)

    def test_secure_export_does_not_contain_plaintext(self):
        store = FakeSecretStore()
        migrated, _ = migrate_payload(sample_payload(), secret_store=store)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "servidores.json"
            exported = root / "export.json"
            source.write_text(json.dumps(migrated), encoding="utf-8")
            manager = GerenciadorServidores(source, secret_store=store)

            with patch("builtins.print"):
                manager.exportar_configuracao(str(exported))

            self.assertNotIn("synthetic-secret", exported.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
