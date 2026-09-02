import unittest

from maintenance_status import (
    apply_device_maintenance,
    apply_zabbix_maintenance,
    is_device_in_maintenance,
    normalize_ip,
)


class MaintenanceStatusTests(unittest.TestCase):
    def test_overrides_offline_by_ip(self):
        data = {"aps": [{"nome": "AP-01", "ip": "10.0.0.10", "status": "offline"}]}
        hosts = [{"hostid": "7", "name": "AP-01", "ip": "10.0.0.10", "maintenanceid": "3"}]

        result = apply_zabbix_maintenance(data, hosts)

        self.assertEqual(result["aps"][0]["status"], "maintenance")
        self.assertEqual(result["aps"][0]["status_controladora"], "offline")
        self.assertTrue(result["aps"][0]["em_manutencao"])
        self.assertEqual(result["aps_offline"], 0)
        self.assertEqual(result["aps_maintenance"], 1)
        self.assertEqual(data["aps"][0]["status"], "offline")

    def test_preserves_unmatched_ap(self):
        data = {"aps": [{"ip": "10.0.0.11", "status": "offline"}]}

        result = apply_zabbix_maintenance(data, [{"ip": "10.0.0.12"}])

        self.assertEqual(result["aps"][0]["status"], "offline")
        self.assertFalse(result["aps"][0]["em_manutencao"])
        self.assertEqual(result["aps_offline"], 1)

    def test_does_not_override_online_ap_in_group_maintenance(self):
        data = {"aps": [{"ip": "10.0.0.13", "status": "online"}]}
        result = apply_zabbix_maintenance(data, [{"ip": "10.0.0.13", "maintenanceid": "444"}])

        self.assertEqual(result["aps"][0]["status"], "online")
        self.assertFalse(result["aps"][0]["em_manutencao"])
        self.assertEqual(result["aps_maintenance"], 0)

    def test_clears_stale_maintenance_from_online_ap(self):
        data = {"aps": [{
            "ip": "10.0.0.14",
            "status": "maintenance",
            "status_controladora": "online",
            "em_manutencao": True,
            "maintenanceid": "444",
        }]}
        result = apply_zabbix_maintenance(data, [{"ip": "10.0.0.14", "maintenanceid": "444"}])

        self.assertEqual(result["aps"][0]["status"], "online")
        self.assertFalse(result["aps"][0]["em_manutencao"])
        self.assertNotIn("maintenanceid", result["aps"][0])

    def test_normalize_ip_rejects_non_ip_values(self):
        self.assertEqual(normalize_ip(" 10.0.0.1 "), "10.0.0.1")
        self.assertEqual(normalize_ip("ap.example.local"), "")

    def test_maintenance_flag_has_priority_over_stale_offline_status(self):
        self.assertTrue(is_device_in_maintenance({"status": "offline", "em_manutencao": True}))

    def test_applies_maintenance_to_offline_server(self):
        devices = [{"nome": "SRV-01", "ip": "10.0.0.20", "status": "offline"}]
        result = apply_device_maintenance(devices, [{"ip": "10.0.0.20", "maintenanceid": "10"}])

        self.assertEqual(result[0]["status"], "maintenance")
        self.assertTrue(result[0]["em_manutencao"])

    def test_applies_maintenance_to_offline_firewall_availability(self):
        devices = [{"nome": "FW-01", "ip": "10.0.0.30", "status_disponibilidade": "offline"}]
        result = apply_device_maintenance(
            devices, [{"ip": "10.0.0.30", "maintenanceid": "11"}], "status_disponibilidade"
        )

        self.assertEqual(result[0]["status_disponibilidade"], "maintenance")
        self.assertEqual(result[0]["status"], "maintenance")

    def test_keeps_online_device_online(self):
        devices = [{"ip": "10.0.0.40", "status": "online"}]
        result = apply_device_maintenance(devices, [{"ip": "10.0.0.40", "maintenanceid": "12"}])

        self.assertEqual(result[0]["status"], "online")
        self.assertFalse(result[0]["em_manutencao"])


if __name__ == "__main__":
    unittest.main()
