"""Private, machine-authenticated routes used by the SofIA orchestrator."""

from datetime import datetime, timezone
import json

from flask import Blueprint, jsonify, request

from .service_auth import authenticate_service_request
from .map_alerts import load_map_alert_snapshot
from .scope_token import SofiaScopeError, read_regional_scope_token
from .tools_sentinel import consultar_inventario_regional
from .operational_inventory import OperationalSnapshotError, query_operational_inventory
from .query_response import execute_plan
from . import chat_requests
from .execution_control import configured_workflow, execution_id, stop_execution
from .n8n_client import SofiaN8nError


sofia_service_bp = Blueprint("sofia_service", __name__)
MAX_SERVICE_ALERTS = 100

SERVICE_CAPABILITIES = (
    {
        "id": "assistant.query.read",
        "method": "POST",
        "path": "/api/internal/sofia/v1/assistant/query",
    },
    {
        "id": "service.health.read",
        "method": "GET",
        "path": "/api/internal/sofia/v1/health",
    },
    {
        "id": "service.capabilities.read",
        "method": "GET",
        "path": "/api/internal/sofia/v1/capabilities",
    },
    {
        "id": "alerts.read",
        "method": "GET",
        "path": "/api/internal/sofia/v1/alerts",
    },
    {
        "id": "regionals.read",
        "method": "POST",
        "path": "/api/internal/sofia/v1/regionals/query",
    },
    {
        "id": "inventory.read",
        "method": "POST",
        "path": "/api/internal/sofia/v1/inventory/query",
    },
)


@sofia_service_bp.before_request
def require_service_identity():
    return authenticate_service_request()


@sofia_service_bp.post("/api/internal/sofia/v1/executions/register")
def register_chat_execution():
    """Bind a trusted n8n execution to a request already owned by a user."""
    payload = request.get_json(silent=True) if request.is_json else None
    try:
        request_id = chat_requests.request_uuid(payload["request_id"])
        identifier = execution_id(payload["execution_id"])
        workflow = str(payload["workflow_id"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Identificadores invalidos."), 400
    try:
        if workflow != configured_workflow():
            return jsonify(error="Workflow nao autorizado."), 403
        if not chat_requests.register_execution(request_id, identifier):
            return jsonify(error="Consulta nao encontrada ou ja vinculada."), 409
        record = chat_requests.get(request_id)
        cancelled = bool(record and record["cancelled"])
        if record and record["cancel_requested"] and not cancelled:
            cancelled = stop_execution(identifier)
            if cancelled:
                chat_requests.confirm_cancelled(request_id)
        response = jsonify(registered=True, cancelled=cancelled)
        response.headers["Cache-Control"] = "no-store"
        return response
    except SofiaN8nError:
        return jsonify(error="Controle de execucoes indisponivel."), 503


@sofia_service_bp.get("/api/internal/sofia/v1/health")
def service_health():
    response = jsonify(
        {
            "status": "ok",
            "service": "sentinel",
            "mode": "read-only",
            "api_version": "v1",
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@sofia_service_bp.get("/api/internal/sofia/v1/capabilities")
def service_capabilities():
    response = jsonify(
        {
            "service": "sentinel",
            "mode": "read-only",
            "api_version": "v1",
            "capabilities": list(SERVICE_CAPABILITIES),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _service_alert_payload(notification):
    return {
        key: notification.get(key)
        for key in (
            "id",
            "type",
            "severity",
            "title",
            "message",
            "regional",
            "device",
            "quantity",
            "persistent",
            "occurred_at",
        )
    }


@sofia_service_bp.get("/api/internal/sofia/v1/alerts")
def service_alerts():
    snapshot = load_map_alert_snapshot()
    alerts = snapshot["alerts"]
    # A partial/stale list must never deactivate alerts or record recoveries.
    if not snapshot["fresh"] or len(alerts) > MAX_SERVICE_ALERTS:
        response = jsonify(
            success=False,
            error="Snapshot incompleto ou desatualizado; sincronizacao nao autorizada.",
            snapshot={"updated_at": snapshot["updated_at"], "fresh": snapshot["fresh"]},
            truncated=len(alerts) > MAX_SERVICE_ALERTS,
        )
        response.headers["Cache-Control"] = "no-store"
        return response, 503
    visible = alerts[:MAX_SERVICE_ALERTS]
    response = jsonify(
        {
            "success": True,
            "service": "sentinel",
            "mode": "read-only",
            "api_version": "v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": {
                "updated_at": snapshot["updated_at"],
                "updated_at_brasilia": snapshot["updated_at_brasilia"],
                "fresh": snapshot["fresh"],
                "age_seconds": snapshot["age_seconds"],
                "ttl_seconds": snapshot["ttl_seconds"],
            },
            "summary": snapshot["summary"],
            "alerts": [_service_alert_payload(item) for item in visible],
            "truncated": len(alerts) > len(visible),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@sofia_service_bp.post("/api/internal/sofia/v1/regionals/query")
def service_regionals_query():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "message": "JSON invalido."}), 400
    try:
        allowed_regionals = read_regional_scope_token(
            payload.get("sentinel_scope_token")
        )
        sections = payload.get("sections") or []
        if not isinstance(sections, list) or len(sections) > 3:
            raise ValueError("Secoes regionais invalidas.")
        result = consultar_inventario_regional(
            codigo_regional=payload.get("regional"),
            secoes=sections,
            allowed_regionals=allowed_regionals,
        )
    except SofiaScopeError:
        return jsonify({"success": False, "message": "Escopo regional invalido."}), 403
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    if result is None:
        return jsonify({"success": False, "message": "Regional nao encontrada."}), 404
    response = jsonify({
        "success": True,
        "service": "sentinel",
        "mode": "read-only",
        "api_version": "v1",
        "data": result,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@sofia_service_bp.post("/api/internal/sofia/v1/inventory/query")
def service_inventory_query():
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        return jsonify(success=False, message="JSON invalido."), 400
    try:
        allowed = read_regional_scope_token(payload.get("sentinel_scope_token"))
        result = query_operational_inventory(
            resource=payload.get("resource"), allowed_regionals=allowed,
            regional=payload.get("regional"), status=payload.get("status"),
            detail_level=payload.get("detail_level", "list"),
            limit=payload.get("limit", 20), offset=payload.get("offset", 0),
            expires_within_days=payload.get("expires_within_days"),
            search=payload.get("search"),
        )
    except SofiaScopeError:
        return jsonify(success=False, message="Escopo regional invalido."), 403
    except PermissionError:
        return jsonify(success=False, message="Regional nao encontrada."), 404
    except (OSError, json.JSONDecodeError, OperationalSnapshotError):
        return jsonify(success=False, message="Snapshot operacional indisponivel."), 503
    except (ValueError, TypeError):
        return jsonify(success=False, message="Consulta de inventario invalida."), 400
    response = jsonify(success=True, service="sentinel", mode="read-only", data=result)
    response.headers["Cache-Control"] = "no-store"
    return response


@sofia_service_bp.post("/api/internal/sofia/v1/assistant/query")
def service_assistant_query():
    """Execute an explicit plan and render the authorized facts server-side."""
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        return jsonify(success=False, message="JSON inválido."), 400
    try:
        allowed = read_regional_scope_token(payload.get("sentinel_scope_token"))
        result = execute_plan(payload.get("plan"), allowed)
    except SofiaScopeError:
        return jsonify(success=False, message="Escopo regional inválido."), 403
    except PermissionError:
        return jsonify(success=False, message="Regional não encontrada."), 404
    except (OSError, json.JSONDecodeError, OperationalSnapshotError):
        return jsonify(success=False, message="Snapshot operacional indisponível."), 503
    except (ValueError, TypeError):
        return jsonify(success=False, message="Plano de consulta inválido."), 400
    response = jsonify(success=True, mode="read-only", **result)
    response.headers["Cache-Control"] = "no-store"
    return response
