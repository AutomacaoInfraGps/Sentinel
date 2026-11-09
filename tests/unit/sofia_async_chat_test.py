from pathlib import Path
from threading import Event, Thread
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from sofia import chat_requests
from tests.unit.sofia_page_test import ChatUser, create_preview_app


class SofiaAsyncChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_preview_app()
        self.app.config["SOFIA_REQUEST_DB"] = str(Path(self.temp.name) / "requests.sqlite3")
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = ChatUser.id
            session["_fresh"] = True
        self.payload = {"message": "Quais APs?", "conversation_id": str(uuid.uuid4()),
                        "request_id": str(uuid.uuid4()), "async": True}
        self.headers = {"X-Sentinel-Request": "sofia-chat"}
        self.workers = []

        def worker_factory(**kwargs):
            worker = Thread(**kwargs)
            self.workers.append(worker)
            return worker

        worker_patch = patch("sofia.routes.Thread", side_effect=worker_factory)
        worker_patch.start()
        self.addCleanup(worker_patch.stop)
        self.patches = []
        for target, value in [("usuario_pode_executar", True), ("registrar_evento_sofia", None),
                              ("codigos_regionais", ["REG_ARARAS"]),
                              ("access_scope", {"allowed": {"REG_ARARAS"}}),
                              ("issue_regional_scope_token", "test-scope")]:
            patcher = patch("sofia.routes." + target, return_value=value)
            self.patches.append(patcher.start())
            self.addCleanup(patcher.stop)
        self.addCleanup(self.join_workers)

    def join_workers(self):
        for worker in self.workers:
            worker.join(6)
            self.assertFalse(worker.is_alive(), "Worker did not finish")

    def submit(self, **changes):
        return self.client.post("/api/sofia/chat", json={**self.payload, **changes}, headers=self.headers)

    def poll(self, **changes):
        return self.client.get("/api/sofia/chat/requests/" + self.payload["request_id"],
            query_string={"conversation_id": self.payload["conversation_id"], **changes}, headers=self.headers)

    def wait_for_terminal(self):
        for _ in range(100):
            response = self.poll()
            if response.status_code != 202:
                self.join_workers()
                return response
            time.sleep(0.02)
        self.fail("Worker did not finish")

    def test_submission_returns_while_model_runs_then_poll_gets_reply(self):
        release = Event()
        started = Event()

        def query(**kwargs):
            self.assertEqual(kwargs["read_timeout"], 480)
            started.set()
            release.wait(5)
            return "Há 1 AP offline."

        with patch("sofia.routes.consultar_sofia", side_effect=query) as model:
            try:
                self.assertEqual(self.submit().status_code, 202)
                self.assertTrue(started.wait(2))
                self.assertEqual(self.poll().status_code, 202)
                self.assertEqual(self.submit().status_code, 202)
                self.assertEqual(model.call_count, 1)
                self.assertEqual(self.submit(message="Outra mensagem").status_code, 409)
            finally:
                release.set()
            result = self.wait_for_terminal()
        self.assertEqual(result.status_code, 200)
        self.assertIn("1 AP", result.json["reply"])
        self.assertIn("no-store", result.headers["Cache-Control"])

    def test_result_requires_same_owner_conversation_and_current_scope(self):
        with patch("sofia.routes.consultar_sofia", return_value="PRIVATE_REPLY"):
            self.submit()
            self.wait_for_terminal()
        self.assertEqual(self.poll(conversation_id=str(uuid.uuid4())).status_code, 404)
        with patch("sofia.routes.access_scope", return_value={"allowed": {"REG_FORA"}}):
            denied = self.poll()
        self.assertEqual(denied.status_code, 404)
        with self.app.app_context():
            # Ownership is enforced independently of the scope digest.
            with chat_requests._database() as db:
                db.execute("UPDATE chat_requests SET owner='other-user'")
        self.assertEqual(self.poll().status_code, 404)

    def test_stop_wins_over_late_worker_reply(self):
        release = Event()
        with patch("sofia.routes.consultar_sofia", side_effect=lambda **kw: (release.wait(5), "LATE_REPLY")[1]):
            self.assertEqual(self.submit().status_code, 202)
            with self.app.app_context():
                chat_requests.cancel(self.payload["request_id"], ChatUser.id)
            release.set()
            self.join_workers()
            polled = self.poll()
        self.assertTrue(polled.json["cancelled"])
        self.assertNotIn("LATE_REPLY", polled.get_data(as_text=True))

    def test_worker_failure_is_an_error_not_zero_records(self):
        with patch("sofia.routes.consultar_sofia", side_effect=RuntimeError("PRIVATE_SECRET")):
            self.assertEqual(self.submit().status_code, 202)
            result = self.wait_for_terminal()
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("PRIVATE_SECRET", result.get_data(as_text=True))

    def test_poll_requires_authentication_and_permissions(self):
        with patch("sofia.routes.usuario_pode_executar", return_value=False):
            self.assertEqual(self.poll().status_code, 403)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.poll().status_code, 401)
