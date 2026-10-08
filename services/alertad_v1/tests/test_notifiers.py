from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from alertad.notifiers import (
    GraphEmailNotifier,
    GraphTeamsNotifier,
    GraphTeamsRecipientNotifier,
    graph_teams_notifiers_from_environment,
    retry_after_seconds,
)
from alertad.graph import GraphAuthenticationError
from alertad.parsing import parse_windows_event


FIXTURES = Path(__file__).parent / "fixtures"


class FakeTokenProvider:
    def get_token(self) -> str:
        return "token-de-teste"


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        headers: dict | None = None,
        payload: object | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("synthetic response without json")
        return self.payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.response


class SequenceHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


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
        self.assertEqual(request["json"]["message"]["body"]["contentType"], "HTML")
        self.assertEqual(
            request["json"]["message"]["body"]["content"],
            "<div><strong>mensagem</strong></div>",
        )

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
            {
                "body": {
                    "contentType": "html",
                    "content": "<div><strong>mensagem</strong></div>",
                }
            },
        )

    def test_teams_recipient_resolves_one_on_one_chat_and_reuses_it(self) -> None:
        http = SequenceHttpClient(
            [
                FakeResponse(201, payload={"id": "19:direct@thread.v2"}),
                FakeResponse(201),
                FakeResponse(201),
            ]
        )
        notifier = GraphTeamsRecipientNotifier(
            FakeTokenProvider(),
            "sender@example.com",
            "target@example.com",
            http,
            "teams:synthetic",
        )

        first = notifier.send(self.event, "primeira")
        second = notifier.send(self.event, "segunda")

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(len(http.calls), 3)
        chat_url, chat_request = http.calls[0]
        self.assertTrue(chat_url.endswith("/chats"))
        members = chat_request["json"]["members"]
        self.assertIn("sender@example.com", members[0]["user@odata.bind"])
        self.assertIn("target@example.com", members[1]["user@odata.bind"])
        self.assertIn("19%3Adirect%40thread.v2/messages", http.calls[1][0])
        self.assertIn("19%3Adirect%40thread.v2/messages", http.calls[2][0])
        self.assertEqual(
            http.calls[1][1]["json"]["body"],
            {
                "contentType": "html",
                "content": "<div><strong>primeira</strong></div>",
            },
        )

    def test_async_chat_creation_is_retried_without_sending_message(self) -> None:
        http = SequenceHttpClient([FakeResponse(202)])
        notifier = GraphTeamsRecipientNotifier(
            FakeTokenProvider(),
            "sender@example.com",
            "target@example.com",
            http,
            "teams:synthetic",
        )

        result = notifier.send(self.event, "mensagem")

        self.assertFalse(result.success)
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_after_seconds, 30)
        self.assertEqual(len(http.calls), 1)

    def test_teams_recipient_factory_deduplicates_and_separates_deliveries(self) -> None:
        environment = {
            "M365_TENANT_ID": "synthetic-tenant",
            "M365_CLIENT_ID": "synthetic-client",
            "M365_SENDER_UPN": "sender@example.com",
            "ALERTAD_TEAMS_CACHE_FILE": "synthetic-cache.bin",
            "ALERTAD_TEAMS_RECIPIENTS": (
                "first@example.com,SECOND@example.com,first@example.com"
            ),
        }
        with patch.dict("os.environ", environment, clear=True):
            notifiers = graph_teams_notifiers_from_environment(
                http=FakeHttpClient(FakeResponse(201))
            )

        self.assertEqual(len(notifiers), 2)
        self.assertTrue(all(channel.startswith("teams:") for channel in notifiers))
        self.assertEqual(
            {notifier.recipient_upn for notifier in notifiers.values()},
            {"first@example.com", "SECOND@example.com"},
        )
        providers = {id(notifier.token_provider) for notifier in notifiers.values()}
        self.assertEqual(len(providers), 1)

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
