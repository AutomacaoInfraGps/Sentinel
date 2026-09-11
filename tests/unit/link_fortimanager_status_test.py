import unittest
from unittest.mock import patch

import web_config


class LinkFortimanagerStatusTest(unittest.TestCase):
    def test_monitor_zabbix_packet_loss_above_ten_is_offline(self):
        sla_data = {"MONITOR_ZABBIX": {"packet_loss": 10.01}}
        status, source = web_config._resolve_link_operational_status("online", "active", sla_data)

        self.assertEqual("offline", status)
        self.assertEqual("monitor_zabbix_packet_loss", source)

    def test_monitor_zabbix_packet_loss_at_ten_is_online(self):
        sla_data = {"MONITOR_ZABBIX": {"packet-loss": "10%"}}
        status, source = web_config._resolve_link_operational_status("offline", "inactive", sla_data)

        self.assertEqual("online", status)
        self.assertEqual("monitor_zabbix_packet_loss", source)

    def test_link_mode_is_fallback_when_monitor_zabbix_is_missing(self):
        status, source = web_config._resolve_link_operational_status("online", "inactive")

        self.assertEqual("online", status)
        self.assertEqual("link_mode", source)

    def test_sla_is_used_when_link_mode_is_unavailable(self):
        status, source = web_config._resolve_link_operational_status("", "inactive")

        self.assertEqual("offline", status)
        self.assertEqual("sla", source)

    @patch.object(web_config, "_list_fortimanager_devices")
    @patch.object(web_config, "_get_cached_fortimanager_device")
    def test_regional_cache_supplies_exact_device_name(self, cached_device, live_devices):
        live_devices.return_value = [{"name": "FGT_CONTROL_MCO", "ip": "10.0.0.99"}]
        cached_device.return_value = {
            "name": "FGT_CONTROL_MCO",
            "ip": "10.253.3.54",
            "status": "online",
        }
        regional = {"links": [{"fortigate_host": "10.253.3.54"}]}

        result = web_config._get_gerenciador_fortigate_regional("REG_CONTROL_MCO", regional)

        self.assertEqual("FGT_CONTROL_MCO", result["device"]["name"])
        self.assertEqual("10.253.3.54", result["device"]["ip"])


if __name__ == "__main__":
    unittest.main()
