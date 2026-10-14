"""Apply the latest safe UniFi WLAN inventory to a cached map payload."""

from __future__ import annotations


def overlay_wifi_networks(map_payload, unifi_payload, resolve_regional):
    regionals = map_payload.get("regionais") or []
    sites = unifi_payload.get("sites") or []
    wifi_sites = [
        site for site in sites
        if isinstance(site, dict) and isinstance(site.get("redes_wifi"), list)
    ]
    if not wifi_sites:
        return {"available": False, "networks": 0, "mapped": 0}

    by_code = {
        str(regional.get("codigo") or ""): regional
        for regional in regionals
        if isinstance(regional, dict) and regional.get("codigo")
    }
    for regional in by_code.values():
        regional["redes_wifi"] = []

    unmapped = map_payload.setdefault("unmapped", {})
    unmapped["redes_wifi"] = []
    total = 0
    mapped = 0

    for site in wifi_sites:
        site_name = site.get("nome") or site.get("name") or site.get("id")
        code = resolve_regional(by_code, site_name)
        regional = by_code.get(code)
        for network in site.get("redes_wifi") or []:
            if not isinstance(network, dict):
                continue
            total += 1
            bands = ", ".join(str(item) for item in network.get("bandas") or [])
            projected = {
                "nome": network.get("nome") or "Rede Wi-Fi",
                "rede": network.get("rede") or "",
                "transmissao": network.get("transmissao") or [],
                "descricao": bands,
                "status": "online" if network.get("ativo", True) else "inativo",
            }
            if regional is None:
                projected["regional"] = site_name or "SEM_REGIONAL"
                unmapped["redes_wifi"].append(projected)
                continue
            regional["redes_wifi"].append(projected)
            mapped += 1

    for regional in by_code.values():
        totals = regional.setdefault("totais", {})
        totals["redes_wifi"] = len(regional["redes_wifi"])

    return {"available": True, "networks": total, "mapped": mapped}
