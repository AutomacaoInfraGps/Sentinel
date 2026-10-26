"""Persistencia e adaptacao segura da Revisao de Acessos para o sino."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from .settings import DATA_ROOT


ALLOWED_ORIGIN = "automacao-auditoria"
ALLOWED_STATUSES = frozenset({"SUCESSO", "FALHA"})
ALLOWED_SEVERITIES = frozenset({"informacao", "aviso", "critico"})
AUDIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_AUDITS = 50
DEFAULT_RETENTION_DAYS = 180
DEFAULT_MAX_EVENTS = 1000
DEFAULT_RECENT_LIMIT = 100


class AuditPayloadError(ValueError):
    """Payload externo invalido e seguro para retornar como HTTP 400."""


def _text(value, name, maximum, *, required=True):
    if not isinstance(value, str):
        raise AuditPayloadError(f"{name} deve ser texto.")
    result = value.strip()
    if required and not result:
        raise AuditPayloadError(f"{name} e obrigatorio.")
    if len(result) > maximum:
        raise AuditPayloadError(f"{name} excede {maximum} caracteres.")
    return result


def _iso_datetime(value, name):
    text = _text(value, name, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditPayloadError(f"{name} deve ser uma data ISO 8601 valida.") from exc
    if parsed.tzinfo is None:
        raise AuditPayloadError(f"{name} deve incluir o fuso horario.")
    return parsed.isoformat()


def _boolean(value, name):
    if not isinstance(value, bool):
        raise AuditPayloadError(f"{name} deve ser booleano.")
    return value


def _integer(value, name, *, minimum=0, maximum=1_000_000):
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuditPayloadError(f"{name} deve ser inteiro.")
    if not minimum <= value <= maximum:
        raise AuditPayloadError(f"{name} esta fora do intervalo permitido.")
    return value


def sanitize_audit_payload(payload):
    """Seleciona exclusivamente dados necessarios ao sino e valida seus limites."""
    if not isinstance(payload, Mapping):
        raise AuditPayloadError("O corpo JSON deve ser um objeto.")

    origin = _text(payload.get("origem"), "origem", 64)
    if origin != ALLOWED_ORIGIN:
        raise AuditPayloadError("origem invalida.")
    status = _text(payload.get("status"), "status", 16).upper()
    if status not in ALLOWED_STATUSES:
        raise AuditPayloadError("status invalido.")
    severity = _text(payload.get("severidade"), "severidade", 16).casefold()
    if severity not in ALLOWED_SEVERITIES:
        raise AuditPayloadError("severidade invalida.")

    raw_summary = payload.get("resumo")
    if not isinstance(raw_summary, Mapping):
        raise AuditPayloadError("resumo deve ser um objeto.")
    executed_at = _iso_datetime(raw_summary.get("executado_em"), "resumo.executado_em")
    occurred_at = _iso_datetime(payload.get("data"), "data")

    execution_id = payload.get("execucao_id", raw_summary.get("execucao_id"))
    if execution_id is None:
        stable_key = f"{origin}:{executed_at}"
        execution_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:32]
    else:
        execution_id = _text(execution_id, "execucao_id", 128)
        if not AUDIT_ID_PATTERN.fullmatch(execution_id):
            raise AuditPayloadError("execucao_id possui formato invalido.")

    raw_audits = raw_summary.get("auditorias")
    if not isinstance(raw_audits, list) or not raw_audits:
        raise AuditPayloadError("resumo.auditorias deve ser uma lista nao vazia.")
    if len(raw_audits) > MAX_AUDITS:
        raise AuditPayloadError(f"resumo.auditorias excede {MAX_AUDITS} itens.")

    audits = []
    for index, item in enumerate(raw_audits):
        prefix = f"resumo.auditorias[{index}]"
        if not isinstance(item, Mapping):
            raise AuditPayloadError(f"{prefix} deve ser um objeto.")
        item_status = _text(item.get("status"), f"{prefix}.status", 16).upper()
        if item_status not in {"OK", "FALHA"}:
            raise AuditPayloadError(f"{prefix}.status invalido.")
        audit = {
            "id": _text(item.get("id"), f"{prefix}.id", 64),
            "nome": _text(item.get("nome"), f"{prefix}.nome", 100),
            "status": item_status,
            "tentativas": _integer(item.get("tentativas"), f"{prefix}.tentativas", minimum=1, maximum=100),
            "inicio": _iso_datetime(item.get("inicio"), f"{prefix}.inicio"),
            "fim": _iso_datetime(item.get("fim"), f"{prefix}.fim"),
        }
        failure_stage = item.get('failure_stage')
        if failure_stage not in (None, 'collection', 'document'):
            raise AuditPayloadError('Etapa de falha inválida.')
        audit['failure_stage'] = failure_stage
        if item.get("erro_amigavel") not in (None, ""):
            audit["erro_amigavel"] = _text(
                item.get("erro_amigavel"), f"{prefix}.erro_amigavel", 500
            )
        audits.append(audit)

    return {
        "execucao_id": execution_id,
        "source_execution_id": _text(payload['source_execution_id'], 'source_execution_id', 128) if payload.get('source_execution_id') else None,
        "origem": origin,
        "titulo": _text(payload.get("titulo"), "titulo", 160),
        "mensagem": _text(payload.get("mensagem"), "mensagem", 2000),
        "status": status,
        "severidade": severity,
        "data": occurred_at,
        "resumo": {
            "executado_em": executed_at,
            "somente_montagem": _boolean(raw_summary.get("somente_montagem"), "resumo.somente_montagem"),
            "navegador_compartilhado": _boolean(raw_summary.get("navegador_compartilhado"), "resumo.navegador_compartilhado"),
            "documentos_validos": _boolean(raw_summary.get("documentos_validos"), "resumo.documentos_validos"),
            "prints_removidos": _integer(raw_summary.get("prints_removidos"), "resumo.prints_removidos"),
            "auditorias": audits,
        },
    }


def _database_path(path=None):
    if path is not None:
        return Path(path)
    return DATA_ROOT / 'executions.sqlite3'


def _retention_days():
    try:
        from .settings import load_settings
        return load_settings()['retention_days']
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def _max_events():
    try:
        from .settings import load_settings
        return load_settings()['max_events']
    except ValueError:
        return DEFAULT_MAX_EVENTS


def _connect(path):
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS audit_execution (
            execution_id TEXT PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    return connection


def store_audit_execution(payload, *, path=None, now=None):
    """Grava uma execucao de forma idempotente e aplica retencao transacional."""
    sanitized = sanitize_audit_payload(payload)
    current_time = now or datetime.now(timezone.utc)
    encoded = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    connection = _connect(_database_path(path))
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT 1 FROM audit_execution WHERE execution_id = ?",
            (sanitized["execucao_id"],),
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO audit_execution VALUES (?, ?, ?, ?, ?)",
                (sanitized["execucao_id"], sanitized["data"], sanitized["status"], encoded, current_time.isoformat()),
            )
        cutoff = (current_time - timedelta(days=_retention_days())).isoformat()
        connection.execute("DELETE FROM audit_execution WHERE created_at < ?", (cutoff,))
        connection.execute(
            """DELETE FROM audit_execution
               WHERE execution_id NOT IN (
                   SELECT execution_id FROM audit_execution
                   ORDER BY occurred_at DESC LIMIT ?
               )""",
            (_max_events(),),
        )
        connection.commit()
        return sanitized["execucao_id"], existing is None
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _message(payload):
    labels = {
        'windows': 'AD Windows',
        'admanager': 'AD Manager',
        'firewalls': 'Firewall',
        'linux': 'Linux',
    }
    rows = [
        (labels.get(item['id'], item['nome']), 'SUCESSO' if item['status'] == 'OK' else 'FALHA')
        for item in payload['resumo']['auditorias']
    ]
    return '\n'.join(f'{name}: {status}' for name, status in sorted(rows, key=lambda row: row[0].casefold()))


def _notification(payload, root=DATA_ROOT):
    success = payload["status"] == "SUCESSO"
    local_time = datetime.fromisoformat(payload['data'].replace('Z', '+00:00')).astimezone(ZoneInfo('America/Sao_Paulo'))
    reviews = payload['resumo']['auditorias']
    started = min(datetime.fromisoformat(item['inicio']) for item in reviews)
    finished = max(datetime.fromisoformat(item['fim']) for item in reviews)
    duration = max(0, int((finished - started).total_seconds()))
    from .recovery import recovery_available
    states = []
    for item in reviews:
        state = 'success' if item['status'] == 'OK' else item.get('failure_stage') or 'unknown'
        available = state == 'document' and recovery_available(root, payload['execucao_id'], item['id'])
        states.append({'id': item['id'], 'name': item['nome'], 'state': state,
                       'can_regenerate': available,
                       'reason': ('Evidências completas e preservadas.' if available else
                                  'Documento concluído — disponível para download.' if state == 'success' else
                                  'Coleta incompleta — inicie uma nova revisão.' if state == 'collection' else
                                  'Evidências desta execução indisponíveis ou incompletas.')})
    return {
        "id": f"auditoria:{payload['execucao_id']}",
        "type": "audit_automation",
        "severity": "success" if success else "critical",
        "icon": "bi-person-check",
        "title": "Revisão de Acessos - Resumo:",
        "message": _message(payload),
        "regional": "Revisão de Acessos",
        "device": "Revisão de Acessos",
        "persistent": False,
        "occurred_at": payload["data"],
        "log_label": local_time.strftime('RevAcc_%Y-%m-%d_%H:%M:%S'),
        "duration_seconds": duration,
        "reviews": states,
        "source_execution_id": payload.get('source_execution_id'),
        "url": f"/revisao-acessos?execucao={payload['execucao_id']}",
    }


def load_access_review_notifications(*, authorized, logger=None, path=None, limit=DEFAULT_RECENT_LIMIT):
    """Retorna somente o formato aprovado; indisponibilidade nao afeta o sino."""
    if not authorized:
        return []
    try:
        if path is None:
            config_path = DATA_ROOT / 'config' / 'notifications.json'
            if config_path.exists():
                options = json.loads(config_path.read_text(encoding='utf-8-sig'))
                if options.get('sino_habilitado') is not True:
                    return []
        connection = _connect(_database_path(path))
        try:
            rows = connection.execute(
                "SELECT payload_json FROM audit_execution ORDER BY occurred_at DESC LIMIT ?",
                (min(500, max(1, int(limit))),),
            ).fetchall()
        finally:
            connection.close()
        return [_notification(json.loads(row["payload_json"]), root=_database_path(path).parent) for row in rows]
    except Exception as exc:
        if logger is not None:
            logger.warning("Auditorias indisponiveis para o sino; reason=%s", type(exc).__name__)
        return []
