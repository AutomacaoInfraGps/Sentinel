"""HMAC authentication for the private n8n-to-Sentinel channel."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import re
import sqlite3
import time

from flask import current_app, g, jsonify, request

from .audit import registrar_evento_sofia


KEY_ID_HEADER = "X-Sentinel-Key-Id"
TIMESTAMP_HEADER = "X-Sentinel-Timestamp"
NONCE_HEADER = "X-Sentinel-Nonce"
SIGNATURE_HEADER = "X-Sentinel-Signature"
DEFAULT_CLOCK_SKEW_SECONDS = 60
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def canonical_request(method, target, timestamp, nonce, body=b""):
    """Return the stable byte sequence signed by the service client."""
    body_digest = hashlib.sha256(body or b"").hexdigest()
    return "\n".join(
        (
            str(method).upper(),
            str(target),
            str(timestamp),
            str(nonce),
            body_digest,
        )
    ).encode("utf-8")


def build_signature(secret, method, target, timestamp, nonce, body=b""):
    """Build the hexadecimal HMAC-SHA256 signature used by n8n."""
    return hmac.new(
        str(secret).encode("utf-8"),
        canonical_request(method, target, timestamp, nonce, body),
        hashlib.sha256,
    ).hexdigest()


def _json_error(status_code, message):
    response = jsonify({"success": False, "message": message})
    response.status_code = status_code
    response.headers["Cache-Control"] = "no-store"
    return response


def _audit(status, detail):
    registrar_evento_sofia(
        usuario="service:n8n",
        acao="service:authenticate",
        status=status,
        tamanho_mensagem=0,
        endereco_remoto=request.remote_addr,
        detalhe=detail,
    )


def _configured_clock_skew():
    raw_value = os.environ.get(
        "SENTINEL_N8N_MAX_CLOCK_SKEW_SECONDS",
        str(DEFAULT_CLOCK_SKEW_SECONDS),
    )
    try:
        return min(300, max(15, int(raw_value)))
    except ValueError:
        return DEFAULT_CLOCK_SKEW_SECONDS


def _request_target():
    query = request.query_string.decode("latin-1")
    return f"{request.path}?{query}" if query else request.path


def _remote_address_is_allowed(remote_address):
    configured = os.environ.get("SENTINEL_N8N_ALLOWED_NETWORKS", "")
    networks = []
    for item in configured.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            current_app.logger.error("Rede n8n invalida na configuracao")
            return False
    if not networks:
        return False
    try:
        address = ipaddress.ip_address(str(remote_address or ""))
    except ValueError:
        return False
    return any(address in network for network in networks)


def _nonce_database_path():
    configured = os.environ.get("SENTINEL_N8N_NONCE_DB", "").strip()
    if configured:
        return Path(configured)
    return Path(current_app.instance_path) / "sofia_service_nonces.sqlite3"


def _register_nonce(key_id, nonce, expires_at):
    path = _nonce_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS used_nonce (
                key_id TEXT NOT NULL,
                nonce TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (key_id, nonce)
            )
            """
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM used_nonce WHERE expires_at < ?",
            (int(time.time()),),
        )
        try:
            connection.execute(
                "INSERT INTO used_nonce (key_id, nonce, expires_at) VALUES (?, ?, ?)",
                (key_id, nonce, int(expires_at)),
            )
        except sqlite3.IntegrityError:
            connection.rollback()
            return False
        connection.commit()
        return True
    finally:
        connection.close()


def authenticate_service_request():
    """Authenticate one service request and fail closed on configuration errors."""
    if not _remote_address_is_allowed(request.remote_addr):
        _audit("negado", "IP de servico nao autorizado")
        return _json_error(403, "Origem de servico nao autorizada.")

    configured_key_id = os.environ.get("SENTINEL_N8N_KEY_ID", "").strip()
    secret = os.environ.get("SENTINEL_N8N_HMAC_SECRET", "").strip()
    if not configured_key_id or len(secret) < 32:
        current_app.logger.error("Autenticacao do servico n8n nao configurada")
        _audit("erro", "Autenticacao de servico indisponivel")
        return _json_error(503, "Autenticacao de servico indisponivel.")

    key_id = request.headers.get(KEY_ID_HEADER, "").strip()
    timestamp_text = request.headers.get(TIMESTAMP_HEADER, "").strip()
    nonce = request.headers.get(NONCE_HEADER, "").strip()
    supplied_signature = request.headers.get(SIGNATURE_HEADER, "").strip().lower()

    if not hmac.compare_digest(key_id, configured_key_id):
        _audit("negado", "Identidade de servico invalida")
        return _json_error(401, "Autenticacao de servico invalida.")
    if not NONCE_PATTERN.fullmatch(nonce):
        _audit("negado", "Nonce de servico invalido")
        return _json_error(401, "Autenticacao de servico invalida.")
    if not re.fullmatch(r"[0-9a-f]{64}", supplied_signature):
        _audit("negado", "Assinatura de servico invalida")
        return _json_error(401, "Autenticacao de servico invalida.")

    try:
        timestamp = int(timestamp_text)
    except ValueError:
        _audit("negado", "Timestamp de servico invalido")
        return _json_error(401, "Autenticacao de servico invalida.")

    clock_skew = _configured_clock_skew()
    if abs(int(time.time()) - timestamp) > clock_skew:
        _audit("negado", "Requisicao de servico expirada")
        return _json_error(401, "Autenticacao de servico invalida.")

    body = request.get_data(cache=True)
    expected_signature = build_signature(
        secret,
        request.method,
        _request_target(),
        timestamp_text,
        nonce,
        body,
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        _audit("negado", "Assinatura de servico divergente")
        return _json_error(401, "Autenticacao de servico invalida.")

    try:
        nonce_registered = _register_nonce(
            key_id,
            nonce,
            int(time.time()) + (clock_skew * 2),
        )
    except (OSError, sqlite3.Error):
        current_app.logger.exception("Falha ao registrar nonce do servico n8n")
        _audit("erro", "Protecao contra replay indisponivel")
        return _json_error(503, "Autenticacao de servico indisponivel.")
    if not nonce_registered:
        _audit("negado", "Requisicao de servico repetida")
        return _json_error(401, "Autenticacao de servico invalida.")

    g.sofia_service_id = key_id
    _audit("sucesso", "Canal n8n autenticado")
    return None
