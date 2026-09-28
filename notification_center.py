import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import quote, urlencode

from config import PROJECT_ROOT


NOTIFICATION_STATE_FILE = PROJECT_ROOT / "output" / "notification_user_state.json"
_state_lock = Lock()

_GROUP_CONFIG = {
    "links": ("Link indisponível", "bi-router", "critical", "/links"),
    "vpns": ("VPN indisponível", "bi-shield-lock", "critical", "/vpn"),
    "aps": ("Antena indisponível", "bi-wifi-off", "important", "/antenas"),
    "switches": ("Switch com falha", "bi-hdd-network", "critical", "/switches"),
    "firewalls": ("Alerta de firewall", "bi-shield-exclamation", "critical", "/firewalls"),
    "servidores": ("Servidor indisponível", "bi-server", "critical", "/regionais"),
    "admins": ("Divergência no Monitor de Admins", "bi-person-exclamation", "critical", "/admin-logins"),
}
_ALERT_STATUSES = {"offline", "down", "warning", "alerta", "critical", "critico", "error", "erro"}
NOTIFICATION_SNAPSHOT_MAX_AGE = timedelta(hours=6)
SWITCH_UPDATE_NOTIFICATION_MAX_AGE = timedelta(days=30)


def _parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def snapshot_is_fresh(updated_at, now=None, max_age=None):
    updated = _parse_datetime(updated_at)
    if not updated:
        return False
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc) - updated <= (max_age or NOTIFICATION_SNAPSHOT_MAX_AGE)


def _device_name(item):
    return str(
        item.get("nome")
        or item.get("host")
        or item.get("tunel")
        or item.get("id")
        or item.get("ip")
        or "Dispositivo"
    ).strip()


def _notification_id(group, item, kind="status"):
    occurrence = str(item.get("changed_at") or item.get("ultima_verificacao") or "").strip()
    raw = "|".join((group, kind, str(item.get("regional") or ""), _device_name(item), occurrence))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _notification_url(group, target, name, regional):
    query = urlencode({"q": name})
    if group == "servidores" and regional and regional != "Sem regional":
        return f"/regional/{quote(regional, safe='')}?{query}#regional-servidores-section"
    return f"{target}?{query}"


def sort_notifications(notifications):
    """Ordena pendências persistentes antes dos demais eventos recentes."""
    ordered = list(notifications or [])
    priority = {"vpn_orphan": 0, "admin_baseline": 1}
    ordered.sort(key=lambda item: str(item.get("occurred_at") or ""), reverse=True)
    ordered.sort(key=lambda item: priority.get(item.get("type"), 2))
    return ordered


def build_switch_update_notifications(jobs, now=None, max_age=None):
    """Converte atualizações concluídas do histórico em eventos do sino."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    allowed_age = max_age or SWITCH_UPDATE_NOTIFICATION_MAX_AGE
    notifications = []

    for job in jobs or []:
        if str(job.get("status") or "").strip().lower() != "completed":
            continue

        occurred_at = job.get("finished_at_utc") or job.get("finished_at_brasilia")
        occurred = _parse_datetime(occurred_at)
        if not occurred or reference - occurred > allowed_age:
            continue

        job_id = str(job.get("id") or "").strip()
        if not job_id:
            continue
        name = str(
            job.get("switch_name") or job.get("host") or job.get("ip_address") or "Switch"
        ).strip()
        version = str(job.get("expected_version") or "").strip()
        reviewed = (
            job.get("history_status") == "confirmed_after_review"
            or job.get("result_code") == "SWU411"
        )
        if reviewed:
            message = f"A atualização de {name} foi confirmada após a revisão operacional."
        elif version:
            message = f"{name} foi atualizado com sucesso para a versão {version}."
        else:
            message = f"{name} foi atualizado com sucesso."
        query = urlencode({"q": name, "job": job_id})
        notification_id = hashlib.sha256(
            f"switch_update|completed|{job_id}".encode("utf-8")
        ).hexdigest()[:24]
        notifications.append({
            "id": notification_id,
            "type": "switch_update_completed",
            "severity": "success",
            "icon": "bi-arrow-up-circle",
            "title": "Atualização de switch concluída",
            "message": message,
            "regional": str(job.get("regional") or "Sem regional").strip(),
            "device": name,
            "persistent": False,
            "occurred_at": occurred_at,
            "url": f"/switches/firmware/history?{query}",
        })

    return sort_notifications(notifications)


def build_notifications(records_by_group, orphan_vpn_names=None):
    orphan_vpn_names = {str(name).strip() for name in (orphan_vpn_names or set())}
    notifications = []

    for group, config in _GROUP_CONFIG.items():
        title, icon, severity, target = config
        for item in records_by_group.get(group) or []:
            if item.get("em_manutencao"):
                continue
            name = _device_name(item)
            regional = str(item.get("regional") or "Sem regional").strip()

            if group == "vpns" and name in orphan_vpn_names:
                notifications.append({
                    "id": _notification_id(group, item, "orphan"),
                    "type": "vpn_orphan",
                    "severity": "important",
                    "icon": "bi-diagram-3",
                    "title": "VPN sem vínculo regional",
                    "message": f"{name} não corresponde a nenhuma regional cadastrada.",
                    "regional": "Sem regional",
                    "device": name,
                    "persistent": True,
                    "occurred_at": item.get("changed_at") or item.get("updated_at"),
                    "url": _notification_url(group, target, name, regional),
                })

            raw_status = item.get("status_disponibilidade") or item.get("status")
            status = str(raw_status or "").strip().lower()
            if status not in _ALERT_STATUSES:
                continue

            item_title = title
            item_severity = severity
            item_type = group
            item_persistent = False
            if group == "firewalls" and status in {"warning", "alerta"}:
                item_title = "Licença de firewall requer atenção"
                item_severity = "important"
            if group == "admins" and item.get("baseline_pending"):
                item_title = "Administrador fora da baseline"
                item_type = "admin_baseline"
                item_persistent = True

            reason = item.get("warning_resumo") or item.get("status_reason") or item.get("descricao")
            message = f"{name} está {status}."
            if reason and str(reason).strip().lower() not in {status, "n/a"}:
                message = f"{name}: {str(reason).strip()}"
            notifications.append({
                "id": _notification_id(group, item),
                "type": item_type,
                "severity": item_severity,
                "icon": icon,
                "title": item_title,
                "message": message,
                "regional": regional,
                "device": name,
                "persistent": item_persistent,
                "occurred_at": item.get("changed_at") or item.get("ultima_verificacao") or item.get("updated_at"),
                "url": _notification_url(group, target, name, regional),
            })

    return sort_notifications(notifications)


def _load_state(path=None):
    state_path = Path(path or NOTIFICATION_STATE_FILE)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_atomic(payload, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def decorate_with_read_state(username, notifications, path=None):
    state = _load_state(path)
    user_state = ((state.get("users") or {}).get(str(username), {}) or {})
    seen = set(user_state.get("seen_ids") or [])
    dismissed = set(user_state.get("dismissed_ids") or [])
    decorated = []
    for item in notifications:
        persistent = bool(item.get("persistent"))
        if not persistent and item["id"] in dismissed:
            continue
        # Visualizar ou limpar nao resolve uma pendencia persistente.
        decorated.append({**item, "read": False if persistent else item["id"] in seen})
    return decorated, sum(1 for item in decorated if not item["read"])


def mark_notifications_seen(username, notification_ids, path=None):
    state_path = Path(path or NOTIFICATION_STATE_FILE)
    with _state_lock:
        state = _load_state(state_path)
        users = state.setdefault("users", {})
        user_state = users.setdefault(str(username), {})
        seen = list(dict.fromkeys((user_state.get("seen_ids") or []) + list(notification_ids or [])))
        user_state["seen_ids"] = seen[-2000:]
        user_state["viewed_at"] = datetime.now().isoformat()
        _write_atomic(state, state_path)
    return user_state


def dismiss_notifications(username, notification_ids, path=None):
    state_path = Path(path or NOTIFICATION_STATE_FILE)
    with _state_lock:
        state = _load_state(state_path)
        users = state.setdefault("users", {})
        user_state = users.setdefault(str(username), {})
        dismissed = list(dict.fromkeys(
            (user_state.get("dismissed_ids") or []) + list(notification_ids or [])
        ))
        user_state["dismissed_ids"] = dismissed[-2000:]
        user_state["cleared_at"] = datetime.now().isoformat()
        _write_atomic(state, state_path)
    return user_state
