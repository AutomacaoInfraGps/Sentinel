"""Private, machine-authenticated routes used by the SofIA orchestrator."""

from flask import Blueprint, jsonify

from .service_auth import authenticate_service_request


sofia_service_bp = Blueprint("sofia_service", __name__)

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
