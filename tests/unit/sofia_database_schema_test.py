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
READ_MIGRATION = MIGRATION.with_name("003_alert_read_api.sql")
MAP_ALIGNMENT_MIGRATION = MIGRATION.with_name("004_map_alert_alignment.sql")


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

    def test_alert_reads_use_closed_bounded_functions(self) -> None:
        sql = " ".join(READ_MIGRATION.read_text(encoding="utf-8").lower().split())
        self.assertIn("sofia.get_alert_summary", sql)
        self.assertIn("sofia.list_active_alerts", sql)
        self.assertEqual(sql.count("security definer"), 2)
        self.assertEqual(sql.count("set search_path = pg_catalog, sofia"), 2)
        self.assertIn("p_limit < 1 or p_limit > 50", sql)
        self.assertIn("revoke select on sofia.alert_snapshots", sql)
        self.assertIn("revoke all on function", sql)
        self.assertNotIn("source_alert_id", sql)
        self.assertNotIn("content_sha256", sql)

    def test_map_alignment_sums_quantities_and_preserves_closed_access(self) -> None:
        sql = " ".join(MAP_ALIGNMENT_MIGRATION.read_text(encoding="utf-8").lower().split())
        self.assertIn("add column if not exists quantity", sql)
        self.assertIn("sum(snapshot.quantity)", sql)
        self.assertIn("last_observed_at_brasilia text", sql)
        self.assertIn("at time zone 'america/sao_paulo'", sql)
        self.assertIn("'high'", sql)
        self.assertIn("'medium'", sql)
        self.assertIn("'attention'", sql)
        self.assertIn("revoke select, insert, delete on sofia.alert_snapshots", sql)
        self.assertIn("revoke update on sofia.alert_snapshots", sql)
        self.assertIn("revoke update ( severity, title, regional, device", sql)


if __name__ == "__main__":
    unittest.main()
