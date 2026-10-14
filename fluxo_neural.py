"""Sanitized topology projection for the Sentinel neural network view."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256


DEVICE_GROUPS = ("servidores", "switches", "links", "firewalls", "vpns", "aps")
DEVICE_LABELS = {
    "servidores": "Servidor",
    "switches": "Switch",
    "links": "Link",
    "firewalls": "Firewall",
    "vpns": "VPN",
    "aps": "Antena UniFi",
}


def _device_name(record, group, index):
    if not isinstance(record, dict):
        return f"{DEVICE_LABELS[group]} {index + 1}"
    for key in ("nome", "host", "hostname", "tunel", "name"):
        value = str(record.get(key) or "").strip()
        if value:
            return value[:120]
    return f"{DEVICE_LABELS[group]} {index + 1}"


def _device_id(regional_code, group, name, index):
    digest = sha256(
        f"{regional_code}\0{group}\0{name}\0{index}".encode("utf-8")
    ).hexdigest()[:14]
    return f"device-{digest}"


def build_neural_flow_payload(map_payload):
    """Expose names and relationships only; never copy operational records."""
    regionals = []
    devices = []
    connections = []
    category_totals = {group: 0 for group in DEVICE_GROUPS}

    for source in map_payload.get("regionais") or []:
        code = str(source.get("codigo") or "").strip()
        if not code:
            continue

        regional_device_ids = []
        regional_counts = {}
        for group in DEVICE_GROUPS:
            records = source.get(group) or []
            regional_counts[group] = len(records)
            category_totals[group] += len(records)
            for index, record in enumerate(records):
                name = _device_name(record, group, index)
                device_id = _device_id(code, group, name, index)
                devices.append({
                    "id": device_id,
                    "nome": name,
                    "tipo": group,
                    "regional_id": code,
                })
                regional_device_ids.append(device_id)
                connections.append({
                    "id": f"edge-{device_id}",
                    "origem": code,
                    "destino": device_id,
                    "tipo": group,
                })

        regionals.append({
            "id": code,
            "codigo": code,
            "nome": str(source.get("nome") or code)[:120],
            "uf": str(source.get("uf") or "").upper()[:2],
            "dispositivos": regional_device_ids,
            "totais": regional_counts,
        })

    regionals.sort(key=lambda item: (item["uf"], item["nome"]))
    return {
        "success": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_updated_at": (map_payload.get("fontes") or {}).get("atualizado_em"),
        "cache_status": map_payload.get("cache_status"),
        "resumo": {
            "regionais": len(regionals),
            "dispositivos": len(devices),
            "conexoes": len(connections),
            "categorias": sum(1 for total in category_totals.values() if total),
        },
        "categorias": category_totals,
        "regionais": regionals,
        "dispositivos": devices,
        "conexoes": connections,
    }
