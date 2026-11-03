from __future__ import annotations

import unittest

from flask import Flask

from sofia.memory_scope import SofiaMemoryScopeError, derive_memory_session_id


class SofiaMemoryScopeTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = "test-memory-secret"
        self.conversation_id = "12345678-1234-4234-9234-123456789abc"

    def _derive(self, user, conversation_id=None, allowed_regionals=None):
        with self.app.app_context():
            return derive_memory_session_id(
                user,
                conversation_id or self.conversation_id,
                allowed_regionals or {"REG_ABC", "REG_BAHIA"},
            )

    def test_key_is_stable_opaque_and_bounded(self):
        first = self._derive("GALAXIA\\Roosevelt")
        second = self._derive("galaxia\\roosevelt")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn("roosevelt", first)
        self.assertNotIn("12345678", first)

    def test_same_conversation_is_isolated_between_users(self):
        self.assertNotEqual(
            self._derive("galaxia\\roosevelt"),
            self._derive("galaxia\\outro.usuario"),
        )

    def test_scope_order_is_stable_but_access_change_rotates_key(self):
        first = self._derive(
            "galaxia\\roosevelt",
            allowed_regionals=["REG_BAHIA", "REG_ABC"],
        )
        reordered = self._derive(
            "galaxia\\roosevelt",
            allowed_regionals=["REG_ABC", "REG_BAHIA"],
        )
        reduced = self._derive(
            "galaxia\\roosevelt",
            allowed_regionals=["REG_ABC"],
        )

        self.assertEqual(first, reordered)
        self.assertNotEqual(first, reduced)

    def test_invalid_conversation_is_rejected(self):
        with self.assertRaises(SofiaMemoryScopeError):
            self._derive("galaxia\\roosevelt", "not-a-uuid")

    def test_missing_secret_fails_closed(self):
        self.app.config["SECRET_KEY"] = ""
        with self.assertRaises(SofiaMemoryScopeError):
            self._derive("galaxia\\roosevelt")

    def test_empty_access_scope_fails_closed(self):
        with self.app.app_context(), self.assertRaises(SofiaMemoryScopeError):
            derive_memory_session_id(
                "galaxia\\roosevelt",
                self.conversation_id,
                set(),
            )


if __name__ == "__main__":
    unittest.main()
