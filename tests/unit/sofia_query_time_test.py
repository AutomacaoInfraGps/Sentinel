import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from sofia.chat_requests import query_time_context, record_answered_message


class SofiaQueryTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__)
        self.app.config["SOFIA_REQUEST_DB"] = str(Path(self.temp.name) / "requests.db")
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)

    def test_new_conversation_does_not_invent_previous_time(self):
        first = query_time_context("user-a", "scope-a")
        self.assertIsNone(first["previous_answered_message_started_at"])
        # Merely starting/reading a message must not advance the cursor.
        self.assertIsNone(query_time_context("user-a", "scope-a")["previous_answered_message_started_at"])

    def test_time_is_isolated_between_users_conversations_and_scopes(self):
        started = "2026-11-06T10:00:00+00:00"
        record_answered_message("user-a", "scope-a", started)
        self.assertEqual(query_time_context("USER-A", "scope-a")["previous_answered_message_started_at"], started)
        for owner, scope in [("user-b", "scope-a"), ("user-a", "new-conversation"), ("user-a", "new-scope")]:
            self.assertIsNone(query_time_context(owner, scope)["previous_answered_message_started_at"])

    def test_late_response_does_not_move_time_backwards(self):
        record_answered_message("user-a", "scope-a", "2026-11-06T11:00:00+00:00")
        record_answered_message("user-a", "scope-a", "2026-11-06T10:00:00+00:00")
        self.assertEqual(query_time_context("user-a", "scope-a")["previous_answered_message_started_at"], "2026-11-06T11:00:00+00:00")

    def test_expired_cursor_is_not_reused(self):
        with patch("sofia.chat_requests.time.time", return_value=0):
            record_answered_message("user-a", "scope-a", "2026-11-06T10:00:00+00:00")
        self.assertIsNone(query_time_context("user-a", "scope-a")["previous_answered_message_started_at"])
