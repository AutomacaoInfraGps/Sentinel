"""Short-lived Sentinel-signed scope passed through the SofIA orchestrator."""

from __future__ import annotations

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer


SCOPE_TOKEN_SALT = "sentinel-sofia-regional-scope-v1"
SCOPE_TOKEN_MAX_AGE_SECONDS = 300
MAX_SCOPE_REGIONALS = 200


class SofiaScopeError(RuntimeError):
    """Raised when a regional scope cannot be issued or validated."""


def _serializer():
    secret_key = current_app.config.get("SECRET_KEY")
    if not secret_key:
        raise SofiaScopeError("Assinatura de escopo indisponivel.")
    return URLSafeTimedSerializer(secret_key, salt=SCOPE_TOKEN_SALT)


def issue_regional_scope_token(regionals):
    allowed = sorted({
        str(regional).strip().upper()
        for regional in (regionals or [])
        if str(regional).strip()
    })[:MAX_SCOPE_REGIONALS]
    if not allowed:
        raise SofiaScopeError("O escopo regional esta vazio.")
    return _serializer().dumps({"version": 1, "regionals": allowed})


def read_regional_scope_token(token, *, max_age=SCOPE_TOKEN_MAX_AGE_SECONDS):
    try:
        payload = _serializer().loads(str(token or ""), max_age=max_age)
    except BadData as exc:
        raise SofiaScopeError("Escopo regional invalido ou expirado.") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise SofiaScopeError("Escopo regional invalido ou expirado.")
    regionals = payload.get("regionals")
    if not isinstance(regionals, list):
        raise SofiaScopeError("Escopo regional invalido ou expirado.")
    allowed = {
        str(regional).strip().upper()
        for regional in regionals
        if isinstance(regional, str) and regional.strip()
    }
    if not allowed or len(allowed) > MAX_SCOPE_REGIONALS:
        raise SofiaScopeError("Escopo regional invalido ou expirado.")
    return allowed
