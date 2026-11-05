"""Server-derived identifiers for isolated SofIA conversation memory."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from flask import current_app


MEMORY_SESSION_SALT = b"sentinel-sofia-memory-session-v1\0"


class SofiaMemoryScopeError(RuntimeError):
    """Raised when a user-bound memory session cannot be derived."""


def derive_memory_session_id(user_ref, conversation_id, allowed_regionals):
    """Return a stable opaque key bound to user, conversation and access scope."""
    secret = current_app.config.get("SECRET_KEY")
    normalized_user = str(user_ref or "").strip().casefold()
    normalized_scope = sorted({
        str(regional).strip().upper()
        for regional in (allowed_regionals or [])
        if str(regional).strip()
    })
    try:
        normalized_conversation = str(uuid.UUID(str(conversation_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SofiaMemoryScopeError("Identificador da conversa invalido.") from exc
    if not secret or not normalized_user or not normalized_scope:
        raise SofiaMemoryScopeError("Escopo da memoria indisponivel.")

    secret_bytes = secret if isinstance(secret, bytes) else str(secret).encode("utf-8")
    payload = (
        MEMORY_SESSION_SALT
        + normalized_user.encode("utf-8")
        + b"\0"
        + normalized_conversation.encode("ascii")
        + b"\0"
        + json.dumps(normalized_scope, separators=(",", ":")).encode("utf-8")
    )
    return hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest()
