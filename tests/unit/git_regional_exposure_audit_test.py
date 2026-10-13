import unittest

from scripts.security.audit_git_regional_exposure import (
    ServerIdentity,
    _server_credentials,
    find_affected_current_servers,
)


class GitRegionalExposureAuditTests(unittest.TestCase):
    def test_reports_identity_without_returning_secret(self):
        payload = {
            "regionais": {
                "REG_TESTE": {
                    "servidores": [
                        {"id": "server-01", "senha": "synthetic-exposed"},
                        {"id": "server-02", "senha": "synthetic-safe"},
                    ]
                }
            }
        }

        affected = find_affected_current_servers(
            payload, {"synthetic-exposed"}
        )

        self.assertEqual(
            affected, [ServerIdentity("REG_TESTE", "server-01")]
        )
        self.assertNotIn("synthetic-exposed", repr(affected))

    def test_ignores_empty_and_reference_values(self):
        payload = {
            "regionais": {
                "REG_TESTE": {
                    "servidores": [
                        {"id": "empty", "senha": ""},
                        {
                            "id": "reference",
                            "senha": {"credential_ref": "regional/test/senha"},
                        },
                    ]
                }
            }
        }

        self.assertEqual(_server_credentials(payload), [])


if __name__ == "__main__":
    unittest.main()
