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


def extract_unifi_items(payload):
    """Normalize legacy and v2 UniFi collection responses."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _normalize_band(value):
    text = _clean(value, 20).lower().replace(" ", "")
    if text in {"ng", "2g", "2.4g", "2.4ghz"}:
        return "2.4 GHz"
    if text in {"na", "5g", "5ghz"}:
        return "5 GHz"
    if text in {"6g", "6e", "6ghz"}:
        return "6 GHz"
    return _clean(value, 20)


def sanitize_ap_wifi_networks(aps):
    """Infer actively broadcast SSIDs from AP runtime data without credentials."""
    networks = {}
    for ap in aps or []:
        if not isinstance(ap, dict):
            continue
        ap_name = _clean(ap.get("name") or ap.get("hostname"))
        vap_entries = ap.get("vap_table") or ap.get("vaps") or []
        for vap in vap_entries:
            if not isinstance(vap, dict):
                continue
            name = _clean(vap.get("essid") or vap.get("name") or vap.get("ssid"))
            if not name:
                continue
            key = name.casefold()
            item = networks.setdefault(key, {
                "nome": name,
                "rede": "",
                "bandas": [],
                "transmissao": [],
                "ativo": True,
            })
            band = _normalize_band(vap.get("radio") or vap.get("radio_name") or vap.get("band"))
            if band and band not in item["bandas"]:
                item["bandas"].append(band)
            if ap_name and ap_name not in item["transmissao"]:
                item["transmissao"].append(ap_name)
    return sorted(networks.values(), key=lambda item: item["nome"].casefold())


def merge_wifi_networks(configured, observed):
    """Keep configured WLANs and enrich them with runtime AP observations."""
    merged = {item["nome"].casefold(): dict(item) for item in configured or [] if item.get("nome")}
    for runtime in observed or []:
        name = runtime.get("nome")
        if not name:
            continue
        key = name.casefold()
        if key not in merged:
            merged[key] = dict(runtime)
            continue
        target = merged[key]
        for field in ("bandas", "transmissao"):
            values = list(target.get(field) or [])
            for value in runtime.get(field) or []:
                if value not in values:
                    values.append(value)
            target[field] = values
    return sorted(merged.values(), key=lambda item: item["nome"].casefold())


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
