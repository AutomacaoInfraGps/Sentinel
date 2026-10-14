"""Public projection of Sentinel map data for the neural network view."""

from __future__ import annotations

from datetime import datetime, timezone


DEVICE_GROUPS = ("servidores", "switches", "links", "aps", "vpns", "firewalls")
PUBLIC_TOTAL_SUFFIXES = (
    "online", "offline", "warning", "inativo", "maintenance", "ok", "alerta",
)


def _public_totals(regional):
    source = regional.get("totais") or {}
    totals = {}
    for group in DEVICE_GROUPS:
        group_totals = {}
        for suffix in PUBLIC_TOTAL_SUFFIXES:
            value = source.get(f"{group}_{suffix}", 0)
            if isinstance(value, (int, float)):
                group_totals[suffix] = int(value)
        if group == "firewalls":
            group_totals["total"] = sum(
                group_totals.get(key, 0)
                for key in ("ok", "alerta", "inativo", "maintenance")
            )
        else:
            group_totals["total"] = sum(
                group_totals.get(key, 0)
                for key in ("online", "offline", "warning", "inativo", "maintenance")
            )
        totals[group] = group_totals
    return totals


def _connection_status(totals):
    if totals.get("offline", 0) > 0:
        return "offline"
    if totals.get("warning", 0) > 0 or totals.get("alerta", 0) > 0:
        return "warning"
    if totals.get("online", 0) > 0 or totals.get("ok", 0) > 0:
        return "online"
    return "unknown"


def build_neural_flow_payload(map_payload):
    """Return only non-sensitive aggregate fields needed by the canvas."""
    regionals = []
    connections = []

    for source in map_payload.get("regionais") or []:
        code = str(source.get("codigo") or "").strip()
        if not code:
            continue
        totals = _public_totals(source)
        alert_count = sum(
            values.get("alerta", 0)
            if values.get("alerta", 0)
            else values.get("offline", 0) + values.get("warning", 0)
            for values in totals.values()
        )
        regionals.append({
            "id": code,
            "codigo": code,
            "nome": str(source.get("nome") or code),
            "uf": str(source.get("uf") or "").upper(),
            "status": "alert" if alert_count else "online",
            "alertas": alert_count,
            "totais": totals,
            "ativos": sum(
                values.get("online", 0) + values.get("ok", 0)
                for values in totals.values()
            ),
        })

        for group in ("vpns", "links"):
            count = totals[group]["total"]
            if count:
                connections.append({
                    "id": f"sentinel-core:{code}:{group}",
                    "origem": "sentinel-core",
                    "destino": code,
                    "tipo": group,
                    "quantidade": count,
                    "status": _connection_status(totals[group]),
                })

    regionals.sort(key=lambda item: (item["uf"], item["nome"]))
    summary = {
        "regionais": len(regionals),
        "com_alerta": sum(1 for item in regionals if item["status"] == "alert"),
        "conexoes": sum(item["quantidade"] for item in connections),
        "ativos": sum(item["ativos"] for item in regionals),
    }
    return {
        "success": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_updated_at": (map_payload.get("fontes") or {}).get("atualizado_em"),
        "cache_status": map_payload.get("cache_status"),
        "hub": {
            "id": "sentinel-core",
            "nome": "Sentinel",
            "tipo": "core",
            "status": "alert" if summary["com_alerta"] else "online",
        },
        "resumo": summary,
        "regionais": regionals,
        "conexoes": connections,
    }
