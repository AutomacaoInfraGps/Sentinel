import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sofia.map_alerts import load_map_alert_snapshot


class SofiaMapAlertsTest(unittest.TestCase):
    def test_uses_the_same_aggregate_counts_as_the_map(self):
        payload = {
            "cache_atualizado_em": "2026-10-09T07:40:32",
            "cache_ttl_segundos": 300,
            "regionais": [
                {
                    "codigo": "REG_UBERLANDIA",
                    "ultima_atualizacao_mapa": "2026-10-09T07:40:30",
                    "alertas": [
                        {"tipo": "vpns", "quantidade": 2, "severidade": "alto", "descricao": "vpns offline"},
                    ],
                },
                {
                    "codigo": "REG_TRADETALENTOS",
                    "alertas": [
                        {"tipo": "aps", "quantidade": 10, "severidade": "medio", "descricao": "aps offline"},
                        {"tipo": "firewalls", "quantidade": 5, "severidade": "atencao", "descricao": "licencas a vencer"},
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "map.json"
            cache.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = load_map_alert_snapshot(
                cache,
                now=datetime(2026, 10, 9, 10, 41, tzinfo=timezone.utc),
            )

        self.assertEqual(
            snapshot["summary"],
            {"critical": 0, "high": 2, "medium": 10, "attention": 5, "total": 17},
        )
        self.assertEqual(snapshot["updated_at_brasilia"], "2026-10-09T07:40:32-03:00")
        self.assertTrue(snapshot["fresh"])
        self.assertEqual([item["quantity"] for item in snapshot["alerts"]], [2, 10, 5])
        self.assertTrue(all(
            item["occurred_at"] == "2026-10-09T07:40:32-03:00"
            for item in snapshot["alerts"]
        ))


if __name__ == "__main__":
    unittest.main()
