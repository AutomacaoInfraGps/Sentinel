"""Private, machine-authenticated routes used by the SofIA orchestrator."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify

from notification_center import build_notifications, snapshot_is_fresh
from operational_state import DEVICE_GROUPS, load_operational_state

from .service_auth import authenticate_service_request


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
            "persistent",
            "occurred_at",
        )
    }


@sofia_service_bp.get("/api/internal/sofia/v1/alerts")
def service_alerts():
    state = load_operational_state()
    groups = state.get("groups") or {}
    records_by_group = {
        group: (groups.get(group) or {}).get("records") or []
        for group in DEVICE_GROUPS
    }
    stale_groups = sorted(
        group
        for group in DEVICE_GROUPS
        if not snapshot_is_fresh((groups.get(group) or {}).get("updated_at"))
    )
    notifications = build_notifications(records_by_group)
    visible = notifications[:MAX_SERVICE_ALERTS]
    severity_counts = {
        severity: sum(1 for item in notifications if item.get("severity") == severity)
        for severity in ("critical", "important", "success")
    }
    response = jsonify(
        {
            "success": True,
            "service": "sentinel",
            "mode": "read-only",
            "api_version": "v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": {
                "updated_at": state.get("updated_at"),
                "fresh": not stale_groups,
                "stale_groups": stale_groups,
            },
            "summary": {
                "total": len(notifications),
                **severity_counts,
            },
            "alerts": [_service_alert_payload(item) for item in visible],
            "truncated": len(notifications) > len(visible),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response
