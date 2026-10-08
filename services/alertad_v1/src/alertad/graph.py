from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Protocol


class TokenProvider(Protocol):
    def get_token(self) -> str: ...


class GraphAuthenticationError(RuntimeError):
    """Falha de autenticação sem expor token ou segredo na mensagem."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        failure_kind: str = "permanent",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.failure_kind = failure_kind


def _authentication_transport_error() -> GraphAuthenticationError:
    return GraphAuthenticationError(
        "Falha temporária no transporte de autenticação Graph",
        retryable=True,
        failure_kind="temporary",
    )


_TEMPORARY_AUTH_ERRORS = frozenset(
    {
        "temporarily_unavailable",
        "server_error",
        "service_not_available",
        "request_timeout",
        "timeout",
    }
)
_INTERACTION_AUTH_ERRORS = frozenset(
    {"interaction_required", "login_required", "consent_required"}
)
_PERMANENT_AUTH_ERRORS = frozenset(
    {
        "invalid_client",
        "unauthorized_client",
        "invalid_scope",
        "access_denied",
        "invalid_grant",
    }
)


def _classified_authentication_error(
    result: object,
    *,
    delegated: bool,
) -> GraphAuthenticationError:
    payload = result if isinstance(result, dict) else {}
    code = str(payload.get("error") or "unexpected_response").strip().casefold()
    if code in _TEMPORARY_AUTH_ERRORS:
        return GraphAuthenticationError(
            f"Autenticação Graph temporariamente indisponível: {code}",
            retryable=True,
            failure_kind="temporary",
        )
    if delegated and code in _INTERACTION_AUTH_ERRORS:
        return GraphAuthenticationError(
            "Autenticação delegada requer renovação manual",
            failure_kind="interaction_required",
        )
    if code in _PERMANENT_AUTH_ERRORS or code in _INTERACTION_AUTH_ERRORS:
        return GraphAuthenticationError(
            f"Configuração ou permissão Graph recusada: {code}",
            failure_kind="permanent",
        )
    return GraphAuthenticationError(
        "Resposta inesperada durante autenticação Graph",
        failure_kind="unexpected",
    )


class ClientCredentialTokenProvider:
    """Obtém token de aplicação para o envio de e-mail."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        *,
        authentication_timeout_seconds: float = 60,
    ) -> None:
        if not all(value.strip() for value in (tenant_id, client_id, client_secret)):
            raise ValueError("Configuração de aplicação do Microsoft Graph incompleta")
        self.tenant_id = tenant_id.strip()
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        if authentication_timeout_seconds <= 0:
            raise ValueError("Timeout de autenticação Graph deve ser maior que zero")
        self.authentication_timeout_seconds = float(authentication_timeout_seconds)
        self._application = None

    def get_token(self) -> str:
        if self._application is None:
            try:
                import msal
            except ImportError as exc:  # pragma: no cover - depende do ambiente do Rigel
                raise GraphAuthenticationError("Dependência 'msal' não instalada") from exc
            try:
                self._application = msal.ConfidentialClientApplication(
                    client_id=self.client_id,
                    authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                    client_credential=self.client_secret,
                    timeout=self.authentication_timeout_seconds,
                )
            except Exception as exc:
                raise _authentication_transport_error() from exc

        try:
            result = self._application.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
        except Exception as exc:
            raise _authentication_transport_error() from exc
        token = result.get("access_token") if isinstance(result, dict) else None
        if not token:
            raise _classified_authentication_error(result, delegated=False)
        return str(token)


class DelegatedTokenProvider:
    """Lê e renova silenciosamente o token delegado usado pelo Teams."""

    # Mantem os mesmos escopos dos demais projetos Graph que compartilham
    # esta identidade delegada e o cache MSAL ja consentido.
    scopes = ("User.Read", "Chat.ReadWrite", "ChatMessage.Send")

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        expected_upn: str,
        cache_file: str | Path,
        *,
        authentication_timeout_seconds: float = 60,
    ) -> None:
        if not all(value.strip() for value in (tenant_id, client_id, expected_upn)):
            raise ValueError("Configuração delegada do Microsoft Graph incompleta")
        self.tenant_id = tenant_id.strip()
        self.client_id = client_id.strip()
        self.expected_upn = expected_upn.strip()
        self.cache_file = Path(cache_file)
        if authentication_timeout_seconds <= 0:
            raise ValueError("Timeout de autenticação Graph deve ser maior que zero")
        self.authentication_timeout_seconds = float(authentication_timeout_seconds)
        self._cache = None
        self._application = None
        self._cache_mtime_ns: int | None = None

    def _build_application(self):
        try:
            import msal
        except ImportError as exc:  # pragma: no cover - depende do ambiente do Rigel
            raise GraphAuthenticationError("Dependência 'msal' não instalada") from exc

        cache = msal.SerializableTokenCache()
        if self.cache_file.exists():
            try:
                cache.deserialize(self.cache_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise GraphAuthenticationError("Cache delegado do Teams inválido") from exc
            self._cache_mtime_ns = self.cache_file.stat().st_mtime_ns

        self._cache = cache
        try:
            self._application = msal.PublicClientApplication(
                client_id=self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                token_cache=cache,
                timeout=self.authentication_timeout_seconds,
            )
        except Exception as exc:
            raise _authentication_transport_error() from exc

    def _save_cache(self) -> None:
        if self._cache is None or not self._cache.has_state_changed:
            return
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.cache_file.parent,
                prefix=f".{self.cache_file.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(self._cache.serialize())
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.cache_file)
            self._cache_mtime_ns = self.cache_file.stat().st_mtime_ns
        except OSError as exc:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise GraphAuthenticationError("Não foi possível atualizar o cache delegado") from exc

    def get_token(self) -> str:
        if self._application is not None and self.cache_file.exists():
            try:
                current_mtime = self.cache_file.stat().st_mtime_ns
            except OSError as exc:
                raise GraphAuthenticationError("Cache delegado do Teams indisponível") from exc
            if self._cache_mtime_ns is not None and current_mtime != self._cache_mtime_ns:
                self._cache = None
                self._application = None
        if self._application is None:
            self._build_application()

        try:
            accounts = self._application.get_accounts(username=self.expected_upn)
        except Exception as exc:
            raise _authentication_transport_error() from exc
        if not accounts:
            raise GraphAuthenticationError(
                "Token delegado do Teams ausente; execute a renovação manual",
                failure_kind="interaction_required",
            )

        try:
            result = self._application.acquire_token_silent(
                list(self.scopes), account=accounts[0]
            )
        except Exception as exc:
            raise _authentication_transport_error() from exc
        self._save_cache()
        token = result.get("access_token") if result else None
        if not token:
            if not result:
                raise GraphAuthenticationError(
                    "Token delegado do Teams expirado; execute a renovação manual",
                    failure_kind="interaction_required",
                )
            raise _classified_authentication_error(result, delegated=True)
        return str(token)

    def renew_interactively(self, show_message: Callable[[str], None] = print) -> None:
        """Executado manualmente; nunca é chamado pelo worker de eventos."""
        if self._application is None:
            self._build_application()

        try:
            flow = self._application.initiate_device_flow(scopes=list(self.scopes))
        except Exception as exc:
            raise _authentication_transport_error() from exc
        if "user_code" not in flow:
            raise GraphAuthenticationError("Não foi possível iniciar o device code flow")
        show_message(str(flow.get("message", "Conclua a autenticação Microsoft.")))
        try:
            result = self._application.acquire_token_by_device_flow(flow)
        except Exception as exc:
            raise _authentication_transport_error() from exc
        if "access_token" not in result:
            raise _classified_authentication_error(result, delegated=True)

        claims = result.get("id_token_claims", {})
        authenticated_upn = str(
            claims.get("preferred_username") or claims.get("upn") or ""
        ).strip()
        if authenticated_upn and authenticated_upn.casefold() != self.expected_upn.casefold():
            raise GraphAuthenticationError("A conta autenticada não é a conta configurada")
        self._save_cache()
