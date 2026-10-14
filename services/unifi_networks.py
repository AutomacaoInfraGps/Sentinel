"""Safe projection helpers for UniFi wireless networks."""

from __future__ import annotations


def _clean(value, limit=120):
    return str(value or "").strip()[:limit]


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return bool(value)


def sanitize_site_wifi_networks(wlans, networks, ap_groups=None):
    """Return WLAN metadata without credentials, keys, MACs or internal payloads."""
    network_by_id = {
        str(item.get("_id") or ""): item
        for item in (networks or [])
        if isinstance(item, dict) and item.get("_id")
    }
    ap_group_by_id = {
        str(item.get("_id") or ""): _clean(item.get("name"))
        for item in (ap_groups or [])
        if isinstance(item, dict) and item.get("_id")
    }
    result = []
    seen = set()

    for wlan in wlans or []:
        if not isinstance(wlan, dict):
            continue
        name = _clean(wlan.get("name") or wlan.get("essid"))
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())

        network = network_by_id.get(str(wlan.get("networkconf_id") or ""), {})
        network_name = _clean(network.get("name"))
        vlan = _clean(network.get("vlan"), 12)
        if network_name and vlan and vlan != "0":
            network_name = f"{network_name} ({vlan})"

        bands = wlan.get("wlan_bands") or wlan.get("wlan_band") or []
        if isinstance(bands, str):
            bands = [bands]
        clean_bands = [_clean(band, 20) for band in bands if _clean(band, 20)]
        group_ids = wlan.get("ap_group_ids") or []
        if isinstance(group_ids, str):
            group_ids = [group_ids]
        broadcasting = [
            ap_group_by_id[str(group_id)]
            for group_id in group_ids
            if ap_group_by_id.get(str(group_id))
        ]

        result.append({
            "nome": name,
            "rede": network_name,
            "bandas": clean_bands,
            "transmissao": broadcasting,
            "ativo": _as_bool(wlan.get("enabled")),
        })

    return sorted(result, key=lambda item: item["nome"].casefold())
