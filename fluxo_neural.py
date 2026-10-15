"""Sanitized topology projection for the Sentinel neural network view."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256


DEVICE_GROUPS = (
    "servidores", "switches", "links", "firewalls", "vpns", "aps", "redes_wifi",
)
DEVICE_LABELS = {
    "servidores": "Servidor",
    "switches": "Switch",
    "links": "Link",
    "firewalls": "Firewall",
    "vpns": "VPN",
    "aps": "Antena UniFi",
    "redes_wifi": "Rede Wi-Fi",
}
DEVICE_DETAIL_FIELDS = {
    "servidores": (
        ("IP", ("ip",)), ("Funcao", ("funcao", "descricao")),
        ("Modelo", ("modelo", "model")),
        ("Sistema operacional", ("sistema_operacional", "os")),
        ("Porta", ("porta", "port")),
        ("Tipo", ("tipo",)),
        ("Monitoramento", ("tipo_monitoramento", "monitoramento")),
        ("Status", ("status",)), ("Ativo", ("ativo",)),
        ("Tempo de resposta", ("tempo_resposta",)),
        ("Ultima verificacao", ("ultima_verificacao", "ultima_atualizacao_mapa")),
        ("Erro", ("erro",)),
    ),
    "switches": (
        ("Hostname", ("host", "hostname")), ("IP", ("ip",)),
        ("Modelo", ("modelo", "model")), ("Firmware", ("firmware", "version")),
        ("Fabricante", ("fabricante", "manufacturer", "vendor")),
        ("Serial", ("serial", "serial_number")), ("MAC", ("mac", "mac_address")),
        ("Portas", ("portas", "ports", "total_ports")),
        ("Uptime", ("uptime",)), ("Status", ("status",)),
        ("Diagnostico", ("warning_resumo", "status_reason", "descricao")),
        ("Ultima verificacao", ("ultima_verificacao", "ultima_atualizacao_mapa")),
    ),
    "links": (
        ("Interface", ("interface_monitorada", "interface", "nome")),
        ("Provedor", ("provedor", "alias", "descricao")),
        ("IP / Rede", ("ip_exibicao", "ip", "url")), ("Status", ("status",)),
        ("Velocidade", ("velocidade", "speed")),
        ("Perda de pacotes", ("packet_loss_percent", "perda_pacotes")),
        ("Modo", ("link_mode_status", "addressing_mode", "modo_verificacao")),
        ("IP publico", ("ip_publico_status", "ip_publico")),
        ("Prioridade", ("priority", "prioridade")),
        ("Origem", ("origem_sync", "regra_origem")),
        ("Latencia", ("latencia", "latency", "tempo_resposta")),
        ("Ultima verificacao", ("ultima_verificacao", "ultima_atualizacao_mapa")),
    ),
    "firewalls": (
        ("Modelo", ("modelo", "model", "descricao")),
        ("Hostname", ("hostname", "host", "nome")), ("IP", ("ip",)),
        ("Firmware", ("firmware", "version")), ("Serial", ("serial", "serial_number")),
        ("Status", ("status",)), ("Disponibilidade", ("status_disponibilidade",)),
        ("Licenca", ("licenca", "license_status", "subscription_status")),
        ("Vencimento", ("vencimento", "expiration_date")),
        ("Ultima verificacao", ("ultima_verificacao", "atualizado_em", "ultima_atualizacao_mapa")),
    ),
    "vpns": (
        ("Tunel", ("tunel", "nome")), ("IP remoto", ("remote_ip",)),
        ("Gateway", ("gateway",)), ("Interface", ("interface",)),
        ("IP local", ("local_ip", "source_ip")),
        ("Fase 1", ("phase1", "fase1")), ("Fase 2", ("phase2", "fase2")),
        ("Criptografia", ("encryption", "criptografia")),
        ("Status", ("status",)),
        ("Ultima verificacao", ("ultima_verificacao", "updated_at", "ultima_atualizacao_mapa")),
    ),
    "aps": (
        ("IP", ("ip",)), ("Site", ("site", "regional")),
        ("Modelo", ("modelo", "model", "modelo_codigo")),
        ("Firmware", ("firmware", "version")), ("Status", ("status",)),
        ("MAC", ("mac", "mac_address")),
        ("Canal", ("canal", "channel")), ("Radio", ("radio", "radio_band")),
        ("Clientes", ("clientes", "num_sta")), ("Uptime", ("uptime",)),
        ("Ultima verificacao", ("ultima_verificacao", "ultima_atualizacao_mapa")),
    ),
    "redes_wifi": (
        ("Rede", ("rede",)), ("Bandas", ("bandas",)),
        ("Transmitida por", ("transmissao",)),
        ("Seguranca", ("seguranca", "security")),
        ("Clientes", ("clientes", "num_sta")),
        ("Status", ("status", "ativo")),
    ),
}


def _detail_value(record, keys):
    for key in keys:
        value = record.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(item).strip() for item in value if str(item).strip())
        if isinstance(value, dict):
            continue
        text = str(value).strip()
        if text:
            return text[:240]
    return ""


def _device_details(record, group):
    if not isinstance(record, dict):
        return []
    details = []
    for label, keys in DEVICE_DETAIL_FIELDS.get(group, ()):
        value = _detail_value(record, keys)
        if value:
            details.append({"rotulo": label, "valor": value})
    return details


def _device_name(record, group, index):
    if not isinstance(record, dict):
        return f"{DEVICE_LABELS[group]} {index + 1}"
    if group == "links":
        interface = str(
            record.get("interface_monitorada")
            or record.get("nome")
            or record.get("interface")
            or ""
        ).strip()
        provider = str(
            record.get("provedor")
            or record.get("alias")
            or record.get("descricao")
            or ""
        ).strip()
        if interface and provider and provider.casefold() not in interface.casefold():
            return f"{interface} - {provider}"[:120]
        if interface or provider:
            return (interface or provider)[:120]

    keys_by_group = {
        "firewalls": ("modelo", "model", "descricao", "nome", "hostname", "host", "name"),
        "vpns": ("tunel", "nome", "name"),
        "switches": ("host", "nome", "hostname", "name"),
        "aps": ("nome", "name", "host", "hostname"),
        "redes_wifi": ("nome", "name", "ssid"),
    }
    for key in keys_by_group.get(group, ("nome", "host", "hostname", "name")):
        value = str(record.get(key) or "").strip()
        if value:
            return value[:120]
    return f"{DEVICE_LABELS[group]} {index + 1}"


def _device_id(regional_code, group, name, index):
    digest = sha256(
        f"{regional_code}\0{group}\0{name}\0{index}".encode("utf-8")
    ).hexdigest()[:14]
    return f"device-{digest}"


def build_neural_flow_payload(map_payload):
    """Expose names and relationships only; never copy operational records."""
    regionals = []
    devices = []
    connections = []
    category_totals = {group: 0 for group in DEVICE_GROUPS}

    for source in map_payload.get("regionais") or []:
        code = str(source.get("codigo") or "").strip()
        if not code:
            continue

        regional_device_ids = []
        regional_counts = {}
        for group in DEVICE_GROUPS:
            records = source.get(group) or []
            regional_counts[group] = len(records)
            category_totals[group] += len(records)
            for index, record in enumerate(records):
                name = _device_name(record, group, index)
                device_id = _device_id(code, group, name, index)
                device = {
                    "id": device_id,
                    "nome": name,
                    "tipo": group,
                    "regional_id": code,
                    "detalhes": _device_details(record, group),
                }
                if group == "redes_wifi":
                    detail_parts = [str(record.get("rede") or "").strip()]
                    broadcasting = record.get("transmissao") or []
                    if isinstance(broadcasting, str):
                        broadcasting = [broadcasting]
                    detail_parts.extend(str(item).strip() for item in broadcasting)
                    device["detalhe"] = " · ".join(
                        part for part in detail_parts if part
                    )[:160]
                devices.append(device)
                regional_device_ids.append(device_id)
                connections.append({
                    "id": f"edge-{device_id}",
                    "origem": code,
                    "destino": device_id,
                    "tipo": group,
                })

        regionals.append({
            "id": code,
            "codigo": code,
            "nome": str(source.get("nome") or code)[:120],
            "uf": str(source.get("uf") or "").upper()[:2],
            "descricao": str(source.get("descricao") or "")[:240],
            "status": str(source.get("status") or "")[:40],
            "ultima_atualizacao": str(
                source.get("ultima_atualizacao_mapa") or ""
            )[:80],
            "dispositivos": regional_device_ids,
            "totais": regional_counts,
        })

    regionals.sort(key=lambda item: (item["uf"], item["nome"]))
    return {
        "success": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_updated_at": (map_payload.get("fontes") or {}).get("atualizado_em"),
        "cache_status": map_payload.get("cache_status"),
        "resumo": {
            "regionais": len(regionals),
            "dispositivos": len(devices),
            "conexoes": len(connections),
            "categorias": sum(1 for total in category_totals.values() if total),
        },
        "categorias": category_totals,
        "regionais": regionals,
        "dispositivos": devices,
        "conexoes": connections,
    }
