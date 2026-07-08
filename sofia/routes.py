"""Authenticated API routes for the SofIA MVP."""

from collections import defaultdict, deque
from threading import Lock
import time

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from .audit import registrar_evento_sofia
from .engine import processar_mensagem_sofia
from .permissions import usuario_pode_executar


sofia_bp = Blueprint("sofia", __name__)

MAX_MESSAGE_LENGTH = 1000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
_request_history = defaultdict(deque)
_rate_limit_lock = Lock()


def _json_response(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _rate_limit_allows(user_id):
    now = time.monotonic()
    with _rate_limit_lock:
        history = _request_history[str(user_id)]
        while history and now - history[0] >= RATE_LIMIT_WINDOW_SECONDS:
            history.popleft()
        if len(history) >= RATE_LIMIT_REQUESTS:
            return False
        history.append(now)
        return True


@sofia_bp.before_request
def require_authenticated_api_user():
    if not current_app.config.get("SOFIA_ENABLED", False):
        return _json_response({"error": "Recurso não encontrado."}, 404)
    if not current_user.is_authenticated:
        return _json_response({"error": "Autenticação necessária."}, 401)


@sofia_bp.post("/api/sofia/chat")
@login_required
def chat():
    username = getattr(current_user, "username", current_user.get_id())
    remote_address = request.remote_addr

    if request.headers.get("X-Sentinel-Request") != "sofia-chat":
        registrar_evento_sofia(
            usuario=username,
            status="rejeitado",
            tamanho_mensagem=0,
            endereco_remoto=remote_address,
            detalhe="Cabeçalho de origem ausente",
        )
        return _json_response({"error": "Requisição inválida."}, 403)

    if request.headers.get("Sec-Fetch-Site", "same-origin") not in {"same-origin", "none"}:
        return _json_response({"error": "Origem não permitida."}, 403)

    if not request.is_json:
        return _json_response({"error": "O corpo deve ser JSON."}, 415)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json_response({"error": "JSON inválido."}, 400)

    message = payload.get("message")
    if not isinstance(message, str):
        return _json_response({"error": "A mensagem deve ser um texto."}, 400)

    message = message.strip()
    if not message:
        return _json_response({"error": "Digite uma mensagem."}, 400)
    if len(message) > MAX_MESSAGE_LENGTH:
        return _json_response({"error": f"A mensagem deve ter até {MAX_MESSAGE_LENGTH} caracteres."}, 413)

    if not _rate_limit_allows(username):
        registrar_evento_sofia(
            usuario=username,
            status="limitado",
            tamanho_mensagem=len(message),
            endereco_remoto=remote_address,
        )
        return _json_response({"error": "Muitas mensagens. Aguarde um minuto e tente novamente."}, 429)

    if not usuario_pode_executar(current_user, "chat:basic"):
        registrar_evento_sofia(
            usuario=username,
            status="negado",
            tamanho_mensagem=len(message),
            endereco_remoto=remote_address,
        )
        return _json_response({"error": "Você não possui permissão para usar a SofIA."}, 403)

    if not usuario_pode_executar(current_user, "sentinel:read"):
        return _json_response({"error": "Você não possui permissão para consultar dados do Sentinel."}, 403)

    try:
        reply = processar_mensagem_sofia(usuario=username, mensagem=message)
        registrar_evento_sofia(
            usuario=username,
            status="sucesso",
            tamanho_mensagem=len(message),
            endereco_remoto=remote_address,
        )
        return _json_response({"reply": reply})
    except Exception:
        registrar_evento_sofia(
            usuario=username,
            status="erro",
            tamanho_mensagem=len(message),
            endereco_remoto=remote_address,
            detalhe="Falha interna no processamento",
        )
        return _json_response({"error": "Não foi possível processar sua mensagem agora."}, 500)
