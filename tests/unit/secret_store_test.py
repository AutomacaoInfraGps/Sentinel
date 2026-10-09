import json
import os
from pathlib import Path
import tempfile
import unittest

from core.secret_store import (
    DpapiCurrentUserProtector,
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


if __name__ == "__main__":
    unittest.main()
