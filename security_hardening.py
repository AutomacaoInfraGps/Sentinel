"""Controles de segurança HTTP compartilhados pelo Sentinel."""

import hmac
import os
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

from flask import jsonify, redirect, request, session, url_for
from flask_login import current_user


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PUBLIC_ENDPOINTS = frozenset({"login", "static", "serve_branding_asset"})


def _load_or_create_secret(project_root):
    configured = os.environ.get("SECRET_KEY", "").strip()
    if configured:
        return configured

    secret_path = Path(project_root) / "instance" / "secret_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = secret_path.read_text(encoding="ascii").strip()
        if len(current) >= 64:
            return current
    except OSError:
        pass

    secret = secrets.token_hex(48)
    temporary = secret_path.with_suffix(".tmp")
    temporary.write_text(secret, encoding="ascii")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, secret_path)
    return secret


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def is_safe_next_url(target):
    if not target:
        return False
    host = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, str(target)))
    return candidate.scheme == host.scheme and candidate.netloc == host.netloc


def _csrf_is_valid():
    expected = str(session.get("_csrf_token") or "")
    supplied = str(
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token")
        or ""
    )
    if expected and supplied and hmac.compare_digest(expected, supplied):
        return True
    return False


def configure_security(app, project_root):
    https_enabled = os.environ.get("SENTINEL_HTTPS_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    app.secret_key = _load_or_create_secret(project_root)
    trusted_hosts = [
        host.strip()
        for host in os.environ.get("SENTINEL_TRUSTED_HOSTS", "").split(",")
        if host.strip()
    ]
    app.config.update(
        SESSION_COOKIE_NAME="sentinel_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=https_enabled,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        MAX_CONTENT_LENGTH=4 * 1024 * 1024,
    )
    if trusted_hosts:
        app.config["TRUSTED_HOSTS"] = trusted_hosts
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def require_authenticated_request():
        endpoint = request.endpoint
        if endpoint and endpoint not in PUBLIC_ENDPOINTS and not current_user.is_authenticated:
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "Autenticação necessária."}), 401
            next_path = request.full_path.rstrip("?")
            return redirect(url_for("login", next=next_path))

        if request.method not in SAFE_METHODS and not _csrf_is_valid():
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "message": "Requisição de segurança inválida."}), 400
            return "Requisição de segurança inválida.", 400
        return None

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; object-src 'none'; frame-ancestors 'self'; form-action 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; "
            "font-src 'self' data: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://code.jquery.com https://cdn.tailwindcss.com;"
        )
        if https_enabled:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        if request.endpoint not in {"static", "serve_branding_asset"}:
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    return {"https_enabled": https_enabled}
