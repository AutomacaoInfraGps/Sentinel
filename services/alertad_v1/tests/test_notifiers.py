from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from alertad.notifiers import GraphEmailNotifier, GraphTeamsNotifier, retry_after_seconds
from alertad.graph import GraphAuthenticationError
from alertad.parsing import parse_windows_event


FIXTURES = Path(__file__).parent / "fixtures"


class FakeTokenProvider:
    def get_token(self) -> str:
        return "token-de-teste"


class FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.response


class NotifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.event = parse_windows_event(
            (FIXTURES / "event_4732.xml").read_text(encoding="utf-8")
        )

    def test_email_uses_application_endpoint_and_recipients(self) -> None:
        http = FakeHttpClient(FakeResponse(202))
        notifier = GraphEmailNotifier(
            FakeTokenProvider(),
            "alertas@example.com",
            ("time@example.com",),
            http,
        )

        result = notifier.send(self.event, "mensagem")

        self.assertTrue(result.success)
        url, request = http.calls[0]
        self.assertIn("/users/alertas%40example.com/sendMail", url)
        self.assertEqual(
            request["json"]["message"]["toRecipients"][0]["emailAddress"]["address"],
            "time@example.com",
        )
        self.assertEqual(request["json"]["message"]["body"]["content"], "mensagem")

    def test_teams_posts_directly_to_configured_group_chat(self) -> None:
        http = FakeHttpClient(FakeResponse(201))
        notifier = GraphTeamsNotifier(
            FakeTokenProvider(),
            "19:chat@thread.v2",
            http,
        )

        result = notifier.send(self.event, "mensagem")

        self.assertTrue(result.success)
        url, request = http.calls[0]
        self.assertIn("/chats/19%3Achat%40thread.v2/messages", url)
        self.assertEqual(
            request["json"],
            {"body": {"contentType": "text", "content": "mensagem"}},
        )

    def test_transient_graph_failure_is_retryable_without_response_body(self) -> None:
        http = FakeHttpClient(
            FakeResponse(429, {"request-id": "request-id-de-teste"})
        )
        notifier = GraphTeamsNotifier(FakeTokenProvider(), "chat", http)

        result = notifier.send(self.event, "mensagem")

        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertEqual(
            result.error,
            "Microsoft Graph retornou HTTP 429; request-id=request-id-de-teste",
        )
        self.assertEqual(result.failure_kind, "temporary")

    def test_retry_after_accepts_seconds_and_http_date_case_insensitively(self) -> None:
        reference = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(retry_after_seconds({"rEtRy-AfTeR": "45"}), 45)
        self.assertEqual(
            retry_after_seconds(
                {"Retry-After": "Wed, 30 Sep 2026 12:05:00 GMT"},
                now=reference,
            ),
            300,
        )
        self.assertIsNone(retry_after_seconds({"Retry-After": "invalid"}))

    def test_graph_result_exposes_retry_after(self) -> None:
        http = FakeHttpClient(FakeResponse(429, {"Retry-After": "120"}))
        result = GraphTeamsNotifier(FakeTokenProvider(), "chat", http).send(
            self.event,
            "mensagem",
        )

        self.assertEqual(result.retry_after_seconds, 120)

    def test_permission_failure_is_not_retryable(self) -> None:
        http = FakeHttpClient(FakeResponse(403))
        notifier = GraphEmailNotifier(
            FakeTokenProvider(),
            "alertas@example.com",
            ("time@example.com",),
            http,
        )

        result = notifier.send(self.event, "mensagem")

        self.assertFalse(result.success)
        self.assertFalse(result.retryable)
        self.assertEqual(result.error, "Microsoft Graph retornou HTTP 403")

    def test_temporary_authentication_error_remains_retryable(self) -> None:
        class TemporaryProvider:
            @staticmethod
            def get_token() -> str:
                raise GraphAuthenticationError(
                    "Autenticação temporariamente indisponível",
                    retryable=True,
                    failure_kind="temporary",
                )

        result = GraphTeamsNotifier(
            TemporaryProvider(),
            "chat",
            FakeHttpClient(FakeResponse(201)),
        ).send(self.event, "mensagem")

        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertEqual(result.failure_kind, "temporary")


if __name__ == "__main__":
    unittest.main()
