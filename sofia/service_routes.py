"""Private, machine-authenticated routes used by the SofIA orchestrator."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify

from .service_auth import authenticate_service_request
from .map_alerts import load_map_alert_snapshot


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
