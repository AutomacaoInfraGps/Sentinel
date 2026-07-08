"""Allowlisted, read-only access to Sentinel data already loaded in memory."""

from collections import Counter
from threading import RLock
import re
import unicodedata


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


def _regionais():
    if _regionais_manager is None:
        return {}
    _regionais_manager.recarregar_regionais()
    return dict((_regionais_manager.regionais or {}).get("regionais") or {})


def identificar_regional(mensagem):
    """Resolve a regional mentioned in free text using code or display name."""
    normalized_message = f" {_normalizar(mensagem)} "
    candidates = []
    for code, regional in _regionais().items():
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


def total_regionais():
    return len(_regionais())


def listar_nomes_regionais(limite=50):
    items = []
    for code, regional in sorted(_regionais().items()):
        items.append(str((regional or {}).get("nome") or code))
    return items[: max(0, int(limite))]


def _status_servidor(server):
    if server.get("ativo") is False:
        return "inativo"
    status = _normalizar(server.get("status"))
    if status in {"online", "offline", "warning", "inativo"}:
        return status
    return "desconhecido"


def resumo_servidores(codigo_regional=None):
    regionals = _regionais()
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


def resumo_links(codigo_regional=None):
    regionals = _regionais()
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


def _switches(codigo_regional=None):
    if _switches_manager is None:
        return []
    if codigo_regional:
        normalized_target = _normalizar(codigo_regional).replace("reg ", "")
        matches = []
        for regional, switches in (_switches_manager.regionais or {}).items():
            normalized_regional = _normalizar(regional).replace("regional ", "").replace("reg ", "")
            if normalized_regional == normalized_target:
                matches.extend(switches or [])
        return matches
    return list(_switches_manager.switches or [])


def resumo_switches(codigo_regional=None):
    statuses = Counter(_status_switch(item) for item in _switches(codigo_regional))
    return dict(statuses, total=sum(statuses.values()))


def alertas_switches_ativos(codigo_regional=None, limite=5):
    alerts = []
    for switch in _switches(codigo_regional):
        if _status_switch(switch) != "warning":
            continue
        alerts.append({
            "switch": str(switch.get("host") or switch.get("name") or "Switch"),
            "regional": str(switch.get("regional") or "N/A"),
            "alerta": str(switch.get("warning_resumo") or "Alerta ativo no Zabbix"),
        })
    return alerts[: max(0, int(limite))]


def nome_regional(codigo_regional):
    regional = _regionais().get(codigo_regional) or {}
    return str(regional.get("nome") or codigo_regional or "Regional")

