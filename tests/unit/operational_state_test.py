import json
import tempfile
import unittest
from pathlib import Path

from operational_state import publish_map_snapshot, records_for


class OperationalStateTest(unittest.TestCase):
    def test_preserves_changed_at_for_unchanged_device(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            first = {"regionais": [{"codigo": "REG_A", "switches": [{"ip": "10.0.0.1", "status": "online"}]}]}
            second = {"regionais": [{"codigo": "REG_A", "switches": [{"ip": "10.0.0.1", "status": "online"}]}]}

            publish_map_snapshot(first, path=path, collected_at="2026-08-28T08:00:00")
            publish_map_snapshot(second, path=path, collected_at="2026-08-28T08:05:00")

            switch = records_for("switches", path=path)[0]
            self.assertEqual(switch["updated_at"], "2026-08-28T08:05:00")
            self.assertEqual(switch["changed_at"], "2026-08-28T08:00:00")

    def test_updates_changed_at_and_removes_missing_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            publish_map_snapshot({
                "regionais": [{
                    "codigo": "REG_A",
                    "aps": [
                        {"ip": "10.0.0.1", "status": "online"},
                        {"ip": "10.0.0.2", "status": "maintenance"},
                    ],
                }]
            }, path=path, collected_at="2026-08-28T08:00:00")
            publish_map_snapshot({
                "regionais": [{
                    "codigo": "REG_A",
                    "aps": [{"ip": "10.0.0.1", "status": "offline"}],
                }]
            }, path=path, collected_at="2026-08-28T08:05:00")

            aps = records_for("aps", path=path)
            self.assertEqual(len(aps), 1)
            self.assertEqual(aps[0]["status"], "offline")
            self.assertEqual(aps[0]["changed_at"], "2026-08-28T08:05:00")
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
