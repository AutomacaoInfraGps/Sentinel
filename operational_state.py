import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock

from config import PROJECT_ROOT


STATE_FILE = PROJECT_ROOT / "output" / "sentinel_operational_state.json"
DEVICE_GROUPS = ("servidores", "switches", "links", "aps", "vpns", "firewalls", "admins")
_lock = Lock()
_VOLATILE_FIELDS = {
    "ultima_verificacao",
    "ultima_atualizacao_mapa",
    "updated_at",
    "changed_at",
}


def _now_iso():
    return datetime.now().isoformat()


def _device_key(device):
    for field in ("hostid", "id", "ip", "nome", "host", "tunel"):
        value = str((device or {}).get(field) or "").strip().lower()
        if value:
            return f"{field}:{value}"
    return ""


def _device_signature(device):
    return {
        key: value
        for key, value in (device or {}).items()
        if key not in _VOLATILE_FIELDS
    }


def load_operational_state(path=None):
    state_path = Path(path or STATE_FILE)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_atomic(payload, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def publish_map_snapshot(map_data, source="mapa", path=None, collected_at=None):
    state_path = Path(path or STATE_FILE)
    now = collected_at or _now_iso()
    regionals = (map_data or {}).get("regionais") or []

    with _lock:
        previous = load_operational_state(state_path)
        previous_groups = previous.get("groups") or {}
        groups = {}

        for group in DEVICE_GROUPS:
            old_records = previous_groups.get(group, {}).get("records") or []
            old_by_key = {
                (str(item.get("regional") or ""), _device_key(item)): item
                for item in old_records
                if _device_key(item)
            }
            records = []
            for regional in regionals:
                regional_code = str(regional.get("codigo") or "").strip()
                for raw_device in regional.get(group) or []:
                    device = deepcopy(raw_device)
                    device["regional"] = regional_code
                    key = (regional_code, _device_key(device))
                    old = old_by_key.get(key)
                    changed = old is None or _device_signature(old) != _device_signature(device)
                    device["updated_at"] = now
                    device["changed_at"] = now if changed else old.get("changed_at") or now
                    records.append(device)

            for raw_device in ((map_data or {}).get("unmapped") or {}).get(group) or []:
                device = deepcopy(raw_device)
                regional_code = str(device.get("regional") or "SEM_REGIONAL").strip()
                device["regional"] = regional_code
                key = (regional_code, _device_key(device))
                old = old_by_key.get(key)
                changed = old is None or _device_signature(old) != _device_signature(device)
                device["updated_at"] = now
                device["changed_at"] = now if changed else old.get("changed_at") or now
                records.append(device)

            groups[group] = {
                "source": source,
                "updated_at": now,
                "records": records,
            }

        payload = {
            "version": 1,
            "updated_at": now,
            "source": source,
            "groups": groups,
            "regionals": deepcopy(regionals),
            "summary": deepcopy((map_data or {}).get("resumo") or {}),
        }
        _write_atomic(payload, state_path)
        return payload


def records_for(group, regional=None, path=None):
    records = load_operational_state(path).get("groups", {}).get(group, {}).get("records") or []
    if regional is None:
        return deepcopy(records)
    regional_norm = str(regional or "").strip().upper()
    return [
        deepcopy(item)
        for item in records
        if str(item.get("regional") or "").strip().upper() == regional_norm
    ]
