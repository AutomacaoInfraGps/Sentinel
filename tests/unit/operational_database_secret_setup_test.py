from contextlib import redirect_stderr, redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.database.configure_collector_secret import (
    COLLECTOR_REFERENCE, configure, main, verify_windows_identity,
)
from scripts.database.import_firewall_cache import ImportErrorSafe


class FakeStore:
    def __init__(self):
        self.entries = {"unrelated/credential": "EXISTING_SECRET"}
        self.writes = []

    def contains(self, reference):
        return reference in self.entries

    def put(self, reference, value):
        self.writes.append(reference)
        self.entries[reference] = value

    def get(self, reference):
        return self.entries[reference]


class FakeConnection:
    def __init__(self, identity=("sentinel_collector", "sentinel", 5433)):
        self.identity = identity
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def execute(self, sql):
        self.sql.append(sql)

    def fetchone(self):
        return self.identity


class OperationalDatabaseSecretSetupTests(unittest.TestCase):
    def test_only_new_reference_is_saved_after_read_only_validation(self):
        store = FakeStore()
        connection = FakeConnection()
        captured = {}

        def connect(**kwargs):
            captured.update(kwargs)
            self.assertEqual(store.writes, [])
            return connection

        result = configure("Test$Password", store=store, connect=connect)
        self.assertEqual(store.writes, [COLLECTOR_REFERENCE])
        self.assertEqual(store.get("unrelated/credential"), "EXISTING_SECRET")
        self.assertEqual(store.get(COLLECTOR_REFERENCE), "Test$Password")
        self.assertIn("default_transaction_read_only=on", captured["options"])
        self.assertEqual((captured["port"], captured["user"], captured["dbname"]), (5433, "sentinel_collector", "sentinel"))
        self.assertFalse(result["sincronizacao_habilitada"])
        self.assertNotIn("Test$Password", json.dumps(result))
        self.assertTrue(all(sql.startswith("SELECT") for sql in connection.sql))

    def test_existing_reference_is_never_overwritten(self):
        store = FakeStore()
        store.entries[COLLECTOR_REFERENCE] = "KEEP_SECRET"
        with self.assertRaises(ImportErrorSafe), patch("builtins.print"):
            configure("NEW_SECRET", store=store, connect=lambda **kwargs: self.fail("Should not connect"))
        self.assertEqual(store.get(COLLECTOR_REFERENCE), "KEEP_SECRET")
        self.assertEqual(store.writes, [])

    def test_failed_login_does_not_write_any_secret(self):
        store = FakeStore()

        def connect(**kwargs):
            raise RuntimeError("password authentication failed SECRET_BOUND_VALUE")

        with self.assertRaises(ImportErrorSafe) as caught:
            configure("SECRET_BOUND_VALUE", store=store, connect=connect)
        self.assertEqual(store.writes, [])
        self.assertNotIn("SECRET_BOUND_VALUE", str(caught.exception))

    def test_wrong_destination_does_not_write(self):
        for identity in (("sentinel_admin", "sentinel", 5433), ("sentinel_collector", "aegis", 5432)):
            store = FakeStore()
            with self.assertRaises(ImportErrorSafe):
                configure("SECRET", store=store, connect=lambda **kwargs: FakeConnection(identity))
            self.assertEqual(store.writes, [])

    def test_windows_identity_is_checked_before_credential_input(self):
        with patch("scripts.database.configure_collector_secret.verify_windows_identity", side_effect=ImportErrorSafe("Wrong account")), patch("scripts.database.configure_collector_secret._read_password") as read, redirect_stderr(io.StringIO()):
            self.assertEqual(main([]), 1)
            read.assert_not_called()

    def test_other_machine_is_refused(self):
        with patch.dict("os.environ", {"COMPUTERNAME": "DEVELOPMENT"}):
            with self.assertRaises(ImportErrorSafe):
                verify_windows_identity()

    def test_cli_uses_dpapi_store_and_does_not_echo_password(self):
        store = FakeStore()
        fake_driver = SimpleNamespace(connect=lambda **kwargs: FakeConnection())
        with patch("scripts.database.configure_collector_secret.verify_windows_identity"), patch("sys.stdin.isatty", return_value=False), patch("scripts.database.configure_collector_secret.JsonSecretStore", return_value=store), patch("scripts.database.configure_collector_secret._read_password", return_value="PRIVATE_PASSWORD"), patch.dict("sys.modules", {"psycopg": fake_driver}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 0)
        self.assertNotIn("PRIVATE_PASSWORD", output.getvalue())
        self.assertTrue(json.loads(output.getvalue())["leitura_dpapi_validada"])


if __name__ == "__main__":
    unittest.main()
