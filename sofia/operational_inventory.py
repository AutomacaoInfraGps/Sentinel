"""Scoped operational projections of the Sentinel snapshot, never arbitrary JSON access."""

from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

from regional_access import normalize_regional_code
from .map_alerts import BRASILIA_TZ, MAP_ALERT_CACHE, SEVERITY_MAP, _parse_datetime


RESOURCES = {
    "alerts": "alertas", "firewalls": "firewalls", "licenses": "firewalls",
    "links": "links", "vpns": "vpns", "servers": "servidores",
    "aps": "aps", "switches": "switches", "wifi": "redes_wifi",
}
STATUSES = frozenset({
    "online", "offline", "warning", "inactive", "maintenance", "unknown",
    "expiring", "expired", "valid", "unavailable",
    "critical", "high", "medium", "attention", "important", "info", "success",
})
FIELDS = {
    "name": ("nome", "name", "hostname", "host", "tunel"),
    "ip": ("ip", "ip_exibicao", "remote_ip"),
    "model": ("modelo", "model", "platform_str"),
    "last_check": ("ultima_verificacao", "updated_at"),
}
EXTRA_FIELDS = {
    "firewalls": {"firmware": ("firmware",), "serial": ("serial",),
                  "availability": ("status_disponibilidade",)},
    "servers": {"function": ("funcao", "descricao"), "operating_system": ("sistema_operacional",)},
    "switches": {"firmware": ("firmware", "version"), "diagnostic": ("warning_resumo", "status_reason")},
    "links": {"provider": ("provedor", "alias"), "interface": ("interface_monitorada", "interface"),
              "speed": ("velocidade", "speed"), "packet_loss_percent": ("packet_loss_percent",)},
    "vpns": {"tunnel": ("tunel", "nome"), "interface": ("interface",), "remote_ip": ("remote_ip", "gateway")},
    "aps": {"site": ("site",), "clients": ("clientes",), "mac": ("mac",)},
    "wifi": {"ssid": ("ssid", "rede", "nome"), "band": ("banda", "band"), "clients": ("clientes",)},
}


class OperationalSnapshotError(RuntimeError):
    """Operational source is unavailable or malformed; never interpret as zero."""


def _text(record, *keys):
    for key in keys:
        value = record.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return str(value).strip()[:240] or None
    return None


def _integer(value):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if -100000 <= result <= 100000 else None


def _status(value):
    value = str(value or "").strip().lower()
    aliases = {"up": "online", "down": "offline", "ok": "online",
               "inativo": "inactive", "indisponivel": "unavailable", "manutencao": "maintenance"}
    value = aliases.get(value, value)
    return value if value in STATUSES else "unknown"


def _expiry(value):
    """Preserve date-only precision; convert Unix instants without guessing a date."""
    value = str(value or "").strip()
    if not value:
        return None, None
    try:
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            stamp = float(value)
            if stamp <= 0:
                return None, None
            moment = datetime.fromtimestamp(stamp, timezone.utc)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat(), None
        elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
            return datetime.strptime(value, "%d/%m/%Y").date().isoformat(), None
        else:
            moment = _parse_datetime(value)
            if moment is None:
                return None, None
        return moment.astimezone(timezone.utc).isoformat(), moment.astimezone(BRASILIA_TZ).isoformat()
    except (ValueError, OverflowError, OSError):
        return None, None


def _license(record, firewall, code, maintenance):
    unavailable = record.get("status_indisponivel") is True or _status(record.get("status")) in {"unavailable", "offline"}
    expired = record.get("notificacao_expirada") is True
    expiring = record.get("notificacao_critica") is True or record.get("alerta_vencimento") is True
    expiry, expiry_brasilia = _expiry(_text(record, "expiracao", "data_expiracao", "expires_at"))
    if unavailable:
        status = "unavailable"
    elif expired:
        status = "expired"
    elif expiring:
        status = "expiring"
    else:
        status = "valid" if expiry else "unknown"
    return {
        "regional": code, "firewall": _text(firewall, "nome", "hostname", "name"),
        "firewall_serial": _text(firewall, "serial"),
        "name": _text(record, "nome", "tipo_licenca", "tipo"),
        "status": status, "expires_at": expiry,
        "expires_at_brasilia": expiry_brasilia,
        "days_remaining": None if unavailable or not expiry else _integer(record.get("dias_restantes")),
        "last_check": _text(firewall, "ultima_verificacao", "updated_at"),
        "in_maintenance": maintenance,
    }


def query_operational_inventory(*, resource, allowed_regionals, regional=None,
                                status=None, detail_level="list", limit=20, offset=0,
                                expires_within_days=None, search=None, path=None, now=None):
    """Filter first, then summarize and paginate explicit non-secret fields."""
    if resource not in RESOURCES or detail_level not in {"summary", "list", "detail"}:
        raise ValueError("Recurso ou nivel de detalhe nao permitido.")
    if search is not None and (not isinstance(search, str) or len(search) > 120):
        raise ValueError("Pesquisa de inventario invalida.")
    search = str(search or "").strip().casefold()
    status = str(status or "").strip().lower() or None
    if status and status not in STATUSES:
        raise ValueError("Filtro de status nao permitido.")
    if resource == "alerts" and status and status not in {*SEVERITY_MAP.values(), "unknown"}:
        raise ValueError("Filtro de alertas deve usar uma severidade disponivel no mapa.")
    if isinstance(limit, bool) or isinstance(offset, bool) or not isinstance(limit, int) or not isinstance(offset, int):
        raise ValueError("Limite e deslocamento devem ser inteiros.")
    if not 1 <= limit <= 50 or not 0 <= offset <= 10000:
        raise ValueError("Limite ou deslocamento fora do intervalo permitido.")
    if expires_within_days is not None and (
        resource != "licenses" or isinstance(expires_within_days, bool)
        or not isinstance(expires_within_days, int) or not 0 <= expires_within_days <= 3660
    ):
        raise ValueError("Prazo de vencimento invalido.")
    if not isinstance(allowed_regionals, (list, tuple, set, frozenset)) or len(allowed_regionals) > 200:
        raise ValueError("Escopo regional invalido.")
    allowed = {normalize_regional_code(code) for code in allowed_regionals if isinstance(code, str) and code.strip()}
    selected = normalize_regional_code(regional) if regional else None
    if selected and selected not in allowed and f"REG_{selected}" in allowed:
        selected = f"REG_{selected}"
    if selected and selected not in allowed:
        raise PermissionError("Regional nao encontrada no escopo autorizado.")
    payload = json.loads(Path(path or MAP_ALERT_CACHE).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("regionais"), list):
        raise OperationalSnapshotError("Snapshot operacional invalido.")
    updated_at = payload.get("cache_atualizado_em") or (payload.get("fontes") or {}).get("atualizado_em")
    observed = _parse_datetime(updated_at)
    reference = now or datetime.now(timezone.utc)
    age = max(0, int((reference - observed).total_seconds())) if observed else None
    ttl = max(1, int(payload.get("cache_ttl_segundos") or 300))
    records, gaps = [], []
    for entry in payload["regionais"]:
        if not isinstance(entry, dict):
            raise OperationalSnapshotError("Regional invalida no snapshot.")
        code = normalize_regional_code(entry.get("codigo"))
        if code not in allowed or (selected and code != selected):
            continue
        maintenance = bool(entry.get("em_manutencao"))
        if RESOURCES[resource] not in entry:
            gaps.append({"regional": code, "reason": "resource_not_collected"})
        raw_records = entry.get(RESOURCES[resource]) or []
        if not isinstance(raw_records, list):
            raise OperationalSnapshotError("Inventario invalido no snapshot.")
        for record in raw_records:
            if not isinstance(record, dict):
                continue
            if resource == "licenses":
                licenses = record.get("licencas")
                if not isinstance(licenses, list) or not licenses:
                    gaps.append({"regional": code, "firewall": _text(record, "nome", "hostname"),
                                 "reason": "license_details_unavailable"})
                    continue
                items = [_license(lic, record, code, maintenance) for lic in licenses if isinstance(lic, dict)]
            elif resource == "alerts":
                if maintenance:
                    continue
                quantity = _integer(record.get("quantidade"))
                if quantity is None or quantity < 1:
                    continue
                severity = SEVERITY_MAP.get(record.get("severidade"), "unknown")
                items = [{"regional": code, "name": _text(record, "descricao", "tipo"),
                          "category": _text(record, "tipo"), "quantity": quantity, "status": severity}]
            else:
                item = {key: _text(record, *keys) for key, keys in {**FIELDS, **EXTRA_FIELDS.get(resource, {})}.items()}
                item.update(regional=code, status=_status(record.get("status")), in_maintenance=maintenance)
                items = [item]
            records.extend(item for item in items
                           if (not status or item["status"] == status)
                           and (not search or any(search in str(value).casefold() for value in item.values() if value is not None))
                           and (expires_within_days is None or (
                               item["days_remaining"] is not None
                               and 0 <= item["days_remaining"] <= expires_within_days
                           )))

    records.sort(key=lambda item: (item["regional"], item.get("firewall") or "", item.get("name") or ""))
    regional_counts = Counter(item["regional"] for item in records)
    status_counts = Counter(item["status"] for item in records)
    summary = {"records": len(records), "regionals": len(regional_counts), "by_status": dict(status_counts)}
    if resource == "alerts":
        summary["occurrences"] = sum(item["quantity"] for item in records)
    if resource == "licenses":
        summary["licenses"] = len(records)
        summary["firewalls"] = len({(item["regional"], item["firewall_serial"] or item["firewall"]) for item in records})
    visible = [] if detail_level == "summary" else records[offset:offset + limit]
    return {
        "source": "sentinel_operational_snapshot", "resource": resource,
        "detail_level": detail_level, "updated_at": updated_at,
        "fresh": age is not None and age <= ttl, "age_seconds": age,
        "summary": summary,
        "regionals": [{"code": code, "records": count} for code, count in sorted(regional_counts.items())],
        "records": visible, "returned": len(visible), "available": len(records),
        "offset": offset, "limit": limit,
        "truncated": detail_level != "summary" and offset + len(visible) < len(records),
        "details_omitted": detail_level == "summary" and bool(records),
        "data_gaps": gaps,
    }
