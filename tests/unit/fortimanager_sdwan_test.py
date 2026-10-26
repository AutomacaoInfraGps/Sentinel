import unittest
from unittest.mock import Mock

from fortimanager_client import FortiManagerClient


class FortiManagerSdwanTest(unittest.TestCase):
    def test_reuses_working_monitor_endpoint_without_removing_fallbacks(self):
        client = FortiManagerClient(host="fortimanager.local", api_key="test")
        preferred = "/api/v2/monitor/sdwan/status"
        client._preferred_sdwan_monitor_resource = preferred
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "result": [{
                "status": {"code": 0},
                "data": [{
                    "status": {"code": 0},
                    "response": {
                        "results": {
                            "WAN1": {"interface": "WAN1", "status": "up"},
                        },
                    },
                }],
            }],
        }
        client.session.post = Mock(return_value=response)

        result = client.proxy_monitor_sdwan("root", "FGT_TESTE")

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], preferred)
        self.assertEqual(result["mapping"], {"WAN1": "active"})
        payload = client.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["params"][0]["data"]["resource"], preferred)
        client.session.post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
