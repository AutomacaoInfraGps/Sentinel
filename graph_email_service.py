from __future__ import annotations

import atexit
import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import msal
import requests

from config import ENV_CONFIG, PROJECT_ROOT


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = [
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/User.Read",
    "offline_access",
    "openid",
    "profile",
]


def _coalesce(*values: Any, default: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "sim", "on"}


def _parse_scopes(value: Any) -> list[str]:
    if isinstance(value, list):
        scopes = [str(item or "").strip() for item in value]
    else:
        scopes = [item.strip() for item in str(value or "").split(",")]
    return [scope for scope in scopes if scope]


def _normalize_recipients(recipients: list[str] | tuple[str, ...] | str) -> list[str]:
    if isinstance(recipients, str):
        raw_items = recipients.split(",")
    else:
        raw_items = list(recipients or [])

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        email = str(item or "").strip()
        if not email or "@" not in email:
            continue

        key = email.lower()
        if key in seen:
            continue

        seen.add(key)
        cleaned.append(email)

    return cleaned


@dataclass(frozen=True)
class GraphEmailConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    sender_upn: str
    reply_to: str
    token_cache_path: Path
    allow_interactive_login: bool
    scopes: list[str]

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @property
    def auth_mode(self) -> str:
        return "application" if self.client_secret else "delegated"

    @property
    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.client_id:
            missing.append("client_id")
        if self.auth_mode == "application" and not self.sender_upn:
            missing.append("sender_upn")
        return missing


def load_graph_email_config() -> GraphEmailConfig:
    graph_config = ENV_CONFIG.get("microsoft_graph", {}) or {}
    default_cache_path = PROJECT_ROOT / "authtoken" / "graph_token_cache.bin"

    tenant_id = _coalesce(
        os.getenv("M365_TENANT_ID"),
        graph_config.get("tenant_id"),
    )
    client_id = _coalesce(
        os.getenv("M365_DELEGATED_CLIENT_ID"),
        os.getenv("M365_CLIENT_ID"),
        graph_config.get("client_id"),
    )
    client_secret = _coalesce(
        os.getenv("M365_CLIENT_SECRET"),
        graph_config.get("client_secret"),
    )
    sender_upn = _coalesce(
        os.getenv("M365_SENDER_UPN"),
        graph_config.get("sender_upn"),
    )
    reply_to = _coalesce(
        os.getenv("REPLY_TO_GROUP_EMAIL"),
        graph_config.get("reply_to"),
    )
    cache_path = _coalesce(
        os.getenv("M365_TOKEN_CACHE_PATH"),
        graph_config.get("token_cache_path"),
        default=str(default_cache_path),
    )
    scopes = _parse_scopes(graph_config.get("scopes")) or list(DEFAULT_SCOPES)
    allow_interactive_login = _parse_bool(
        os.getenv("M365_ALLOW_INTERACTIVE_LOGIN"),
        _parse_bool(graph_config.get("allow_interactive_login"), False),
    )

    return GraphEmailConfig(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        sender_upn=sender_upn,
        reply_to=reply_to,
        token_cache_path=Path(cache_path),
        allow_interactive_login=allow_interactive_login,
        scopes=scopes,
    )


class GraphEmailService:
    def __init__(self, config: GraphEmailConfig | None = None):
        self.config = config or load_graph_email_config()
        self._token_cache: msal.SerializableTokenCache | None = None
        self._app: msal.PublicClientApplication | None = None
        self._confidential_app: msal.ConfidentialClientApplication | None = None

    def is_configured(self) -> bool:
        return not self.config.missing_fields

    def _ensure_configured(self) -> None:
        if self.is_configured():
            return

        missing = ", ".join(self.config.missing_fields)
        raise RuntimeError(
            "Configuracao Microsoft Graph incompleta. Ajuste environment.json ou variaveis de ambiente: "
            f"{missing}."
        )

    def _load_cache(self) -> msal.SerializableTokenCache:
        if self._token_cache is not None:
            return self._token_cache

        cache = msal.SerializableTokenCache()
        cache_path = self.config.token_cache_path
        if cache_path.exists():
            cache.deserialize(cache_path.read_text(encoding="utf-8"))

        def save_cache() -> None:
            if not cache.has_state_changed:
                return
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(cache.serialize(), encoding="utf-8")

        atexit.register(save_cache)
        self._token_cache = cache
        return cache

    def _build_public_client(self) -> msal.PublicClientApplication:
        if self._app is not None:
            return self._app

        self._ensure_configured()
        self._app = msal.PublicClientApplication(
            client_id=self.config.client_id,
            authority=self.config.authority,
            token_cache=self._load_cache(),
        )
        return self._app

    def _build_confidential_client(self) -> msal.ConfidentialClientApplication:
        if self._confidential_app is not None:
            return self._confidential_app

        self._ensure_configured()
        self._confidential_app = msal.ConfidentialClientApplication(
            client_id=self.config.client_id,
            authority=self.config.authority,
            client_credential=self.config.client_secret,
        )
        return self._confidential_app

    def _resolve_account(self, app: msal.PublicClientApplication) -> dict[str, Any] | None:
        if self.config.sender_upn:
            accounts = app.get_accounts(username=self.config.sender_upn)
            if accounts:
                return accounts[0]

        accounts = app.get_accounts()
        if accounts:
            return accounts[0]

        return None

    def acquire_token(self, interactive: bool | None = None) -> str:
        if self.config.auth_mode == "application":
            app = self._build_confidential_client()
            result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            token = result.get("access_token")
            if token:
                return str(token)
            raise RuntimeError(
                "Falha ao obter token Microsoft Graph via client credentials: "
                + json.dumps(result, ensure_ascii=False)
            )

        app = self._build_public_client()
        account = self._resolve_account(app)

        if account:
            result = app.acquire_token_silent(self.config.scopes, account=account)
            if result and result.get("access_token"):
                return str(result["access_token"])

        interactive_allowed = self.config.allow_interactive_login if interactive is None else interactive
        if not interactive_allowed:
            raise RuntimeError(
                "Token Microsoft Graph nao encontrado no cache. Execute o teste com --interactive para autenticar "
                f"e gravar o cache em {self.config.token_cache_path}."
            )

        flow = app.initiate_device_flow(scopes=self.config.scopes)
        if "user_code" not in flow:
            raise RuntimeError(
                "Falha ao iniciar device flow do Microsoft Graph: "
                + json.dumps(flow, ensure_ascii=False)
            )

        print(flow.get("message", "Acesse o link exibido pelo Microsoft Graph para concluir a autenticacao."))
        result = app.acquire_token_by_device_flow(flow)
        token = result.get("access_token")
        if not token:
            raise RuntimeError(
                "Falha ao obter token Microsoft Graph: " + json.dumps(result, ensure_ascii=False)
            )

        return str(token)

    def _get(self, endpoint: str, token: str) -> requests.Response:
        return requests.get(
            f"{GRAPH_BASE_URL}{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )

    def _post(self, endpoint: str, token: str, payload: dict[str, Any]) -> requests.Response:
        return requests.post(
            f"{GRAPH_BASE_URL}{endpoint}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )

    def get_profile(self, interactive: bool | None = None) -> dict[str, Any]:
        token = self.acquire_token(interactive=interactive)
        endpoint = "/me?$select=id,displayName,userPrincipalName,mail"
        if self.config.auth_mode == "application":
            endpoint = f"/users/{self.config.sender_upn}?$select=id,displayName,userPrincipalName,mail"
        response = self._get(endpoint, token)
        if response.status_code != 200:
            raise RuntimeError(
                f"Falha ao consultar perfil no Graph: HTTP {response.status_code} | {response.text}"
            )
        return response.json()

    def _build_attachment_payloads(self, attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for attachment in attachments or []:
            data = attachment.get("data", b"")
            if not data:
                continue

            payload = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": str(attachment.get("name") or "arquivo.bin").strip() or "arquivo.bin",
                "contentType": str(attachment.get("content_type") or "application/octet-stream").strip(),
                "contentBytes": base64.b64encode(data).decode("ascii"),
            }

            content_id = str(attachment.get("content_id") or attachment.get("cid") or "").strip()
            if content_id:
                payload["isInline"] = bool(attachment.get("is_inline", True))
                payload["contentId"] = content_id

            payloads.append(payload)

        return payloads

    def send_mail(
        self,
        recipients: list[str] | tuple[str, ...] | str,
        subject: str,
        html_body: str,
        interactive: bool | None = None,
        save_to_sent_items: bool = True,
        attachments: list[dict[str, Any]] | None = None,
        reply_to: list[str] | tuple[str, ...] | str | None = None,
    ) -> bool:
        normalized_recipients = _normalize_recipients(recipients)
        if not normalized_recipients:
            raise ValueError("Nenhum destinatario valido foi informado para envio pelo Microsoft Graph.")

        token = self.acquire_token(interactive=interactive)
        normalized_reply_to = _normalize_recipients(reply_to or ([self.config.reply_to] if self.config.reply_to else []))
        payload = {
            "message": {
                "subject": str(subject or "").strip(),
                "body": {
                    "contentType": "HTML",
                    "content": str(html_body or ""),
                },
                "toRecipients": [
                    {"emailAddress": {"address": recipient}}
                    for recipient in normalized_recipients
                ],
            },
            "saveToSentItems": bool(save_to_sent_items),
        }

        if normalized_reply_to:
            payload["message"]["replyTo"] = [
                {"emailAddress": {"address": recipient}}
                for recipient in normalized_reply_to
            ]

        attachment_payloads = self._build_attachment_payloads(attachments)
        if attachment_payloads:
            payload["message"]["attachments"] = attachment_payloads

        endpoint = "/me/sendMail"
        if self.config.auth_mode == "application":
            endpoint = f"/users/{self.config.sender_upn}/sendMail"

        response = self._post(endpoint, token, payload)
        if response.status_code not in (200, 202):
            raise RuntimeError(
                f"Falha ao enviar email pelo Graph: HTTP {response.status_code} | {response.text}"
            )
        return True
