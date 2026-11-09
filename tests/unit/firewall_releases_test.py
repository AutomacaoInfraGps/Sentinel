import unittest
from datetime import datetime, timezone

from services import firewall_releases as module


class ReleaseTests(unittest.TestCase):
    def payload(self):
        return {
            "result": [{
                "data": {
                    "status": "success",
                    "version_list": [{
                        "platform": "FortiGate-60F",
                        "versions": [
                            {"type": "GA", "version": "7.0.0-b0001"},
                            {"type": "GA", "version": "7.1.0-b0002"},
                            {"type": "GA", "version": "8.0.2-b0251"},
                            {"type": "SPECIAL", "version": "7.9.9-b9999"},
                        ],
                    }],
                },
                "status": {"code": 0, "message": "OK"},
            }],
        }

    def test_catalog_reads_only_ga_releases_by_model(self):
        catalog = module.catalog_from_fortimanager(self.payload())

        self.assertEqual(catalog, {"FG-60F": [(7, 0, 0), (7, 1, 0), (8, 0, 2)]})

    def test_update_rule_stays_within_installed_major_family(self):
        checked = datetime(2026, 11, 9, 12, 30, tzinfo=timezone.utc)
        cases = [
            ([(7, 0, 0), (7, 1, 0)], "update", "7.1.0"),
            ([(7, 0, 0), (7, 1, 0), (8, 0, 0)], "update", "7.1.0"),
            ([(7, 0, 0), (8, 0, 0)], "current", None),
            ([(7, 0, 0)], "current", None),
        ]
        for releases, state, available in cases:
            with self.subTest(releases=releases):
                result = module.assess({"FG-60F": releases}, "FortiGate-60F", "7.0.0", checked)
                self.assertEqual(result["state"], state)
                self.assertEqual(result.get("available_version"), available)
                if available:
                    self.assertIn(f"/{available}/", result["url"])

    def test_missing_catalog_model_or_firmware_is_unknown(self):
        catalog = module.catalog_from_fortimanager(self.payload())
        for data, hardware, firmware in [
            (None, "FortiGate-60F", "7.0.0"),
            (catalog, "FortiGate-80F", "7.0.0"),
            (catalog, "FortiGate-60F", "N/A"),
        ]:
            with self.subTest(hardware=hardware, firmware=firmware):
                self.assertEqual(module.assess(data, hardware, firmware)["state"], "unknown")

    def test_invalid_fortimanager_response_is_unavailable(self):
        for payload in [{}, {"result": []}, {"result": [{"data": {"status": "failed"}}]}]:
            with self.subTest(payload=payload):
                self.assertIsNone(module.catalog_from_fortimanager(payload))

    def test_formats_build_for_display(self):
        self.assertEqual(module.format_firmware("v7.4.13, build2933"), "v7.4.13, Build 2933")


if __name__ == "__main__":
    unittest.main()
