"""Allowlisted, read-only access to Sentinel data already loaded in memory."""

from collections import Counter
from threading import RLock
import re
import unicodedata

from maintenance_status import apply_regional_maintenance
from regional_matching import find_regional_code


_LOCK = RLock()
_regionais_manager = None
_switches_manager = None


def configurar_ferramentas_sentinel(*, regionais_manager, switches_manager):
    """Inject existing managers without importing the Flask application."""
    global _regionais_manager, _switches_manager
    with _LOCK:
        _regionais_manager = regionais_manager
        _switches_manager = switches_manager


def _normalizar(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _regionais(allowed_regionals=None):
    if _regionais_manager is None:
        return {}
    _regionais_manager.recarregar_regionais()
    regionais = dict((_regionais_manager.regionais or {}).get("regionais") or {})
    if allowed_regionals is None:
        return regionais
    allowed = {str(code).strip().upper() for code in allowed_regionals}
    return {code: data for code, data in regionais.items() if str(code).strip().upper() in allowed}


def codigos_regionais():
    return list(_regionais())


def identificar_regional(mensagem, allowed_regionals=None):
    """Resolve a regional mentioned in free text using code or display name."""
    normalized_message = f" {_normalizar(mensagem)} "
    candidates = []
    for code, regional in _regionais(allowed_regionals).items():
        aliases = {
            _normalizar(code),
            _normalizar(str(code).replace("REG_", "")),
            _normalizar((regional or {}).get("nome")),
            _normalizar((regional or {}).get("descricao")),
        }
        aliases.discard("")
        for alias in aliases:
            if f" {alias} " in normalized_message:
                candidates.append((len(alias), code))
    return max(candidates, default=(0, None))[1]


def total_regionais(allowed_regionals=None):
    return len(_regionais(allowed_regionals))


def listar_nomes_regionais(limite=50, allowed_regionals=None):
    items = []
    for code, regional in sorted(_regionais(allowed_regionals).items()):
        items.append(str((regional or {}).get("nome") or code))
    return items[: max(0, int(limite))]


def _status_servidor(server):
    if server.get("ativo") is False:
        return "inativo"
    status = _normalizar(server.get("status"))
    if status in {"online", "offline", "warning", "inativo"}:
        return status
    return "desconhecido"


def resumo_servidores(codigo_regional=None, allowed_regionals=None):
    regionals = _regionais(allowed_regionals)
    selected = {codigo_regional: regionals.get(codigo_regional)} if codigo_regional else regionals
    statuses = Counter()
    for regional in selected.values():
        if not regional:
            continue
        for server in regional.get("servidores") or []:
            statuses[_status_servidor(server)] += 1
    return dict(statuses, total=sum(statuses.values()))


def _internet_links(regional):
    links = regional.get("links_internet_auto")
    if isinstance(links, list):
        return links
    return [
        link for link in (regional.get("links") or [])
        if _normalizar(link.get("tipo")) != "tunnel"
    ]


def _status_link(link):
    if link.get("ativo") is False or _normalizar(link.get("sla_status")) == "inactive":
        return "inativo"
    status = _normalizar(link.get("status"))
    return status if status in {"online", "offline", "inativo"} else "desconhecido"


def resumo_links(codigo_regional=None, allowed_regionals=None):
    regionals = _regionais(allowed_regionals)
    selected = {codigo_regional: regionals.get(codigo_regional)} if codigo_regional else regionals
    statuses = Counter()
    for regional in selected.values():
        if not regional:
            continue
        for link in _internet_links(regional):
            statuses[_status_link(link)] += 1
    return dict(statuses, total=sum(statuses.values()))


def _status_switch(switch):
    status = _normalizar(switch.get("status"))
    if status in {"online", "offline", "warning", "inativo"}:
        return status
    if status in {"nao encontrado", "erro"}:
        return "offline"
    return "desconhecido"


def _switches(codigo_regional=None, allowed_regionals=None):
    if _switches_manager is None:
        return []
    if codigo_regional:
        if allowed_regionals is not None and str(codigo_regional).strip().upper() not in {
            str(code).strip().upper() for code in allowed_regionals
        }:
            return []
        normalized_target = _normalizar(codigo_regional).replace("reg ", "")
        matches = []
        for regional, switches in (_switches_manager.regionais or {}).items():
            normalized_regional = _normalizar(regional).replace("regional ", "").replace("reg ", "")
            if normalized_regional == normalized_target:
                matches.extend(switches or [])
        return matches
    switches = []
    for code in _regionais(allowed_regionals):
        switches.extend(_switches(code))
    return switches


def resumo_switches(codigo_regional=None, allowed_regionals=None):
    statuses = Counter(_status_switch(item) for item in _switches(codigo_regional, allowed_regionals))
    return dict(statuses, total=sum(statuses.values()))


def alertas_switches_ativos(codigo_regional=None, limite=5, allowed_regionals=None):
    alerts = []
    for switch in _switches(codigo_regional, allowed_regionals):
        if _status_switch(switch) != "warning":
            continue
        alerts.append({
            "switch": str(switch.get("host") or switch.get("name") or "Switch"),
            "regional": str(switch.get("regional") or "N/A"),
            "alerta": str(switch.get("warning_resumo") or "Alerta ativo no Zabbix"),
        })
    return alerts[: max(0, int(limite))]


def nome_regional(codigo_regional, allowed_regionals=None):
    regional = _regionais(allowed_regionals).get(codigo_regional) or {}
    return str(regional.get("nome") or codigo_regional or "Regional")


def consultar_manutencoes_regionais(allowed_regionals=None):
    """Return a scoped, credential-free view of active regional maintenance."""
    regionals = _regionais(allowed_regionals)
    state = {
        code: {
            "nome": (regional or {}).get("nome") or code,
            "em_manutencao": False,
            "manutencoes": [],
        }
        for code, regional in regionals.items()
    }
    if _switches_manager is None or not hasattr(
        _switches_manager, "obter_manutencoes_ativas"
    ):
        return {"available": False, "total": 0, "regionals": []}

    try:
        maintenances = _switches_manager.obter_manutencoes_ativas(
            cache_seconds=60
        )
        apply_regional_maintenance(
            state,
            maintenances,
            lambda available, value: find_regional_code(
                available,
                value,
                _normalizar,
            ),
        )
    except Exception:
        return {"available": False, "total": 0, "regionals": []}

    visible = []
    for code, regional in sorted(state.items()):
        if not regional.get("em_manutencao"):
            continue
        windows = []
        for maintenance in regional.get("manutencoes") or []:
            windows.append({
                "name": _public_value(maintenance, "nome", limit=160),
                "description": _public_value(
                    maintenance, "descricao", limit=240
                ),
                "active_since": _public_value(
                    maintenance, "active_since", limit=40
                ),
                "active_till": _public_value(
                    maintenance, "active_till", limit=40
                ),
            })
        visible.append({
            "code": code,
            "name": _public_value(regional, "nome") or code,
            "in_maintenance": True,
            "maintenance_windows": windows,
        })
    return {"available": True, "total": len(visible), "regionals": visible}


REGIONAL_QUERY_SECTIONS = frozenset({"servidores", "links", "switches"})


def _public_value(record, *keys, limit=160):
    for key in keys:
        value = record.get(key)
        if value in (None, "") or isinstance(value, (dict, list, tuple, set)):
            continue
        return str(value).strip()[:limit]
    return ""


def _public_servers(regional):
    result = []
    for server in regional.get("servidores") or []:
        result.append({
            "name": _public_value(server, "nome", "id"),
            "ip": _public_value(server, "ip"),
            "function": _public_value(server, "funcao", "descricao"),
            "model": _public_value(server, "modelo"),
            "operating_system": _public_value(server, "sistema_operacional"),
            "status": _status_servidor(server),
            "last_check": _public_value(server, "ultima_verificacao", limit=80),
        })
    return result


def _public_links(regional):
    result = []
    for link in _internet_links(regional):
        result.append({
            "name": _public_value(link, "nome", "interface_monitorada", "interface"),
            "provider": _public_value(link, "provedor", "alias", "descricao"),
            "network": _public_value(link, "ip_exibicao", "ip"),
            "speed": _public_value(link, "velocidade"),
            "packet_loss_percent": _public_value(link, "packet_loss_percent"),
            "status": _status_link(link),
            "last_check": _public_value(link, "ultima_verificacao", limit=80),
        })
    return result


def _public_switches(codigo_regional, allowed_regionals):
    result = []
    for switch in _switches(codigo_regional, allowed_regionals):
        result.append({
            "name": _public_value(switch, "host", "nome", "hostname"),
            "ip": _public_value(switch, "ip"),
            "model": _public_value(switch, "modelo", "model"),
            "firmware": _public_value(switch, "firmware", "version"),
            "status": _status_switch(switch),
            "diagnostic": _public_value(switch, "warning_resumo", "status_reason"),
            "last_check": _public_value(switch, "ultima_verificacao", limit=80),
        })
    return result


def consultar_inventario_regional(
    *, codigo_regional=None, secoes=None, allowed_regionals=None
):
    """Return a closed, credential-free projection for the SofIA tools."""
    regionals = _regionais(allowed_regionals)
    maintenance = consultar_manutencoes_regionais(allowed_regionals)
    maintenance_by_code = {
        item["code"]: item
        for item in maintenance.get("regionals") or []
    }
    if not codigo_regional:
        return {
            "mode": "index",
            "source": "sentinel_inventory",
            "authoritative": True,
            "complete": True,
            "total": len(regionals),
            "returned": len(regionals),
            "maintenance": {
                "available": maintenance["available"],
                "total": maintenance["total"],
            },
            "regionals": [
                {
                    "code": code,
                    "name": _public_value(regional, "nome") or code,
                    "state": _public_value(regional, "uf", "estado", limit=40),
                    "in_maintenance": code in maintenance_by_code,
                    "maintenance_windows": (
                        maintenance_by_code.get(code, {}).get("maintenance_windows")
                        or []
                    ),
                }
                for code, regional in sorted(regionals.items())
            ],
        }

    normalized_code = str(codigo_regional).strip().upper()
    regional = regionals.get(normalized_code)
    if not regional:
        return None

    requested = {
        str(section).strip().lower()
        for section in (secoes or [])
        if str(section).strip()
    }
    invalid = requested - REGIONAL_QUERY_SECTIONS
    if invalid:
        raise ValueError("Secao regional nao permitida.")

    response = {
        "mode": "detail",
        "regional": {
            "code": normalized_code,
            "name": _public_value(regional, "nome") or normalized_code,
            "description": _public_value(regional, "descricao", limit=240),
            "state": _public_value(regional, "uf", "estado", limit=40),
            "in_maintenance": normalized_code in maintenance_by_code,
            "maintenance_windows": (
                maintenance_by_code.get(normalized_code, {}).get(
                    "maintenance_windows"
                ) or []
            ),
        },
        "summary": {
            "servers": resumo_servidores(normalized_code, allowed_regionals),
            "links": resumo_links(normalized_code, allowed_regionals),
            "switches": resumo_switches(normalized_code, allowed_regionals),
        },
    }
    if "servidores" in requested:
        response["servers"] = _public_servers(regional)
    if "links" in requested:
        response["links"] = _public_links(regional)
    if "switches" in requested:
        response["switches"] = _public_switches(normalized_code, allowed_regionals)
    return response

