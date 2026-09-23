"""Blueprint pronto para conectar o backend v0.1 ao Sentinel.

O Sentinel injeta somente duas regras locais: como localizar um switch pelo
host e quais usuarios podem atualizar. Todo o fluxo de preflight, upload,
agendamento, DPAPI, execucao e consulta de progresso permanece neste projeto.
"""

from __future__ import annotations

import logging
from pathlib import Path
import secrets
from typing import Callable
from uuid import uuid4

from flask import Blueprint, Flask, abort, jsonify, request, session
from flask_login import current_user
from werkzeug.utils import secure_filename

try:  # pacote copiado para services/switch_update_v01 no Sentinel
    from .main import MAX_FIRMWARE_BYTES, UpdateError, __version__
    from .scheduler import (
        TZDATA_AVAILABLE,
        ScheduleConflictError,
        ScheduleError,
        SwitchUpdateScheduler,
    )
except ImportError:  # testes/execucao direta neste repositorio
    from main import MAX_FIRMWARE_BYTES, UpdateError, __version__
    from scheduler import (
        TZDATA_AVAILABLE,
        ScheduleConflictError,
        ScheduleError,
        SwitchUpdateScheduler,
    )


SwitchResolver = Callable[[str], dict | None]
AuthorizationCheck = Callable[[str], bool]
WorkerTrigger = Callable[[], bool]
WorkerHealth = Callable[[], dict]
LOGGER = logging.getLogger("sentinel.switch-update.backend")


def create_switch_update_blueprint(
    scheduler: SwitchUpdateScheduler,
    *,
    resolve_switch: SwitchResolver,
    is_authorized: AuthorizationCheck,
    trigger_worker: WorkerTrigger | None = None,
    worker_health: WorkerHealth | None = None,
    execution_mode: str = "internal_thread",
) -> Blueprint:
    blueprint = Blueprint("switch_firmware_v01", __name__)
    # Compartilha o token global do Sentinel. O security.js envia este valor
    # automaticamente e o before_request principal também o valida.
    csrf_session_key = "_csrf_token"

    @blueprint.before_request
    def configure_request_limits() -> None:
        if request.endpoint == "switch_firmware_v01.firmware_preflight":
            request.max_content_length = MAX_FIRMWARE_BYTES + 1024 * 1024

    def user_id() -> str:
        if not current_user.is_authenticated:
            abort(401)
        value = str(current_user.get_id() or "").strip()
        if not value:
            abort(401)
        return value

    def require_authorized_user() -> str:
        value = user_id()
        if not is_authorized(value):
            abort(403)
        return value

    def validate_csrf() -> None:
        expected = str(session.get(csrf_session_key) or "")
        provided = str(request.headers.get("X-CSRF-Token") or "")
        if not expected or not provided or not secrets.compare_digest(expected, provided):
            abort(403, description="Token CSRF ausente ou invalido.")

    def switch_url(host: str) -> tuple[dict, str]:
        record = resolve_switch(host)
        if not isinstance(record, dict):
            abort(404, description="Switch nao encontrado no inventario do Sentinel.")
        ip = str(record.get("ip") or "").strip()
        if not ip:
            abort(400, description="Switch sem IP cadastrado.")
        status = str(record.get("status") or "").strip().casefold()
        if status and status not in {"online", "warning", "atencao", "atenção"}:
            abort(409, description="O switch precisa estar online para iniciar o preflight.")
        protocol = str(record.get("protocol") or record.get("protocolo") or "https").lower()
        if protocol not in {"http", "https"}:
            protocol = "https"
        return record, f"{protocol}://{ip}"

    def json_error(message: str, status: int):
        return jsonify({"success": False, "message": message}), status

    @blueprint.errorhandler(ScheduleConflictError)
    def conflict_error(exc):
        return json_error(str(exc), 409)

    @blueprint.errorhandler(ScheduleError)
    @blueprint.errorhandler(UpdateError)
    def operational_error(exc):
        return json_error(str(exc), 400)

    @blueprint.errorhandler(400)
    @blueprint.errorhandler(401)
    @blueprint.errorhandler(403)
    @blueprint.errorhandler(404)
    @blueprint.errorhandler(409)
    @blueprint.errorhandler(413)
    def http_error(exc):
        return json_error(str(getattr(exc, "description", exc)), int(exc.code))

    @blueprint.get("/api/switches/firmware/csrf")
    def csrf_token():
        require_authorized_user()
        token = secrets.token_urlsafe(32)
        session[csrf_session_key] = token
        return jsonify({"success": True, "csrf_token": token})

    @blueprint.get("/api/switches/firmware/health")
    def firmware_health():
        require_authorized_user()
        payload = {
            "success": True,
            "version": __version__,
            "scheduler_running": scheduler.is_running,
            "execution_mode": execution_mode,
            "timezone": "America/Sao_Paulo",
            "tzdata_available": TZDATA_AVAILABLE,
        }
        if worker_health is not None:
            try:
                payload["worker"] = dict(worker_health())
            except Exception:
                LOGGER.exception("Nao foi possivel consultar a tarefa externa do worker.")
                payload["worker"] = {"available": False}
        return jsonify(payload)

    @blueprint.post("/api/switches/<path:host>/firmware/preflight")
    def firmware_preflight(host: str):
        owner = require_authorized_user()
        validate_csrf()
        switch, url = switch_url(host)
        if request.content_length and request.content_length > MAX_FIRMWARE_BYTES + 1024 * 1024:
            abort(413, description="Upload excede o limite permitido.")
        uploaded = request.files.get("firmware")
        if uploaded is None or not uploaded.filename:
            return json_error("Selecione um firmware .swi.", 400)
        original_name = secure_filename(uploaded.filename)
        if not original_name.lower().endswith(".swi"):
            return json_error("Apenas firmware .swi e permitido.", 400)
        original_name = f"{Path(original_name).stem[:160]}.swi"

        temporary = scheduler.draft_dir / f"upload-{uuid4().hex}-{original_name}"
        total = 0
        try:
            with temporary.open("xb") as output:
                while True:
                    chunk = uploaded.stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_FIRMWARE_BYTES:
                        raise ScheduleError(
                            f"O firmware excede {MAX_FIRMWARE_BYTES // (1024 * 1024)} MiB."
                        )
                    output.write(chunk)
            if total == 0:
                raise ScheduleError("O arquivo de firmware esta vazio.")
            draft = scheduler.create_draft(
                owner=owner,
                url=url,
                firmware=temporary,
                original_name=original_name,
            )
        finally:
            temporary.unlink(missing_ok=True)

        return jsonify(
            {
                "success": True,
                "draft": draft,
                "switch": {
                    "host": host,
                    "ip": switch.get("ip"),
                    "modelo": switch.get("modelo"),
                    "local": switch.get("local"),
                    "status": switch.get("status"),
                    "ultima_verificacao": switch.get("ultima_verificacao_formatada")
                    or switch.get("ultima_verificacao"),
                },
            }
        )

    @blueprint.post("/api/switches/<path:host>/firmware/jobs")
    def create_firmware_job(host: str):
        owner = require_authorized_user()
        validate_csrf()
        switch_url(host)  # confirma novamente que o host continua no inventario
        payload = request.get_json(silent=True) or {}
        password = str(payload.get("password") or "")
        immediate = not payload.get("scheduled_at")
        try:
            draft = scheduler.get_draft(str(payload.get("draft_token") or ""), owner=owner)
            if draft["host"] != switch_url(host)[1].split("://", 1)[1]:
                return json_error("O preflight pertence a outro switch.", 409)
            scheduled_at = payload.get("scheduled_at")
            if not scheduled_at:
                scheduled_at = scheduler.now()
            result = scheduler.schedule_from_draft(
                draft_id=draft["draft_token"],
                owner=owner,
                scheduled_at=scheduled_at,
                username=str(payload.get("username") or ""),
                password=password,
                confirmed_decision=str(payload.get("confirmed_decision") or ""),
            )
        finally:
            password = ""
        worker_triggered = None
        if immediate and trigger_worker is not None:
            try:
                worker_triggered = bool(trigger_worker())
            except Exception:
                worker_triggered = False
                LOGGER.exception("Nao foi possivel acionar a tarefa externa do worker.")
        return jsonify(
            {
                "success": True,
                "job": result,
                "worker_triggered": worker_triggered,
            }
        ), 202

    @blueprint.get("/api/switches/firmware/jobs")
    def list_firmware_jobs():
        owner = require_authorized_user()
        return jsonify({"success": True, "jobs": scheduler.list_schedules(owner=owner)})

    @blueprint.get("/api/switches/firmware/jobs/<job_id>")
    def firmware_job_status(job_id: str):
        owner = require_authorized_user()
        return jsonify({"success": True, "job": scheduler.get_schedule(job_id, owner=owner)})

    @blueprint.delete("/api/switches/firmware/jobs/<job_id>")
    def cancel_firmware_job(job_id: str):
        owner = require_authorized_user()
        validate_csrf()
        result = scheduler.cancel_schedule(job_id, owner=owner)
        return jsonify({"success": True, "job": result})

    @blueprint.post("/api/switches/firmware/jobs/<job_id>/acknowledge-review")
    def acknowledge_firmware_review(job_id: str):
        owner = require_authorized_user()
        validate_csrf()
        result = scheduler.acknowledge_review(job_id, owner=owner)
        return jsonify({"success": True, "job": result})

    @blueprint.post("/api/switches/firmware/jobs/<job_id>/recheck")
    def recheck_firmware_job(job_id: str):
        owner = require_authorized_user()
        validate_csrf()
        result = scheduler.recheck_review(job_id, owner=owner)
        return jsonify({"success": True, "job": result})

    @blueprint.delete("/api/switches/firmware/drafts/<draft_id>")
    def cancel_firmware_draft(draft_id: str):
        owner = require_authorized_user()
        validate_csrf()
        scheduler.delete_draft(draft_id, owner=owner)
        return jsonify({"success": True})

    return blueprint


def install_switch_update_backend(
    app: Flask,
    scheduler: SwitchUpdateScheduler,
    *,
    resolve_switch: SwitchResolver,
    is_authorized: AuthorizationCheck,
    start_scheduler: bool = True,
    trigger_worker: WorkerTrigger | None = None,
    worker_health: WorkerHealth | None = None,
) -> Blueprint:
    """Registra as rotas e inicia o unico worker sequencial do processo."""
    existing = app.extensions.get("switch_update_backend_v01")
    if existing:
        return existing["blueprint"]
    blueprint = create_switch_update_blueprint(
        scheduler,
        resolve_switch=resolve_switch,
        is_authorized=is_authorized,
        trigger_worker=trigger_worker,
        worker_health=worker_health,
        execution_mode="internal_thread" if start_scheduler else "windows_task",
    )
    app.register_blueprint(blueprint)
    app.extensions["switch_update_backend_v01"] = {
        "blueprint": blueprint,
        "scheduler": scheduler,
    }
    if start_scheduler:
        scheduler.start()
    return blueprint
