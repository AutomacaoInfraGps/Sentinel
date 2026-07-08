"""Deterministic, read-only orchestration for the SofIA MVP."""

import re
import unicodedata

from .tools_sentinel import (
    alertas_switches_ativos,
    identificar_regional,
    nome_regional,
    resumo_links,
    resumo_servidores,
    resumo_switches,
    total_regionais,
)

SOFIA_INITIAL_REPLY = (
    "Olá, eu sou a SofIA, assistente virtual do Sentinel. Como posso te ajudar?"
)


def _normalizar_mensagem(mensagem):
    texto = unicodedata.normalize("NFKD", str(mensagem or ""))
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _contem_termo(texto, *termos):
    tokens = set(texto.split())
    return any(termo in tokens for termo in termos)


def _formatar_status(resumo, labels):
    parts = [f"{resumo.get('total', 0)} no total"]
    for key, label in labels:
        value = resumo.get(key, 0)
        if value:
            parts.append(f"{value} {label}")
    return ", ".join(parts)


def _resumo_regional(codigo):
    regional = nome_regional(codigo)
    servidores = _formatar_status(
        resumo_servidores(codigo),
        (("online", "online"), ("offline", "offline"), ("warning", "em warning"), ("inativo", "inativos"), ("desconhecido", "sem status")),
    )
    links = _formatar_status(
        resumo_links(codigo),
        (("online", "online"), ("offline", "offline"), ("inativo", "inativos"), ("desconhecido", "sem status")),
    )
    switches = _formatar_status(
        resumo_switches(codigo),
        (("online", "online"), ("offline", "offline"), ("warning", "em warning"), ("inativo", "inativos"), ("desconhecido", "sem status")),
    )
    return f"Resumo da {regional}: servidores: {servidores}; links de internet: {links}; switches: {switches}."


def processar_mensagem_sofia(*, usuario, mensagem):
    """Classify an allowed topic without invoking tools or external models."""
    del usuario
    msg = _normalizar_mensagem(mensagem)
    regional_code = identificar_regional(msg)

    if _contem_termo(msg, "ola", "oi", "bom", "boa"):
        return SOFIA_INITIAL_REPLY

    if regional_code and not _contem_termo(msg, "servidor", "servidores", "vm", "vms", "switch", "switches", "link", "links", "vpn", "vpns", "ipsec", "zabbix", "alerta", "alertas"):
        return _resumo_regional(regional_code)

    if _contem_termo(msg, "regional", "regionais") and not _contem_termo(
        msg,
        "servidor", "servidores", "vm", "vms",
        "switch", "switches", "link", "links",
        "vpn", "vpns", "ipsec", "zabbix",
        "alerta", "alertas", "problema", "problemas",
    ):
        return f"O Sentinel possui {total_regionais()} regionais cadastradas. Você pode informar o nome de uma regional para consultar o resumo."

    if _contem_termo(msg, "servidor", "servidores", "vm", "vms"):
        summary = resumo_servidores(regional_code)
        scope = f" na {nome_regional(regional_code)}" if regional_code else ""
        return "Servidores" + scope + ": " + _formatar_status(
            summary,
            (("online", "online"), ("offline", "offline"), ("warning", "em warning"), ("inativo", "inativos"), ("desconhecido", "sem status")),
        ) + "."

    if _contem_termo(msg, "switch", "switches"):
        summary = resumo_switches(regional_code)
        scope = f" na {nome_regional(regional_code)}" if regional_code else ""
        return "Switches" + scope + ": " + _formatar_status(
            summary,
            (("online", "online"), ("offline", "offline"), ("warning", "em warning"), ("inativo", "inativos"), ("desconhecido", "sem status")),
        ) + "."

    if _contem_termo(msg, "link", "links"):
        summary = resumo_links(regional_code)
        scope = f" na {nome_regional(regional_code)}" if regional_code else ""
        return "Links de internet" + scope + ": " + _formatar_status(
            summary,
            (("online", "online"), ("offline", "offline"), ("inativo", "inativos"), ("desconhecido", "sem status")),
        ) + "."

    if _contem_termo(msg, "vpn", "vpns", "ipsec"):
        return "A consulta real de VPNs ainda não está habilitada nesta versão da SofIA."

    if _contem_termo(msg, "zabbix", "alerta", "alertas", "problema", "problemas"):
        alerts = alertas_switches_ativos(regional_code)
        if not alerts:
            scope = f" para {nome_regional(regional_code)}" if regional_code else ""
            return f"Não há alertas ativos de switches no cache do Zabbix{scope}."
        details = "; ".join(
            f"{item['switch']} ({item['regional']}): {item['alerta']}"
            for item in alerts
        )
        return f"Encontrei {len(alerts)} alerta(s) ativo(s) de switches: {details}."

    if _contem_termo(msg, "dashboard", "painel", "tela", "sentinel"):
        return "Posso explicar as telas e os indicadores disponíveis no dashboard do Sentinel."

    return (
        "No momento posso te ajudar com regionais, servidores, switches, "
        "links, VPNs, Zabbix e dashboard do Sentinel."
    )
