import json
import os
from pathlib import Path
import tempfile
import unittest

from core.secret_store import (
    DpapiCurrentUserProtector,
    DpapiLocalMachineProtector,
    JsonSecretStore,
    SecretNotFoundError,
    SecretStoreError,
)


class FakeProtector:
    name = "fake-test-protector"

    def protect(self, secret: str) -> bytes:
        if not secret:
            raise SecretStoreError("empty")
        return secret.encode("utf-8")[::-1]

    def unprotect(self, protected: bytes) -> str:
        return bytes(protected)[::-1].decode("utf-8")


class JsonSecretStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "secrets.json"
        self.store = JsonSecretStore(self.path, protector=FakeProtector())

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_roundtrip_does_not_persist_plaintext(self):
        self.store.put("regional/REG_TESTE/server/1/password", "segredo-unico")

        self.assertEqual(
            self.store.get("regional/REG_TESTE/server/1/password"),
            "segredo-unico",
        )
        self.assertNotIn("segredo-unico", self.path.read_text(encoding="utf-8"))

    def test_update_and_delete(self):
        reference = "environment/zabbix/password"
        self.store.put(reference, "primeiro")
        self.store.put(reference, "segundo")

        self.assertTrue(self.store.contains(reference))
        self.assertEqual(self.store.get(reference), "segundo")
        self.assertTrue(self.store.delete(reference))
        self.assertFalse(self.store.contains(reference))
        self.assertFalse(self.store.delete(reference))
        with self.assertRaises(SecretNotFoundError):
            self.store.get(reference)

    def test_put_many_persists_all_values_without_plaintext(self):
        self.store.put_many({
            "regional/test/server/1/password": "secret-one",
            "regional/test/server/2/password": "secret-two",
        })

        self.assertEqual(
            self.store.get("regional/test/server/1/password"), "secret-one"
        )
        self.assertEqual(
            self.store.get("regional/test/server/2/password"), "secret-two"
        )
        persisted = self.path.read_text(encoding="utf-8")
        self.assertNotIn("secret-one", persisted)
        self.assertNotIn("secret-two", persisted)

    def test_get_many_returns_all_requested_values(self):
        self.store.put_many({
            "regional/test/server/1/password": "secret-one",
            "regional/test/server/2/password": "secret-two",
        })

        self.assertEqual(
            self.store.get_many([
                "regional/test/server/1/password",
                "regional/test/server/2/password",
            ]),
            {
                "regional/test/server/1/password": "secret-one",
                "regional/test/server/2/password": "secret-two",
            },
        )

    def test_rejects_unsafe_reference(self):
        with self.assertRaises(SecretStoreError):
            self.store.put("../outside", "segredo")

    def test_rejects_incompatible_store(self):
        self.path.write_text(
            json.dumps({"version": 99, "protection": "unknown", "entries": {}}),
            encoding="utf-8",
        )
        with self.assertRaises(SecretStoreError):
            self.store.contains("environment/test/password")


@unittest.skipUnless(os.name == "nt", "DPAPI existe somente no Windows")
class DpapiCurrentUserTests(unittest.TestCase):
    def test_roundtrip(self):
        protector = DpapiCurrentUserProtector()
        protected = protector.protect("segredo-dpapi-current-user")

        self.assertNotIn(b"segredo-dpapi-current-user", protected)
        self.assertEqual(
            protector.unprotect(protected),
            "segredo-dpapi-current-user",
        )

    def test_local_machine_roundtrip(self):
        protector = DpapiLocalMachineProtector()
        protected = protector.protect("segredo-dpapi-local-machine")

        self.assertNotIn(b"segredo-dpapi-local-machine", protected)
        self.assertEqual(
            protector.unprotect(protected),
            "segredo-dpapi-local-machine",
        )


if __name__ == "__main__":
    unittest.main()
