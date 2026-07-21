"""Deterministic, read-only orchestration for the SofIA MVP."""

from functools import lru_cache
from pathlib import Path
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


_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

_KNOWLEDGE_TOPICS = {
    "dashboard": {
        "file": "dashboard.md",
        "terms": ("dashboard", "painel", "tela", "sentinel"),
        "title": "Dashboard do Sentinel",
    },
    "regionais": {
        "file": "regionais.md",
        "terms": ("regional", "regionais"),
        "title": "Regionais",
    },
    "servidores": {
        "file": "servidores.md",
        "terms": ("servidor", "servidores", "vm", "vms"),
        "title": "Servidores e VMs",
    },
    "links": {
        "file": "links_internet.md",
        "terms": ("link", "links", "internet"),
        "title": "Links de Internet",
    },
    "switches": {
        "file": "switches.md",
        "terms": ("switch", "switches", "zabbix", "alerta", "alertas"),
        "title": "Switches e Zabbix",
    },
    "vpns": {
        "file": "vpns.md",
        "terms": ("vpn", "vpns", "ipsec"),
        "title": "VPNs e IPsec",
    },
    "seguranca": {
        "file": "seguranca.md",
        "terms": ("seguranca", "seguro", "permissao", "permissoes", "auditoria", "rbac", "ad"),
        "title": "Seguranca da SofIA",
    },
}


def _normalizar_mensagem(mensagem):
    texto = unicodedata.normalize("NFKD", str(mensagem or ""))
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _contem_termo(texto, *termos):
    tokens = set(texto.split())
    return any(termo in tokens for termo in termos)


def _quer_explicacao(texto):
    if _contem_termo(texto, "esta", "estao", "status", "offline", "online", "quantos", "quantas", "tem"):
        return False
    return _contem_termo(
        texto,
        "explica",
        "explique",
        "explicar",
        "como",
        "funciona",
        "funcionam",
        "que",
        "significa",
        "sobre",
        "ajuda",
        "duvida",
    )


@lru_cache(maxsize=16)
def _carregar_conhecimento(nome_arquivo):
    path = _KNOWLEDGE_DIR / nome_arquivo
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _extrair_secao(markdown, titulo):
    marcador = f"## {titulo}"
    inicio = markdown.find(marcador)
    if inicio < 0:
        return ""
    inicio = markdown.find("\n", inicio)
    if inicio < 0:
        return ""
    fim = markdown.find("\n## ", inicio + 1)
    if fim < 0:
        fim = len(markdown)
    return markdown[inicio:fim].strip()


def _limpar_markdown(texto):
    linhas = []
    in_code_block = False
    for linha in texto.splitlines():
        stripped = linha.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not stripped:
            continue
        stripped = stripped.lstrip("#").strip().replace("`", "")
        if stripped.startswith("- "):
            stripped = "- " + stripped[2:].strip()
        linhas.append(stripped)
    return "\n".join(linhas)


def _resposta_conhecimento(topico):
    config = _KNOWLEDGE_TOPICS.get(topico)
    if not config:
        return None

    markdown = _carregar_conhecimento(config["file"])
    if not markdown:
        return None

    objetivo = _limpar_markdown(_extrair_secao(markdown, "Objetivo"))
    comportamento = _limpar_markdown(
        _extrair_secao(markdown, "Comportamento Atual")
        or _extrair_secao(markdown, "Temas que a SofIA Pode Explicar")
        or _extrair_secao(markdown, "Estado Atual")
        or _extrair_secao(markdown, "Principio")
    )

    partes = [config["title"]]
    if objetivo:
        partes.append(objetivo)
    if comportamento:
        partes.append(comportamento)
    return "\n\n".join(partes)


def _resposta_ajuda_guiada():
    return (
        "Ainda nao entendi essa pergunta com seguranca.\n\n"
        "Hoje posso responder, por exemplo:\n"
        "- Quantas regionais temos?\n"
        "- Resumo da regional ABC\n"
        "- Como estao os servidores?\n"
        "- Como estao os links de internet?\n"
        "- Tem alerta de switch?\n"
        "- Me explica o dashboard\n"
        "- Como funciona a seguranca da SofIA?\n\n"
        "Por enquanto trabalho em modo somente leitura e nao executo acoes reais."
    )


def _identificar_topico_conhecimento(texto):
    for topico, config in _KNOWLEDGE_TOPICS.items():
        if _contem_termo(texto, *config["terms"]):
            return topico
    return None


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

    topico_conhecimento = _identificar_topico_conhecimento(msg)
    if topico_conhecimento == "seguranca":
        resposta = _resposta_conhecimento(topico_conhecimento)
        if resposta:
            return resposta

    if _quer_explicacao(msg):
        resposta = _resposta_conhecimento(topico_conhecimento) if topico_conhecimento else None
        if resposta:
            return resposta

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

    if _contem_termo(msg, "zabbix", "alerta", "alertas", "problema", "problemas"):
        alerts = alertas_switches_ativos(regional_code)
        if not alerts:
            scope = f" para {nome_regional(regional_code)}" if regional_code else ""
            return f"NÃ£o hÃ¡ alertas ativos de switches no cache do Zabbix{scope}."
        details = "; ".join(
            f"{item['switch']} ({item['regional']}): {item['alerta']}"
            for item in alerts
        )
        return f"Encontrei {len(alerts)} alerta(s) ativo(s) de switches: {details}."

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

    if _contem_termo(msg, "dashboard", "painel", "tela", "sentinel"):
        return _resposta_conhecimento("dashboard") or "Posso explicar as telas e os indicadores disponíveis no dashboard do Sentinel."

    return (
        _resposta_ajuda_guiada()
    )
