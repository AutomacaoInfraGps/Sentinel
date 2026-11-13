"""Validate a read-only plan and render facts from scoped inventory results."""

from datetime import datetime, timezone

from regional_access import normalize_regional_code
from .operational_inventory import query_operational_inventory
from .map_alerts import BRASILIA_TZ, _parse_datetime


RESOURCE_LABELS = {
    "alerts": "registros de alerta", "firewalls": "firewalls", "licenses": "licenças",
    "links": "links", "vpns": "túneis VPN", "servers": "servidores", "aps": "APs",
    "switches": "switches", "wifi": "redes Wi-Fi", "regionals": "regionais autorizadas",
}
RESOURCE_SINGULAR_LABELS = {
    "alerts": "registro de alerta", "firewalls": "firewall", "licenses": "licença",
    "links": "link", "vpns": "túnel VPN", "servers": "servidor", "aps": "AP",
    "switches": "switch", "wifi": "rede Wi-Fi", "regionals": "regional autorizada",
}
FIELD_LABELS = {
    "name": "Nome", "regional": "Regional", "ip": "IP", "model": "Modelo",
    "firmware": "Firmware", "serial": "Serial", "status": "Estado", "ssid": "SSID",
    "provider": "Provedor", "interface": "Interface", "speed": "Velocidade",
    "packet_loss_percent": "Perda (%)", "tunnel": "Túnel", "remote_ip": "IP remoto",
    "function": "Função", "operating_system": "Sistema operacional", "site": "Site",
    "clients": "Clientes", "mac": "MAC", "band": "Banda", "diagnostic": "Diagnóstico",
    "firewall": "Firewall", "firewall_serial": "Serial do firewall",
    "expires_at": "Vencimento", "days_remaining": "Dias restantes",
    "category": "Categoria", "quantity": "Ocorrências", "last_check": "Verificado em",
}
STATUS_LABELS = {
    "online": "online", "offline": "offline", "warning": "em atenção",
    "inactive": "inativo", "maintenance": "em manutenção", "unknown": "desconhecido",
    "expiring": "a vencer", "expired": "expirado", "valid": "válido",
    "unavailable": "indisponível", "critical": "crítico", "high": "alto",
    "medium": "médio", "attention": "atenção", "important": "importante",
    "info": "informativo", "success": "normal",
}
DEFAULT_FIELDS = {
    "alerts": ["name", "regional", "quantity", "status"],
    "licenses": ["name", "regional", "firewall", "days_remaining"],
    "firewalls": ["name", "regional", "model", "firmware", "status"],
    "wifi": ["name", "ssid", "regional", "status"],
    "regionals": ["regional"],
}
MAX_RENDER_LENGTH = 7600


def _display(value):
    if value is None or value == "":
        return "não informado"
    return " ".join(str(value).split()).replace("**", "")[:240]


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("mode") != "query":
        raise ValueError("Plano de consulta inválido.")
    permitted = {"mode", "reply", "resource", "regional", "status", "search", "view", "fields", "limit", "offset"}
    if set(plan) - permitted or plan.get("resource") not in RESOURCE_LABELS:
        raise ValueError("Recurso de consulta inválido.")
    if plan.get("view", "list") not in {"count", "list", "detail"}:
        raise ValueError("Apresentação inválida.")
    for key in ("regional", "status", "search"):
        if not isinstance(plan.get(key, ""), str) or len(plan.get(key, "")) > 120:
            raise ValueError("Filtro de consulta inválido.")
    fields = plan.get("fields", [])
    if (not isinstance(fields, list) or len(fields) > 8
            or any(not isinstance(field, str) or field not in FIELD_LABELS for field in fields)):
        raise ValueError("Campos de consulta inválidos.")
    limit, offset = plan.get("limit", 20), plan.get("offset", 0)
    if (type(limit) is not int or not 1 <= limit <= 50
            or type(offset) is not int or not 0 <= offset <= 10000):
        raise ValueError("Paginação inválida.")
    return {"resource": plan["resource"], "regional": plan.get("regional", ""),
            "status": plan.get("status", ""), "search": plan.get("search", ""),
            "view": plan.get("view", "list"), "fields": list(dict.fromkeys(fields)),
            "limit": limit, "offset": offset}


def render_inventory(result, query):
    """Counts always use the complete filtered summary, never the visible page."""
    resource = query["resource"]
    count = result["summary"]["records"]
    label = RESOURCE_SINGULAR_LABELS[resource] if count == 1 else RESOURCE_LABELS[resource]
    scope = (f"na regional {_display(query['regional'])}" if query["regional"]
             else "nas regionais autorizadas")
    state = ""
    if query["status"]:
        status = query["status"]
        description = STATUS_LABELS.get(status, _display(status))
        state = " " + (description if status in {"online", "offline", "maintenance", "warning", "expiring"}
                       else f"com status {description}")
    lines = [f"Encontrei {count} {label}{state} {scope}." if count
             else f"Não encontrei {label}{state} {scope}."]
    if query["search"]:
        lines.append(f"A busca considerou o termo “{_display(query['search'])}”.")
    if resource == "alerts":
        lines.append(f"Esses registros somam {result['summary']['occurrences']} ocorrências.")
    if resource == "licenses":
        firewalls = result["summary"]["firewalls"]
        firewall_label = "firewall distinto" if firewalls == 1 else "firewalls distintos"
        lines.append(f"A consulta abrange {firewalls} {firewall_label}.")
    states = result["summary"]["by_status"]
    if query["view"] == "count" and states and not query["status"]:
        lines.append("Por estado, temos " + ", ".join(
            f"{quantity} " + (STATUS_LABELS[status] if status in {"online", "offline", "maintenance", "warning", "expiring"}
                             else f"com status {STATUS_LABELS.get(status, status)}")
            for status, quantity in sorted(states.items())
        ) + ".")
    fields = query["fields"] or DEFAULT_FIELDS.get(resource, ["name", "ip", "regional", "status"])
    identity_fields = ["regional"] if resource == "regionals" else ["name", "regional"]
    fields = list(dict.fromkeys([*identity_fields, *fields]))
    displayed = 0
    if query["view"] != "count":
        for record in result["records"]:
            parts = []
            for field in fields:
                value = record.get(field)
                if field == "status":
                    value = STATUS_LABELS.get(value, value)
                parts.append(_display(value) if field == "name" else f"{FIELD_LABELS[field]} — {_display(value)}")
            row = "- " + " | ".join(parts)
            # Reserve room for pagination and source warnings, including long names.
            if len("\n".join(lines)) + len(row) > MAX_RENDER_LENGTH - 700:
                break
            lines.append(row)
            displayed += 1
        if result["offset"] + displayed < count:
            lines.append(f"Lista parcial — exibidos {displayed} de {count} registros. "
                         f"Próximo deslocamento — {result['offset'] + displayed}.")
        elif result["offset"]:
            lines.append(f"Página iniciada no deslocamento {result['offset']}.")
    if result["data_gaps"]:
        lines.append(f"Há {len(result['data_gaps'])} lacunas de coleta. A contagem cobre somente os dados disponíveis.")
    if not result["fresh"]:
        updated = _parse_datetime(result["updated_at"])
        if updated:
            local_time = updated.astimezone(BRASILIA_TZ).strftime("%d/%m/%Y às %H:%M:%S")
            lines.append(f"Última atualização — {local_time} (horário de Brasília).")
        else:
            lines.append("Horário da última atualização não informado.")
    return "\n".join(lines), displayed


def execute_plan(plan, allowed_regionals, *, path=None, now=None):
    query = validate_plan(plan)
    if query["resource"] == "regionals":
        allowed = sorted({normalize_regional_code(code) for code in allowed_regionals})
        selected = normalize_regional_code(query["regional"]) if query["regional"] else ""
        if selected and selected not in allowed and f"REG_{selected}" in allowed:
            selected = f"REG_{selected}"
        if selected and selected not in allowed:
            raise PermissionError("Regional não encontrada.")
        if query["status"] or query["search"]:
            raise ValueError("Filtro indisponível para regionais.")
        codes = [selected] if selected else allowed
        result = {"summary": {"records": len(codes), "by_status": {}},
                  "records": [{"regional": code} for code in codes[query["offset"]:query["offset"] + query["limit"]]],
                  "offset": query["offset"], "data_gaps": [], "fresh": True,
                  "updated_at": (now or datetime.now(timezone.utc)).isoformat(),
                  "source": "sentinel_authorized_scope"}
    else:
        result = query_operational_inventory(
            resource=query["resource"], allowed_regionals=allowed_regionals,
            regional=query["regional"], status=query["status"], search=query["search"],
            detail_level="summary" if query["view"] == "count" else "list",
            limit=query["limit"], offset=query["offset"], path=path, now=now,
        )
    reply, displayed = render_inventory(result, query)
    next_offset = result["offset"] + displayed
    return {"reply": reply, "query": {"mode": "query", **query},
            "source": result["source"], "updated_at": result["updated_at"],
            "fresh": result["fresh"], "matched": result["summary"]["records"],
            "displayed": displayed,
            "next_offset": next_offset if query["view"] != "count" and next_offset < result["summary"]["records"] else None,
            "data_gaps_count": len(result["data_gaps"])}
