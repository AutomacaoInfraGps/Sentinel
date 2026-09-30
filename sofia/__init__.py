"""SofIA integration for the Sentinel web application."""

from .routes import sofia_bp
from .service_routes import sofia_service_bp


def init_sofia(app):
    """Register the isolated SofIA API blueprint."""
    app.register_blueprint(sofia_bp)
    app.register_blueprint(sofia_service_bp)

