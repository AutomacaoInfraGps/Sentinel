from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import quote

from .contracts import DeliveryResult
from .graph import (
    ClientCredentialTokenProvider,
    DelegatedTokenProvider,
    GraphAuthenticationError,
    TokenProvider,
)
from .models import ADGroupEvent


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class HttpResponse(Protocol):
    status_code: int
    headers: dict

    def json(self) -> object: ...


class HttpClient(Protocol):
    def post(self, url: str, **kwargs) -> HttpResponse: ...


def _default_http_client() -> HttpClient:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - depende do ambiente do Rigel
        raise RuntimeError("Dependência 'requests' não instalada") from exc
    return requests.Session()


def _request_error(response: HttpResponse) -> str:
    request_id = response.headers.get("request-id") or response.headers.get("client-request-id")
    suffix = f"; request-id={request_id}" if request_id else ""
    return f"Microsoft Graph retornou HTTP {response.status_code}{suffix}"


def _is_retryable(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599


def retry_after_seconds(
    headers: dict,
    *,
    now: datetime | None = None,
) -> float | None:
    raw_value = next(
        (
            value
            for key, value in headers.items()
            if str(key).casefold() == "retry-after"
        ),
        None,
    )
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        seconds = int(text, 10)
    except ValueError:
        try:
            target = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        return max(0.0, (target.astimezone(timezone.utc) - reference).total_seconds())
    return float(max(0, seconds))


def _recipients_from_env(name: str) -> tuple[str, ...]:
    values = []
    seen = set()
    for raw_value in os.getenv(name, "").split(","):
        value = raw_value.strip()
        key = value.casefold()
        if value and "@" in value and key not in seen:
            values.append(value)
            seen.add(key)
    return tuple(values)


def _teams_delivery_channel(recipient: str) -> str:
    digest = hashlib.sha256(recipient.casefold().encode("utf-8")).hexdigest()[:24]
    return f"teams:{digest}"


def _response_json(response: HttpResponse) -> dict:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _odata_user_reference(user_principal_name: str) -> str:
    escaped = user_principal_name.replace("'", "''")
    return f"{GRAPH_BASE}/users('{escaped}')"


@dataclass
class GraphEmailNotifier:
    token_provider: TokenProvider
    sender_upn: str
    recipients: tuple[str, ...]
    http: HttpClient
    channel: str = "email"

    @classmethod
    def from_environment(cls, http: HttpClient | None = None) -> "GraphEmailNotifier":
        recipients = _recipients_from_env("ALERTAD_EMAIL_RECIPIENTS")
        sender = os.getenv("M365_SENDER_UPN", "").strip()
        if not sender or not recipients:
            raise ValueError("M365_SENDER_UPN ou ALERTAD_EMAIL_RECIPIENTS não configurado")
        provider = ClientCredentialTokenProvider(
            os.getenv("M365_TENANT_ID", ""),
            os.getenv("M365_CLIENT_ID", ""),
            os.getenv("M365_CLIENT_SECRET", ""),
        )
        return cls(provider, sender, recipients, http or _default_http_client())

    def send(self, event: ADGroupEvent, message: str) -> DeliveryResult:
        payload = {
            "message": {
                "subject": f"[CRÍTICO] Alteração no grupo {event.target_user_name}",
                "body": {"contentType": "Text", "content": message},
                "toRecipients": [
                    {"emailAddress": {"address": address}}
                    for address in self.recipients
                ],
            },
            "saveToSentItems": True,
        }
        try:
            token = self.token_provider.get_token()
            response = self.http.post(
                f"{GRAPH_BASE}/users/{quote(self.sender_upn, safe='')}/sendMail",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
        except GraphAuthenticationError as exc:
            return DeliveryResult(
                False,
                exc.retryable,
                str(exc),
                failure_kind=exc.failure_kind,
            )
        except Exception as exc:
            return DeliveryResult(
                False,
                True,
                f"Falha de comunicação com o Graph: {type(exc).__name__}",
                failure_kind="uncertain",
            )

        if response.status_code == 202:
            return DeliveryResult(True)
        retryable = _is_retryable(response.status_code)
        return DeliveryResult(
            False,
            retryable,
            _request_error(response),
            retry_after_seconds=(
                retry_after_seconds(response.headers) if retryable else None
            ),
            failure_kind=(
                "uncertain" if response.status_code == 408 else (
                    "temporary" if retryable else "permanent"
                )
            ),
        )


@dataclass
class GraphTeamsNotifier:
    token_provider: TokenProvider
    chat_id: str
    http: HttpClient
    channel: str = "teams"

    @classmethod
    def from_environment(cls, http: HttpClient | None = None) -> "GraphTeamsNotifier":
        tenant = os.getenv("M365_TENANT_ID", "").strip()
        client = (
            os.getenv("M365_DELEGATED_CLIENT_ID", "").strip()
            or os.getenv("M365_CLIENT_ID", "").strip()
        )
        sender = os.getenv("M365_SENDER_UPN", "").strip()
        chat_id = os.getenv("ALERTAD_TEAMS_CHAT_ID", "").strip()
        cache_file = os.getenv(
            "ALERTAD_TEAMS_CACHE_FILE", ".auth_cache/teams_token_cache.bin"
        ).strip()
        if not chat_id:
            raise ValueError("ALERTAD_TEAMS_CHAT_ID não configurado")
        provider = DelegatedTokenProvider(tenant, client, sender, cache_file)
        return cls(provider, chat_id, http or _default_http_client())

    def send(self, event: ADGroupEvent, message: str) -> DeliveryResult:
        del event  # exigido pelo contrato comum de notificadores
        try:
            token = self.token_provider.get_token()
            response = self.http.post(
                f"{GRAPH_BASE}/chats/{quote(self.chat_id, safe='')}/messages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"body": {"contentType": "text", "content": message}},
                timeout=60,
            )
        except GraphAuthenticationError as exc:
            return DeliveryResult(
                False,
                exc.retryable,
                str(exc),
                failure_kind=exc.failure_kind,
            )
        except Exception as exc:
            return DeliveryResult(
                False,
                True,
                f"Falha de comunicação com o Graph: {type(exc).__name__}",
                failure_kind="uncertain",
            )

        if response.status_code == 201:
            return DeliveryResult(True)
        retryable = _is_retryable(response.status_code)
        return DeliveryResult(
            False,
            retryable,
            _request_error(response),
            retry_after_seconds=(
                retry_after_seconds(response.headers) if retryable else None
            ),
            failure_kind=(
                "uncertain" if response.status_code == 408 else (
                    "temporary" if retryable else "permanent"
                )
            ),
        )


@dataclass
class GraphTeamsRecipientNotifier:
    """Entrega para um chat 1:1 resolvido a partir do UPN do destinatario."""

    token_provider: TokenProvider
    sender_upn: str
    recipient_upn: str
    http: HttpClient
    channel: str
    _chat_id: str | None = field(default=None, init=False, repr=False)

    def _resolve_chat(self, token: str) -> tuple[str | None, DeliveryResult | None]:
        if self._chat_id:
            return self._chat_id, None
        response = self.http.post(
            f"{GRAPH_BASE}/chats",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "chatType": "oneOnOne",
                "members": [
                    {
                        "@odata.type": "#microsoft.graph.aadUserConversationMember",
                        "roles": ["owner"],
                        "user@odata.bind": _odata_user_reference(self.sender_upn),
                    },
                    {
                        "@odata.type": "#microsoft.graph.aadUserConversationMember",
                        "roles": ["owner"],
                        "user@odata.bind": _odata_user_reference(self.recipient_upn),
                    },
                ],
            },
            timeout=60,
        )
        if response.status_code in {200, 201}:
            chat_id = str(_response_json(response).get("id") or "").strip()
            if chat_id:
                self._chat_id = chat_id
                return chat_id, None
            return None, DeliveryResult(
                False,
                False,
                "Microsoft Graph retornou chat sem identificador",
                failure_kind="unexpected",
            )
        if response.status_code == 202:
            return None, DeliveryResult(
                False,
                True,
                "Microsoft Graph iniciou a criacao assincrona do chat",
                retry_after_seconds=30,
                failure_kind="temporary",
            )
        retryable = _is_retryable(response.status_code)
        return None, DeliveryResult(
            False,
            retryable,
            _request_error(response),
            retry_after_seconds=(
                retry_after_seconds(response.headers) if retryable else None
            ),
            failure_kind=("temporary" if retryable else "permanent"),
        )

    def send(self, event: ADGroupEvent, message: str) -> DeliveryResult:
        del event
        try:
            token = self.token_provider.get_token()
            chat_id, failure = self._resolve_chat(token)
            if failure is not None:
                return failure
            response = self.http.post(
                f"{GRAPH_BASE}/chats/{quote(chat_id or '', safe='')}/messages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"body": {"contentType": "text", "content": message}},
                timeout=60,
            )
        except GraphAuthenticationError as exc:
            return DeliveryResult(
                False,
                exc.retryable,
                str(exc),
                failure_kind=exc.failure_kind,
            )
        except Exception as exc:
            return DeliveryResult(
                False,
                True,
                f"Falha de comunicacao com o Graph: {type(exc).__name__}",
                failure_kind="uncertain",
            )

        if response.status_code in {200, 201, 202}:
            return DeliveryResult(True)
        if response.status_code == 404:
            self._chat_id = None
        retryable = _is_retryable(response.status_code) or response.status_code == 404
        return DeliveryResult(
            False,
            retryable,
            _request_error(response),
            retry_after_seconds=(
                retry_after_seconds(response.headers) if retryable else None
            ),
            failure_kind=(
                "uncertain" if response.status_code == 408 else (
                    "temporary" if retryable else "permanent"
                )
            ),
        )


def graph_teams_notifiers_from_environment(
    http: HttpClient | None = None,
) -> dict[str, GraphTeamsNotifier | GraphTeamsRecipientNotifier]:
    recipients = _recipients_from_env("ALERTAD_TEAMS_RECIPIENTS")
    if not recipients:
        notifier = GraphTeamsNotifier.from_environment(http=http)
        return {notifier.channel: notifier}

    tenant = os.getenv("M365_TENANT_ID", "").strip()
    client = (
        os.getenv("M365_DELEGATED_CLIENT_ID", "").strip()
        or os.getenv("M365_CLIENT_ID", "").strip()
    )
    sender = os.getenv("M365_SENDER_UPN", "").strip()
    cache_file = os.getenv(
        "ALERTAD_TEAMS_CACHE_FILE", ".auth_cache/teams_token_cache.bin"
    ).strip()
    provider = DelegatedTokenProvider(tenant, client, sender, cache_file)
    session = http or _default_http_client()
    result = {}
    for recipient in recipients:
        channel = _teams_delivery_channel(recipient)
        result[channel] = GraphTeamsRecipientNotifier(
            provider,
            sender,
            recipient,
            session,
            channel,
        )
    return result
