"""Authenticated API routes for the SofIA MVP."""

from collections import defaultdict, deque
from threading import BoundedSemaphore, Lock, Thread
import hashlib
import time
import uuid

from flask import Blueprint, abort, current_app, jsonify, make_response, render_template, request
from flask_login import current_user, login_required

from .audit import registrar_evento_sofia
from .n8n_client import SofiaN8nError, consultar_sofia
from .memory_scope import SofiaMemoryScopeError, derive_memory_session_id
from .permissions import usuario_pode_executar
from .scope_token import SofiaScopeError, issue_regional_scope_token
from .tools_sentinel import codigos_regionais
from .user_context import build_user_context
from . import chat_requests
from .execution_control import stop_execution
from regional_access import access_scope, effective_user_groups


sofia_bp = Blueprint("sofia", __name__)

MAX_MESSAGE_LENGTH = 1000
RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
_request_history = defaultdict(deque)
_rate_limit_lock = Lock()
_async_slots = BoundedSemaphore(2)
ASYNC_READ_TIMEOUT = 480


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


def _run_async_chat(app, arguments, owner, memory_session_id, remote_address):
    with app.app_context():
        identifier = arguments["request_id"]
        try:
            reply = consultar_sofia(**arguments, read_timeout=ASYNC_READ_TIMEOUT)
            if chat_requests.finish_result(identifier, reply):
                chat_requests.record_answered_message(
                    owner, memory_session_id, arguments["query_context"]["query_started_at"]
                )
                registrar_evento_sofia(usuario=owner, status="sucesso",
                    tamanho_mensagem=len(arguments["mensagem"]), endereco_remoto=remote_address,
                    detalhe="Resposta assíncrona da SofIA via n8n")
        except Exception as exc:
            current_app.logger.warning("Consulta assíncrona da SofIA falhou (%s)", type(exc).__name__)
            chat_requests.finish_result(identifier,
                "Não consegui concluir a consulta. Tente novamente em uma nova solicitação.", failed=True)
            registrar_evento_sofia(usuario=owner, status="erro",
                tamanho_mensagem=len(arguments["mensagem"]), endereco_remoto=remote_address,
                detalhe="Falha na consulta assíncrona da SofIA")
        finally:
            _async_slots.release()


def _start_async_chat(arguments, owner, memory_session_id, remote_address):
    identifier = arguments["request_id"]
    digest = hashlib.sha256(arguments["mensagem"].encode("utf-8")).hexdigest()
    existing = chat_requests.get_result(identifier)
    if existing:
        reservation = chat_requests.get(identifier)
        if (not reservation or reservation["owner"] != str(owner).casefold()
                or existing["memory_session_id"] != memory_session_id
                or existing["request_digest"] != digest):
            return _json_response({"error": "Identificador da consulta já utilizado."}, 409)
        return _json_response({"request_id": identifier, "pending": True}, 202)
    if not _async_slots.acquire(blocking=False):
        return _json_response({"error": "Há consultas em processamento. Aguarde e tente novamente."}, 429)
    try:
        if not chat_requests.begin(identifier, owner):
            _async_slots.release()
            return _json_response({"cancelled": True, "reply": "Consulta cancelada."})
        chat_requests.create_result(identifier, memory_session_id, digest)
        worker = Thread(target=_run_async_chat,
            args=(current_app._get_current_object(), arguments, owner, memory_session_id, remote_address),
            daemon=True, name="sofia-chat-request")
        worker.start()
    except ValueError:
        _async_slots.release()
        return _json_response({"error": "Identificador da consulta já utilizado."}, 409)
    except Exception:
        _async_slots.release()
        chat_requests.finish_result(identifier, "Não foi possível iniciar a consulta.", failed=True)
        raise
    return _json_response({"request_id": identifier, "pending": True}, 202)


@sofia_bp.before_request
def require_authenticated_api_user():
    if not current_app.config.get("SOFIA_ENABLED", False):
        return _json_response({"error": "Recurso não encontrado."}, 404)
    if not current_user.is_authenticated:
        return _json_response({"error": "Autenticação necessária."}, 401)


@sofia_bp.get("/sofia")
@login_required
def page():
    if not usuario_pode_executar(current_user, "chat:basic"):
        abort(403)
    response = make_response(render_template("sofia_chat.html"))
    response.headers["Cache-Control"] = "no-store"
    return response


@sofia_bp.post("/api/sofia/chat")
@login_required
def chat():
    username = getattr(current_user, "username", None) or current_user.get_id()
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

    try:
        conversation_id = str(uuid.UUID(str(payload.get("conversation_id") or "")))
    except (ValueError, TypeError, AttributeError):
        return _json_response({"error": "Identificador da conversa inválido."}, 400)

    try:
        request_id = chat_requests.request_uuid(payload.get("request_id") or uuid.uuid4())
    except (ValueError, TypeError, AttributeError):
        return _json_response({"error": "Identificador da consulta invalido."}, 400)

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
        groups = effective_user_groups(
            getattr(current_user, "groups", ()) or (),
            getattr(current_user, "dn", ""),
        )
        scope = access_scope(groups, codigos_regionais())
        scope_token = issue_regional_scope_token(scope["allowed"])
        memory_session_id = derive_memory_session_id(
            username,
            conversation_id,
            scope["allowed"],
        )
        if payload.get("async") is True:
            return _start_async_chat({
                "mensagem": message, "allowed_regionals": scope["allowed"],
                "scope_token": scope_token, "conversation_id": memory_session_id,
                "request_id": request_id,
                "user_context": build_user_context(current_user, current_app.config.get("SOFIA_CREATOR_USERS", ())),
                "query_context": chat_requests.query_time_context(username, memory_session_id),
            }, username, memory_session_id, remote_address)
        try:
            should_start = chat_requests.begin(request_id, username)
        except ValueError:
            return _json_response({"error": "Identificador da consulta ja utilizado."}, 409)
        if not should_start:
            return _json_response({"cancelled": True, "reply": "Consulta cancelada."})
        time_context = chat_requests.query_time_context(username, memory_session_id)
        reply = consultar_sofia(
            mensagem=message,
            allowed_regionals=scope["allowed"],
            scope_token=scope_token,
            conversation_id=memory_session_id,
            request_id=request_id,
            user_context=build_user_context(
                current_user,
                current_app.config.get("SOFIA_CREATOR_USERS", ()),
            ),
            query_context=time_context,
        )
        if (chat_requests.get(request_id) or {}).get("cancel_requested"):
            return _json_response({"cancelled": True, "reply": "Resposta descartada apos a solicitacao de parada."})
        chat_requests.record_answered_message(username, memory_session_id, time_context["query_started_at"])
        audit_detail = "Resposta da SofIA via n8n"
        registrar_evento_sofia(
            usuario=username,
            status="sucesso",
            tamanho_mensagem=len(message),
            endereco_remoto=remote_address,
            detalhe=audit_detail,
        )

        return _json_response({"reply": reply})
    except (SofiaMemoryScopeError, SofiaN8nError, SofiaScopeError) as exc:
        current_app.logger.exception("Falha no webhook privado da SofIA")
        registrar_evento_sofia(
            usuario=username,
            status="erro",
            tamanho_mensagem=len(message),
            endereco_remoto=remote_address,
            detalhe=f"Orquestrador indisponivel: {exc}",
        )
        return _json_response(
            {
                "error": "A consulta de alertas da SofIA esta indisponivel no momento.",
                "reply": (
                    "Não consegui consultar os dados do Sentinel neste momento. "
                    "Tente novamente em instantes."
                ),
            },
            502,
        )
    except Exception:
        registrar_evento_sofia(
            usuario=username,
            status="erro",
            tamanho_mensagem=len(message),
            endereco_remoto=remote_address,
            detalhe="Falha interna no processamento",
        )
        return _json_response(
            {
                "error": "Não foi possível processar sua mensagem agora.",
                "reply": (
                    "Não consegui processar sua mensagem neste momento. "
                    "Tente novamente em instantes."
                ),
            },
            500,
        )


@sofia_bp.get("/api/sofia/chat/requests/<identifier>")
@login_required
def chat_result(identifier):
    if (request.headers.get("X-Sentinel-Request") != "sofia-chat"
            or request.headers.get("Sec-Fetch-Site", "same-origin") not in {"same-origin", "none"}):
        return _json_response({"error": "Origem não permitida."}, 403)
    if (not usuario_pode_executar(current_user, "chat:basic")
            or not usuario_pode_executar(current_user, "sentinel:read")):
        return _json_response({"error": "Acesso não permitido."}, 403)
    owner = getattr(current_user, "username", None) or current_user.get_id()
    try:
        identifier = chat_requests.request_uuid(identifier)
        groups = effective_user_groups(getattr(current_user, "groups", ()) or (), getattr(current_user, "dn", ""))
        allowed = access_scope(groups, codigos_regionais())["allowed"]
        scope = derive_memory_session_id(owner, request.args.get("conversation_id"), allowed)
    except (ValueError, TypeError, SofiaMemoryScopeError):
        return _json_response({"error": "Consulta não encontrada."}, 404)
    reservation = chat_requests.get(identifier)
    result = chat_requests.get_result(identifier)
    if (not reservation or not result or reservation["owner"] != str(owner).casefold()
            or result["memory_session_id"] != scope):
        return _json_response({"error": "Consulta não encontrada ou expirada."}, 404)
    if reservation["cancel_requested"]:
        return _json_response({"cancelled": True, "reply": "Consulta interrompida."})
    if result["state"] == "running":
        if time.time() - result["created_at"] > ASYNC_READ_TIMEOUT + 20:
            return _json_response({"error": "Tempo de processamento excedido.",
                                   "reply": "A consulta excedeu o tempo de processamento."}, 504)
        return _json_response({"pending": True, "request_id": identifier}, 202)
    return _json_response({"reply": result["reply"]}, 502 if result["state"] == "error" else 200)


@sofia_bp.post("/api/sofia/chat/cancel")
@login_required
def cancel_chat():
    if request.headers.get("X-Sentinel-Request") != "sofia-chat":
        return _json_response({"error": "Requisicao invalida."}, 403)
    if request.headers.get("Sec-Fetch-Site", "same-origin") not in {"same-origin", "none"}:
        return _json_response({"error": "Origem nao permitida."}, 403)
    if not usuario_pode_executar(current_user, "chat:basic"):
        return _json_response({"error": "Acesso nao permitido."}, 403)
    payload = request.get_json(silent=True) if request.is_json else None
    try:
        request_id = chat_requests.request_uuid(payload["request_id"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return _json_response({"error": "Identificador da consulta invalido."}, 400)
    owner = getattr(current_user, "username", None) or current_user.get_id()
    if not _rate_limit_allows("cancel:" + str(owner)):
        return _json_response({"error": "Muitas solicitacoes de parada. Aguarde um minuto."}, 429)
    record = chat_requests.cancel(request_id, owner)
    if record is None:
        return _json_response({"error": "Consulta nao encontrada."}, 404)
    cancelled = bool(record["cancelled"] or not record["started"])
    message = "Consulta cancelada."
    try:
        # Registration happens immediately after the webhook, before the LLM.
        deadline = time.monotonic() + 3
        while not cancelled and not record["execution_id"] and time.monotonic() < deadline:
            time.sleep(0.1)
            record = chat_requests.get(request_id) or record
            cancelled = bool(record["cancelled"])
        if not cancelled and record["execution_id"]:
            cancelled = stop_execution(record["execution_id"])
        if cancelled:
            chat_requests.confirm_cancelled(request_id)
        else:
            message = "Espera interrompida. O cancelamento no n8n ainda nao foi confirmado."
    except SofiaN8nError as exc:
        current_app.logger.warning("Cancelamento da SofIA nao confirmado: %s", exc)
        message = "Espera interrompida. Nao foi possivel confirmar a parada no n8n."
    registrar_evento_sofia(usuario=owner, status="cancelado" if cancelled else "cancelamento_pendente",
        tamanho_mensagem=0, endereco_remoto=request.remote_addr, acao="chat:cancel", detalhe=message)
    return _json_response({"cancelled": cancelled, "message": message})
