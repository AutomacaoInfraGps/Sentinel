import os
import tempfile
import time
import unittest
from unittest.mock import patch

from sofia.service_auth import build_signature
from web_config import app


class SofiaServiceAuthenticationTest(unittest.TestCase):
    PATH = "/api/internal/sofia/v1/health"
    KEY_ID = "n8n-celeno-v1"
    SECRET = "test-secret-with-at-least-thirty-two-bytes-123456789"

    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "SENTINEL_N8N_KEY_ID": self.KEY_ID,
                "SENTINEL_N8N_HMAC_SECRET": self.SECRET,
                "SENTINEL_N8N_ALLOWED_NETWORKS": "127.0.0.1/32",
                "SENTINEL_N8N_NONCE_DB": os.path.join(
                    self.temp_dir.name,
                    "nonces.sqlite3",
                ),
                "SENTINEL_N8N_MAX_CLOCK_SKEW_SECONDS": "60",
            },
            clear=False,
        )
        self.environment.start()
        self.audit = patch("sofia.service_auth.registrar_evento_sofia")
        self.audit.start()

    def tearDown(self):
        self.audit.stop()
        self.environment.stop()
        self.temp_dir.cleanup()

    def _headers(self, *, nonce="unique-service-nonce-0001", timestamp=None, secret=None):
        timestamp = str(timestamp if timestamp is not None else int(time.time()))
        signature = build_signature(
            secret or self.SECRET,
            "GET",
            self.PATH,
            timestamp,
            nonce,
            b"",
        )
        return {
            "X-Sentinel-Key-Id": self.KEY_ID,
            "X-Sentinel-Timestamp": timestamp,
            "X-Sentinel-Nonce": nonce,
            "X-Sentinel-Signature": signature,
        }

    def test_unsigned_request_is_rejected_without_login_redirect(self):
        response = self.client.get(self.PATH)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["success"], False)

    def test_valid_signed_request_returns_only_minimal_health_data(self):
        response = self.client.get(self.PATH, headers=self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "status": "ok",
                "service": "sentinel",
                "mode": "read-only",
                "api_version": "v1",
            },
        )

    def test_wrong_signature_is_rejected(self):
        response = self.client.get(
            self.PATH,
            headers=self._headers(secret="different-secret-with-at-least-32-bytes"),
        )
        self.assertEqual(response.status_code, 401)

    def test_expired_request_is_rejected(self):
        response = self.client.get(
            self.PATH,
            headers=self._headers(timestamp=int(time.time()) - 120),
        )
        self.assertEqual(response.status_code, 401)

    def test_replayed_nonce_is_rejected(self):
        headers = self._headers(nonce="unique-service-nonce-replay")
        self.assertEqual(self.client.get(self.PATH, headers=headers).status_code, 200)
        self.assertEqual(self.client.get(self.PATH, headers=headers).status_code, 401)

    def test_request_from_unapproved_ip_is_rejected(self):
        response = self.client.get(
            self.PATH,
            headers=self._headers(nonce="unique-service-nonce-other-ip"),
            environ_base={"REMOTE_ADDR": "10.254.12.99"},
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_server_secret_fails_closed(self):
        with patch.dict(os.environ, {"SENTINEL_N8N_HMAC_SECRET": ""}):
            response = self.client.get(
                self.PATH,
                headers=self._headers(nonce="unique-service-nonce-no-secret"),
            )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
