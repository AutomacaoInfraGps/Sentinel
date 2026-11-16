"""Count operational source coverage without exporting records or credentials."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "mapa_consolidado": "output/mapa_monitoramento_cache.json",
    "switches_zabbix": "output/switches_status_cache.json",
    "unifi": "data/unifi.json",
    "servidores_dashboard": "output/dados_dashboard.json",
    "estrutura_regionais": "estrutura_regionais.json",
}
GROUPS = ("servidores", "switches", "links", "aps", "vpns", "redes_wifi", "firewalls")
IDENTIFIERS = ("id", "hostid", "serial", "mac", "nome", "host", "hostname", "tunel")
FIELDS = (*IDENTIFIERS, "ip", "modelo", "model", "firmware", "version", "status",
          "ultima_verificacao", "updated_at", "timestamp", "interface", "interface_monitorada",
          "remote_ip", "gateway", "site", "regional", "funcao", "tipo", "sistema_operacional",
          "em_manutencao", "clientes", "ssid", "rede", "provedor", "ativo")


def _present(value):
    return (value is not None and not isinstance(value, (dict, list, bool))
            and (not isinstance(value, str) or bool(value.strip())))


def _time_kind(value):
    if value is None or value == "":
        return "ausente"
    if not isinstance(value, str):
        return "formato_nao_iso"
    try:
        if "T" not in value and " " not in value:
            return "formato_nao_iso"
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "com_fuso" if parsed.utcoffset() is not None else "sem_fuso"
    except ValueError:
        return "formato_nao_iso"


def _publication(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("cache_atualizado_em", "timestamp", "atualizado_em", "updated_at"):
        if payload.get(key) is not None:
            return payload[key]
    sources = payload.get("fontes")
    return sources.get("atualizado_em") if isinstance(sources, dict) else None


def _stats(scoped_records):
    fields, times = Counter(), Counter()
    identifiers = {key: Counter() for key in IDENTIFIERS}
    invalid = 0
    count = 0
    statuses = 0
    for scope, item in scoped_records:
        if not isinstance(item, dict):
            invalid += 1
            continue
        count += 1
        for key in FIELDS:
            if key in item and item[key] is not None and item[key] != "":
                fields[key] += 1
        if _present(item.get("status")):
            statuses += 1
        timestamp = next((item[key] for key in ("ultima_verificacao", "updated_at", "timestamp")
                          if item.get(key) is not None and item[key] != ""), None)
        times[_time_kind(timestamp)] += 1
        for key, counts in identifiers.items():
            if _present(item.get(key)):
                counts[(scope, str(item[key]).strip().casefold())] += 1
    return {
        "registros": count, "registros_invalidos": invalid,
        "com_status": statuses, "horarios_observacao": dict(times),
        "campos_conhecidos_presentes": dict(sorted(fields.items())),
        "candidatos_identidade_por_regional": {
            key: {"registros_com_valor": sum(values.values()),
                  "valores_repetidos": sum(n > 1 for n in values.values()),
                  "registros_excedentes": sum(n - 1 for n in values.values())}
            for key, values in identifiers.items() if values
        },
    }


def audit_map(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("regionais"), list):
        return {"estrutura_valida": False}
    regionals = payload["regionais"]
    valid = [entry for entry in regionals if isinstance(entry, dict)
             and isinstance(entry.get("codigo"), str) and entry["codigo"].strip()]
    codes = Counter(entry["codigo"].strip().upper() for entry in valid)
    categories = {}
    for group in GROUPS:
        records, missing, malformed, empty = [], 0, 0, 0
        for regional in valid:
            if group not in regional:
                missing += 1
            elif not isinstance(regional[group], list):
                malformed += 1
            else:
                empty += not regional[group]
                records.extend((regional["codigo"].strip().upper(), item) for item in regional[group])
        unmapped = payload.get("unmapped")
        unmapped_items = unmapped.get(group) if isinstance(unmapped, dict) else None
        categories[group] = {
            **_stats(records), "regionais_sem_categoria": missing,
            "regionais_com_lista_vazia": empty, "listas_invalidas": malformed,
            "sem_vinculo_regional": len(unmapped_items) if isinstance(unmapped_items, list) else None,
        }
    return {"estrutura_valida": len(valid) == len(regionals) and not any(n > 1 for n in codes.values()),
            "regionais": len(valid), "codigos_repetidos": sum(n > 1 for n in codes.values()),
            "categorias": categories}


def audit_sources(root=PROJECT_ROOT):
    report = {"modo": "auditoria_somente_leitura_sem_banco", "fontes": {}}
    for source, relative in SOURCES.items():
        path = Path(root) / relative
        if not path.is_file():
            report["fontes"][source] = {"situacao": "ausente"}
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError):
            report["fontes"][source] = {"situacao": "leitura_ou_json_invalido"}
            continue
        info = {"situacao": "lido", "publicacao": _time_kind(_publication(payload))}
        if source == "mapa_consolidado":
            info.update(audit_map(payload))
        elif source == "switches_zabbix":
            if isinstance(payload, dict):
                info["registros"] = len(payload)
                info["valores_objeto"] = sum(isinstance(item, dict) for item in payload.values())
            else:
                info["estrutura_valida"] = False
        elif source == "unifi":
            if isinstance(payload, dict):
                for group in ("aps", "sites"):
                    items = payload.get(group)
                    info[group] = len(items) if isinstance(items, list) else None
            else:
                info["estrutura_valida"] = False
        else:
            entries = payload.get("regionais") if isinstance(payload, dict) else None
            info["regionais_no_envelope"] = len(entries) if isinstance(entries, (dict, list)) else None
        report["fontes"][source] = info
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true", help="Exibe somente cobertura e horarios.")
    args = parser.parse_args(argv)
    report = audit_sources()
    if args.summary:
        for info in report["fontes"].values():
            for category in info.get("categorias", {}).values():
                category.pop("campos_conhecidos_presentes", None)
                category.pop("candidatos_identidade_por_regional", None)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
