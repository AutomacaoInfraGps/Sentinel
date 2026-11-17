"""Audit native UniFi AP identity coverage without network, database or secrets."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import ipaddress
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object)


def _time_kind(value):
    if value is None or value == '':
        return 'ausente'
    if not isinstance(value, str) or not re.search(r'\d[T ]\d', value):
        return 'invalido_ou_nao_iso'
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return 'com_fuso' if parsed.utcoffset() is not None else 'sem_fuso'
    except ValueError:
        return 'invalido_ou_nao_iso'


def _mac(value):
    value = _text(value).lower()
    if re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', value):
        compact = value.replace(':', '')
    elif re.fullmatch(r'(?:[0-9a-f]{2}-){5}[0-9a-f]{2}', value):
        compact = value.replace('-', '')
    elif re.fullmatch(r'[0-9a-f]{12}', value):
        compact = value
    else:
        return None
    return compact if compact not in ('000000000000', 'ffffffffffff') else None


def audit_unifi(payload, regionals):
    if not isinstance(payload, dict):
        raise ValueError('Invalid envelope')
    aps, sites = payload.get('aps'), payload.get('sites')
    if not isinstance(aps, list) or not isinstance(sites, list):
        raise ValueError('Invalid inventory')
    site_ids, site_labels = Counter(), defaultdict(list)
    invalid_sites = missing_site_ids = 0
    for site in sites:
        if not isinstance(site, dict):
            invalid_sites += 1
            continue
        site_id = _text(site.get('id'))
        missing_site_ids += not bool(site_id)
        if site_id:
            site_ids[site_id] += 1
        label = _text(site.get('nome'))
        if label:
            site_labels[label].append(site_id)
    regional_labels = defaultdict(set)
    for code, entry in regionals.items():
        for label in (code, entry.get('nome'), entry.get('descricao')):
            label = _text(label).casefold()
            if label:
                regional_labels[label].add(code)
    counts = Counter()
    macs, identities, statuses, dates, links, bindings = (Counter() for _ in range(6))
    for ap in aps:
        if not isinstance(ap, dict):
            counts['registros_invalidos'] += 1
            continue
        for field in ('nome', 'mac', 'ip', 'site', 'site_id', 'modelo', 'modelo_codigo', 'firmware'):
            counts['com_' + field] += bool(_text(ap.get(field)))
        mac = _mac(ap.get('mac'))
        counts['macs_validos'] += mac is not None
        if mac:
            macs[mac] += 1
        ip = _text(ap.get('ip'))
        try:
            ipaddress.ip_address(ip)
            counts['ips_validos'] += 1
        except ValueError:
            counts['ips_ausentes_ou_invalidos'] += 1
        label = _text(ap.get('site'))
        explicit_id = _text(ap.get('site_id'))
        candidates = site_labels.get(label, [])
        site_id = explicit_id if explicit_id else (candidates[0] if len(candidates) == 1 else '')
        if explicit_id and (site_ids[explicit_id] != 1 or (label and candidates != [explicit_id])):
            kind = 'id_desconhecido_duplicado_ou_conflitante'
        elif site_id and site_ids[site_id] == 1:
            kind = 'site_identificado'
            if mac:
                identities[(site_id, mac)] += 1
        elif len(candidates) > 1:
            kind = 'nome_ambiguo'
        else:
            kind = 'nao_encontrado'
        links[kind] += 1
        regional_candidates = regional_labels.get(label.casefold(), set()) if label else set()
        bindings['exato_unico' if len(regional_candidates) == 1 else
                 'ambiguo' if regional_candidates else 'sem_correspondencia_exata'] += 1
        status = _text(ap.get('status')).lower()
        statuses[status if status in ('online', 'offline', 'warning', 'unknown', 'maintenance', 'inativo')
                 else 'outro_ou_ausente'] += 1
        dates[_time_kind(ap.get('coletado_em'))] += 1
    controller = payload.get('controller')
    controller = controller if isinstance(controller, dict) else {}
    port = controller.get('porta')
    return {
        'situacao': 'lido', 'publicacao': _time_kind(payload.get('timestamp')),
        'controladora_com_endereco': bool(_text(controller.get('ip'))),
        'controladora_com_porta_valida': isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535,
        'aps': len(aps), 'sites': len(sites),
        'sites_invalidos': invalid_sites, 'sites_sem_id': missing_site_ids,
        'ids_de_site_repetidos': sum(n > 1 for n in site_ids.values()),
        'nomes_de_site_repetidos': sum(len(values) > 1 for values in site_labels.values()),
        'cobertura': dict(counts), 'macs_repetidos_na_controladora': sum(n > 1 for n in macs.values()),
        'identidades_site_mac_repetidas': sum(n > 1 for n in identities.values()),
        'aps_com_site_e_mac_identificados': sum(identities.values()),
        'vinculo_ap_site': dict(links), 'regional_por_texto_exato_sem_alias': dict(bindings),
        'por_status': dict(statuses), 'coleta_explicita_por_ap': dict(dates),
    }


def audit_sources(root=ROOT):
    root = Path(root)
    report = {'modo': 'auditoria_aps_somente_leitura_sem_banco', 'fontes': {}}
    regionals = {}
    try:
        catalog = _read(root / 'estrutura_regionais.json')
        entries = catalog.get('regionais') if isinstance(catalog, dict) else None
        if not isinstance(entries, dict) or not entries or any(
                not _text(code) or not isinstance(entry, dict) for code, entry in entries.items()):
            raise ValueError('Invalid catalog')
        regionals = entries
        report['fontes']['catalogo_regional'] = {'situacao': 'lido', 'regionais': len(regionals)}
    except (OSError, ValueError, RecursionError):
        report['fontes']['catalogo_regional'] = {'situacao': 'ausente_ou_invalido'}
    try:
        report['fontes']['unifi_nativo'] = audit_unifi(_read(root / 'data/unifi.json'), regionals)
    except (OSError, ValueError, RecursionError):
        report['fontes']['unifi_nativo'] = {'situacao': 'ausente_ou_invalido'}
    return report


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(audit_sources(), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
