from __future__ import annotations

import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "sofia"
    / "database"
    / "migrations"
    / "001_read_only_foundation.sql"
)
SYNC_MIGRATION = MIGRATION.with_name("002_alert_snapshot_sync.sql")


class SofiaDatabaseSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.sql.lower().split())

    def test_migration_is_transactional_and_versioned(self) -> None:
        self.assertIn("\\set on_error_stop on", self.normalized)
        self.assertIn("begin;", self.normalized)
        self.assertIn("commit;", self.normalized)
        self.assertIn("sofia.schema_migrations", self.normalized)

    def test_runtime_role_cannot_delete_or_mutate_audit(self) -> None:
        runtime_grants = [
            line.strip().lower()
            for line in self.sql.splitlines()
            if "grant " in line.lower() and "sofia_runtime" in line.lower()
        ]
        self.assertTrue(runtime_grants)
        self.assertFalse(any("delete" in line for line in runtime_grants))
        self.assertFalse(
            any(
                "update" in line and "audit_events" in line
                for line in runtime_grants
            )
        )

    def test_schema_does_not_store_prompts_tokens_or_secrets(self) -> None:
        forbidden_columns = (
            "prompt text",
            "response text",
            "access_token",
            "refresh_token",
            "client_secret",
            "password",
        )
        for forbidden in forbidden_columns:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.normalized)

    def test_public_role_is_revoked(self) -> None:
        self.assertIn("revoke all on schema sofia from public", self.normalized)
        self.assertIn("revoke all on all tables in schema sofia from public", self.normalized)

    def test_snapshot_sync_uses_closed_security_definer_function(self) -> None:
        sql = " ".join(SYNC_MIGRATION.read_text(encoding="utf-8").lower().split())
        self.assertIn("security definer", sql)
        self.assertIn("set search_path = pg_catalog, sofia", sql)
        self.assertIn("jsonb_array_length(p_alerts) > 100", sql)
        self.assertIn("revoke all on function", sql)
        self.assertIn("revoke insert on sofia.alert_snapshots", sql)
        self.assertIn("revoke update on sofia.alert_snapshots", sql)
        self.assertNotIn("raw_payload", sql)


if __name__ == "__main__":
    unittest.main()
