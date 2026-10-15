"""Private, machine-authenticated routes used by the SofIA orchestrator."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from .service_auth import authenticate_service_request
from .map_alerts import load_map_alert_snapshot
from .scope_token import SofiaScopeError, read_regional_scope_token
from .tools_sentinel import consultar_inventario_regional


sofia_service_bp = Blueprint("sofia_service", __name__)
MAX_SERVICE_ALERTS = 100

SERVICE_CAPABILITIES = (
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
)


@sofia_service_bp.before_request
def require_service_identity():
    return authenticate_service_request()


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
