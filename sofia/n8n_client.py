"""Restricted client for the private SofIA n8n webhook."""

import os
from urllib.parse import urlsplit

import requests


WEBHOOK_URL_ENV = "SENTINEL_SOFIA_N8N_WEBHOOK_URL"
WEBHOOK_TOKEN_ENV = "SENTINEL_SOFIA_N8N_WEBHOOK_TOKEN"
TOKEN_HEADER = "X-Sentinel-Sofia-Token"
MAX_REPLY_LENGTH = 8000


class SofiaN8nError(RuntimeError):
    """Raised when the private orchestrator cannot return a valid response."""


def _configured_url():
    url = os.environ.get(WEBHOOK_URL_ENV, "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SofiaN8nError("Webhook da SofIA nao configurado")
    if parsed.username or parsed.password or parsed.fragment:
        raise SofiaN8nError("URL do webhook da SofIA invalida")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SofiaN8nError("Webhook HTTP da SofIA deve usar o tunel local")
    return url


def _configured_token():
    token = os.environ.get(WEBHOOK_TOKEN_ENV, "").strip()
    if len(token) < 32:
        raise SofiaN8nError("Token do webhook da SofIA nao configurado")
    return token


def consultar_resumo_alertas(*, mensagem, allowed_regionals):
    regionals = sorted({
        str(regional).strip()
        for regional in (allowed_regionals or [])
        if str(regional).strip()
    })[:200]
    if not regionals:
        return "Nao ha regionais disponiveis para o seu perfil de acesso."

    try:
        response = requests.post(
            _configured_url(),
            headers={TOKEN_HEADER: _configured_token()},
            json={
                "message": str(mensagem or "")[:1000],
                "allowed_regionals": regionals,
            },
            timeout=(5, 180),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise SofiaN8nError("Falha de comunicacao com o orquestrador") from exc

    if response.status_code != 200:
        raise SofiaN8nError(f"Orquestrador respondeu HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SofiaN8nError("Resposta nao JSON do orquestrador") from exc
    reply = payload.get("reply") if isinstance(payload, dict) else None
    if not isinstance(reply, str) or not reply.strip() or len(reply) > MAX_REPLY_LENGTH:
        raise SofiaN8nError("Resposta invalida do orquestrador")
    return reply.strip()
