"""Sanitized topology projection for the Sentinel neural network view."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256


DEVICE_GROUPS = (
    "servidores", "switches", "links", "firewalls", "vpns", "aps", "redes_wifi",
)
DEVICE_LABELS = {
    "servidores": "Servidor",
    "switches": "Switch",
    "links": "Link",
    "firewalls": "Firewall",
    "vpns": "VPN",
    "aps": "Antena UniFi",
    "redes_wifi": "Rede Wi-Fi",
}


def _device_name(record, group, index):
    if not isinstance(record, dict):
        return f"{DEVICE_LABELS[group]} {index + 1}"
    if group == "links":
        interface = str(
            record.get("interface_monitorada")
            or record.get("nome")
            or record.get("interface")
            or ""
        ).strip()
        provider = str(
            record.get("provedor")
            or record.get("alias")
            or record.get("descricao")
            or ""
        ).strip()
        if interface and provider and provider.casefold() not in interface.casefold():
            return f"{interface} - {provider}"[:120]
        if interface or provider:
            return (interface or provider)[:120]

    keys_by_group = {
        "firewalls": ("hostname", "nome", "host", "name"),
        "vpns": ("tunel", "nome", "name"),
        "switches": ("host", "nome", "hostname", "name"),
        "aps": ("nome", "name", "host", "hostname"),
        "redes_wifi": ("nome", "name", "ssid"),
    }
    for key in keys_by_group.get(group, ("nome", "host", "hostname", "name")):
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
                device = {
                    "id": device_id,
                    "nome": name,
                    "tipo": group,
                    "regional_id": code,
                }
                if group == "redes_wifi":
                    device["detalhe"] = str(record.get("rede") or "")[:120]
                devices.append(device)
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
