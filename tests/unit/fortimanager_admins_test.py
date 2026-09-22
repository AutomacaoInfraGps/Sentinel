import unittest
from unittest.mock import Mock

from fortimanager_client import FortiManagerClient, FortiManagerClientError


class FortiManagerAdminsTests(unittest.TestCase):
    def test_reads_vpn_comments_from_device_database(self):
        client = FortiManagerClient(host="fortimanager.local", api_key="test")
        client._request = Mock(return_value={
            "result": [{
                "data": [
                    {"name": "T001_PR_01", "comments": "REG_PARANA"},
                    {"name": "T002_SEM_COMENTARIO"},
                ],
            }],
        })

        comments = client.get_vpn_phase1_comments("FTG_GLX_100F_MATRIZ")

        self.assertEqual(comments, {"T001_PR_01": "REG_PARANA"})

    def _client_with_payload(self, payload):
        client = FortiManagerClient(host="fortimanager.local", api_key="test")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        client.session.post = Mock(return_value=response)
        return client

    def test_missing_result_is_not_treated_as_empty_admin_list(self):
        client = self._client_with_payload({"result": []})

        with self.assertRaises(FortiManagerClientError):
            client.get_fortigate_admins("FGT_TESTE", "GPS_UNIDADES")

    def test_proxy_error_is_not_treated_as_empty_admin_list(self):
        client = self._client_with_payload({
            "result": [{
                "status": {"code": 0},
                "data": [{"status": {"code": -11, "message": "No permission"}}],
            }]
        })

        with self.assertRaises(FortiManagerClientError):
            client.get_fortigate_admins("FGT_TESTE", "GPS_UNIDADES")

    def test_successful_response_returns_admin_names(self):
        client = self._client_with_payload({
            "result": [{
                "status": {"code": 0},
                "data": [{
                    "status": {"code": 0},
                    "response": {
                        "http_status": 200,
                        "status": "success",
                        "results": [{"name": "admin"}, {"name": "admin.santos"}],
                    },
                }],
            }]
        })

        self.assertEqual(
            client.get_fortigate_admins("FGT_TESTE", "GPS_UNIDADES"),
            ["admin", "admin.santos"],
        )


if __name__ == "__main__":
    unittest.main()
