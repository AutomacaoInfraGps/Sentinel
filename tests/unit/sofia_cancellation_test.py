import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import Mock, patch

from sofia import chat_requests
from sofia.execution_control import cancellation_diagnostics, stop_execution
from sofia.n8n_client import SofiaN8nError
from sofia.service_auth import build_signature
from sofia.service_routes import sofia_service_bp
from security_hardening import configure_security
from tests.unit.sofia_page_test import ChatUser, create_preview_app


class SofiaCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_preview_app()
        self.app.config["SOFIA_REQUEST_DB"] = str(Path(self.temp.name) / "requests.db")
        self.app.register_blueprint(sofia_service_bp)
        self.client = self.app.test_client()
        self.request_id = str(uuid.uuid4())
        self.environment = patch.dict(os.environ, {
            "SENTINEL_SOFIA_N8N_WEBHOOK_URL": "http://127.0.0.1:15678/webhook/sofia",
            "SENTINEL_SOFIA_N8N_API_URL": "http://127.0.0.1:15678/api/v1",
            "SENTINEL_SOFIA_N8N_API_KEY": "test-key-" * 8,
            "SENTINEL_SOFIA_N8N_WORKFLOW_ID": "sofia-workflow",
            "SENTINEL_N8N_KEY_ID": "n8n-test",
            "SENTINEL_N8N_HMAC_SECRET": "test-hmac-" * 8,
            "SENTINEL_N8N_ALLOWED_NETWORKS": "127.0.0.1/32",
            "SENTINEL_N8N_NONCE_DB": str(Path(self.temp.name) / "nonces.db"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for target in ["sofia.routes.registrar_evento_sofia", "sofia.service_auth.registrar_evento_sofia"]:
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.permission = patch("sofia.routes.usuario_pode_executar", return_value=True)
        self.permission.start()
        self.addCleanup(self.permission.stop)
        self.headers = {"X-Sentinel-Request": "sofia-chat"}
        self.authenticate()

    def authenticate(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = ChatUser.id
            session["_fresh"] = True

    def reserve(self, owner=ChatUser.id):
        with self.app.app_context():
            chat_requests.begin(self.request_id, owner)
            chat_requests.register_execution(self.request_id, "42")

    def cancel(self, **kwargs):
        return self.client.post("/api/sofia/chat/cancel", json={"request_id": self.request_id},
                                headers=kwargs.pop("headers", self.headers), **kwargs)

    def test_requires_login_origin_and_valid_identifier(self):
        self.assertEqual(self.cancel(headers={}).status_code, 403)
        self.assertEqual(self.cancel(headers={**self.headers, "Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/api/sofia/chat/cancel", headers=self.headers,
                         json={"request_id": "42"}).status_code, 400)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.cancel().status_code, 401)

    def test_permission_denied_cannot_cancel(self):
        self.permission.stop()
        with patch("sofia.routes.usuario_pode_executar", return_value=False):
            self.assertEqual(self.cancel().status_code, 403)

    @patch("sofia.routes.stop_execution", return_value=True)
    def test_only_owner_can_stop_the_registered_execution(self, stop):
        self.reserve(owner="another-user")
        self.assertEqual(self.cancel().status_code, 404)
        stop.assert_not_called()

    @patch("sofia.routes.stop_execution", return_value=True)
    def test_confirms_only_after_n8n_confirmation_and_is_idempotent(self, stop):
        self.reserve()
        self.assertTrue(self.cancel().json["cancelled"])
        self.assertTrue(self.cancel().json["cancelled"])
        stop.assert_called_once_with("42")

    @patch("sofia.routes.stop_execution", side_effect=SofiaN8nError("not configured"))
    def test_failed_stop_is_not_reported_as_success(self, stop):
        self.reserve()
        result = self.cancel().json
        self.assertFalse(result["cancelled"])
        self.assertIn("Nao foi possivel confirmar", result["message"])

    def test_stop_before_send_prevents_late_chat_start(self):
        self.assertTrue(self.cancel().json["cancelled"])
        with self.app.app_context():
            self.assertFalse(chat_requests.begin(self.request_id, ChatUser.id))

    def test_cancel_keeps_csrf_protection(self):
        configure_security(self.app, Path(self.temp.name))
        self.authenticate()
        self.assertEqual(self.cancel().status_code, 400)
        with self.client.session_transaction() as session:
            session["_csrf_token"] = "c" * 64
        self.assertTrue(self.cancel(headers={**self.headers, "X-CSRF-Token": "c" * 64}).json["cancelled"])

    def test_chat_forwards_request_id_and_discards_cancelled_reply(self):
        def delayed_reply(**kwargs):
            self.assertEqual(kwargs["request_id"], self.request_id)
            chat_requests.cancel(self.request_id, ChatUser.id)
            return "RESPOSTA ANTIGA"

        with patch("sofia.routes.codigos_regionais", return_value=["REG_ABC"]), \
             patch("sofia.routes.access_scope", return_value={"allowed": {"REG_ABC"}}), \
             patch("sofia.routes.issue_regional_scope_token", return_value="test-scope"), \
             patch("sofia.routes.consultar_sofia", side_effect=delayed_reply):
            result = self.client.post("/api/sofia/chat", headers=self.headers, json={
                "message": "Teste", "conversation_id": str(uuid.uuid4()), "request_id": self.request_id,
            })
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["cancelled"])
        self.assertNotIn("RESPOSTA ANTIGA", result.get_data(as_text=True))

    def test_registry_rejects_duplicate_start_and_execution_rebinding(self):
        self.reserve()
        with self.app.app_context():
            with self.assertRaises(ValueError):
                chat_requests.begin(self.request_id, ChatUser.id)
            self.assertFalse(chat_requests.register_execution(self.request_id, "99"))

    def register(self, **overrides):
        path = "/api/internal/sofia/v1/executions/register"
        body = json.dumps({"request_id": self.request_id, "execution_id": "42",
                           "workflow_id": "sofia-workflow", **overrides}).encode()
        timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
        return self.client.post(path, data=body, content_type="application/json", headers={
            "X-Sentinel-Key-Id": "n8n-test", "X-Sentinel-Timestamp": timestamp,
            "X-Sentinel-Nonce": nonce,
            "X-Sentinel-Signature": build_signature("test-hmac-" * 8, "POST", path, timestamp, nonce, body),
        })

    def test_registration_requires_service_hmac_and_existing_request(self):
        result = self.client.post("/api/internal/sofia/v1/executions/register", json={})
        self.assertEqual(result.status_code, 401)
        self.assertEqual(self.register().status_code, 409)
        with self.app.app_context():
            chat_requests.begin(self.request_id, ChatUser.id)
        self.assertEqual(self.register(workflow_id="other-workflow").status_code, 403)
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(self.register(execution_id="99").status_code, 409)

    @patch("sofia.service_routes.stop_execution", return_value=True)
    def test_registration_after_stop_handles_the_race(self, stop):
        with self.app.app_context():
            chat_requests.begin(self.request_id, ChatUser.id)
            chat_requests.cancel(self.request_id, ChatUser.id)
        self.assertTrue(self.register().json["cancelled"])
        stop.assert_called_once_with("42")

    @patch("sofia.execution_control.requests.post")
    @patch("sofia.execution_control.requests.get")
    def test_api_cannot_stop_another_workflow(self, get, post):
        get.return_value = Mock(status_code=200, json=lambda: {"workflowId": "another", "status": "running"})
        with self.assertRaises(SofiaN8nError):
            stop_execution("42")
        post.assert_not_called()

    @patch("sofia.execution_control.requests.post")
    @patch("sofia.execution_control.requests.get")
    def test_finished_execution_is_not_restarted_or_stopped(self, get, post):
        get.return_value = Mock(status_code=200, json=lambda: {"workflowId": "sofia-workflow", "status": "success"})
        self.assertFalse(stop_execution("42"))
        post.assert_not_called()

    @patch("sofia.execution_control.requests.get")
    def test_missing_api_key_is_not_treated_as_cancellation(self, get):
        with patch.dict(os.environ, {"SENTINEL_SOFIA_N8N_API_KEY": ""}):
            with self.assertRaises(SofiaN8nError):
                stop_execution("42")
        get.assert_not_called()

    @patch("sofia.execution_control.requests.post")
    @patch("sofia.execution_control.requests.get")
    def test_diagnostics_never_stops_or_exposes_credentials(self, get, post):
        get.return_value = Mock(status_code=200, json=lambda: {
            "workflowId": "sofia-workflow", "status": "running", "data": {"secret": "do-not-print"},
        })
        result = cancellation_diagnostics("42")
        self.assertTrue(result["workflow_matches"])
        self.assertEqual(result["execution_status"], "running")
        self.assertNotIn("test-key-", json.dumps(result))
        self.assertNotIn("do-not-print", json.dumps(result))
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        post.assert_not_called()

    @patch("sofia.execution_control.requests.get")
    def test_diagnostics_reports_missing_key_without_network(self, get):
        with patch.dict(os.environ, {"SENTINEL_SOFIA_N8N_API_KEY": ""}):
            result = cancellation_diagnostics("42")
        self.assertFalse(result["api_key_configured"])
        self.assertFalse(result["configuration_valid"])
        get.assert_not_called()

    @patch("sofia.execution_control.requests.post")
    @patch("sofia.execution_control.requests.get")
    def test_diagnostics_reports_authentication_failure_without_response_body(self, get, post):
        get.return_value = Mock(status_code=401, text="private details")
        result = cancellation_diagnostics("42")
        self.assertEqual(result["http_status"], 401)
        self.assertNotIn("private details", json.dumps(result))
        post.assert_not_called()

    @patch("sofia.execution_control.requests.post")
    @patch("sofia.execution_control.requests.get")
    def test_api_verifies_status_after_stop(self, get, post):
        get.return_value = Mock(status_code=200, json=lambda: {"workflowId": "sofia-workflow", "status": "running"})
        post.return_value = Mock(status_code=200, json=lambda: {"status": "running"})
        self.assertFalse(stop_execution("42"))
        post.return_value = Mock(status_code=200, json=lambda: {"status": "canceled"})
        self.assertTrue(stop_execution("42"))
        self.assertTrue(post.call_args.args[0].endswith("/executions/42/stop"))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    @patch("sofia.execution_control.requests.get")
    def test_api_rejects_invalid_ids_and_non_local_plain_http(self, get):
        for identifier in ["../1", "0", "42/stop", "", "-1"]:
            with self.assertRaises(ValueError):
                stop_execution(identifier)
        with patch.dict(os.environ, {"SENTINEL_SOFIA_N8N_API_URL": "http://10.0.0.1/api/v1"}):
            with self.assertRaises(SofiaN8nError):
                stop_execution("42")
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
