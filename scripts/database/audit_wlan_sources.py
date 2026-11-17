"""Audit saved UniFi WLAN coverage without DB, API calls or credential exports."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _read, _text, _time_kind
from unifi_site_matching import resolve_unifi_site_for_catalog


def _wlan_identity(record):
    values = [record[key] for key in ('wlan_id', '_id', 'id') if record.get(key) not in (None, '')]
    if not values:
        return None, 'ausente'
    if any(not isinstance(value, str) or not value.strip() for value in values):
        return None, 'invalido_ou_conflitante'
    cleaned = {value.strip() for value in values}
    if len(cleaned) != 1:
        return None, 'invalido_ou_conflitante'
    return next(iter(cleaned)), 'presente'


def audit_unifi_wlans(payload, regionals):
    if not isinstance(payload, dict) or not isinstance(payload.get('sites'), list):
        raise ValueError('Invalid source')
    sites = payload['sites']
    site_ids = Counter(_text(site.get('id')) for site in sites if isinstance(site, dict) and _text(site.get('id')))
    counts = Counter()
    identities, names, folded = Counter(), Counter(), Counter()
    name_sites = defaultdict(set)
    regional_bindings, statuses, ids, origins = (Counter() for _ in range(4))
    dates, site_dates = Counter(), Counter()
    for index, site in enumerate(sites):
        if not isinstance(site, dict):
            counts['sites_invalidos'] += 1
            continue
        site_id = _text(site.get('id'))
        counts['sites_sem_id'] += not bool(site_id)
        _, reason = resolve_unifi_site_for_catalog(regionals, site.get('nome'))
        # AP collection time and global file save time are not WLAN observation times.
        site_dates[_time_kind(site.get('wlans_coletadas_em'))] += 1
        counts['sites_com_coleta_wlan_confirmada'] += site.get('coleta_wlans_confirmada') is True
        if 'redes_wifi' not in site:
            counts['sites_sem_lista_wifi'] += 1
            continue
        networks = site['redes_wifi']
        if not isinstance(networks, list):
            counts['listas_wifi_invalidas'] += 1
            continue
        counts['sites_com_lista_wifi'] += 1
        counts['sites_com_lista_wifi_vazia'] += not networks
        for network in networks:
            counts['registros_wifi'] += 1
            if not isinstance(network, dict):
                counts['registros_wifi_invalidos'] += 1
                continue
            name = _text(network.get('nome')) or _text(network.get('ssid'))
            counts['redes_sem_nome'] += not bool(name)
            if name:
                names[(index, name)] += 1
                folded[(index, name.casefold())] += 1
                name_sites[name].add(index)
            wlan_id, identity_kind = _wlan_identity(network)
            ids[identity_kind] += 1
            if wlan_id and site_id and site_ids[site_id] == 1:
                identities[(site_id, wlan_id)] += 1
                counts['redes_com_site_e_id_wlan'] += 1
            regional_bindings[reason] += 1
            active = network.get('ativo')
            statuses['ativa' if active is True else 'inativa' if active is False else 'ausente_ou_nao_booleano'] += 1
            origin = _text(network.get('origem'))
            origins[origin if origin in ('configuracao_unifi', 'runtime_ap', 'configuracao_e_runtime')
                    else 'outro_ou_ausente'] += 1
            dates[_time_kind(network.get('coletado_em'))] += 1
            counts['redes_com_id_rede'] += bool(_text(network.get('networkconf_id')))
            counts['redes_com_rede_textual'] += bool(_text(network.get('rede')))
            for field in ('bandas', 'transmissao'):
                value = network.get(field)
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    counts['listas_' + field + '_ausentes_ou_invalidas'] += 1
                elif value:
                    counts['redes_com_' + field] += 1
    controller = payload.get('controller')
    controller = controller if isinstance(controller, dict) else {}
    port = controller.get('porta')
    keys = ('sites_invalidos', 'sites_sem_id', 'sites_sem_lista_wifi', 'listas_wifi_invalidas',
            'sites_com_lista_wifi', 'sites_com_lista_wifi_vazia', 'sites_com_coleta_wlan_confirmada',
            'registros_wifi', 'registros_wifi_invalidos', 'redes_sem_nome', 'redes_com_site_e_id_wlan',
            'redes_com_id_rede', 'redes_com_rede_textual', 'redes_com_bandas', 'redes_com_transmissao',
            'listas_bandas_ausentes_ou_invalidas', 'listas_transmissao_ausentes_ou_invalidas')
    return {
        'situacao': 'lido', 'publicacao': _time_kind(payload.get('timestamp')),
        'controladora_com_endereco': bool(_text(controller.get('ip'))),
        'controladora_com_porta_valida': type(port) is int and 1 <= port <= 65535,
        'sites': len(sites), 'ids_de_site_repetidos': sum(n > 1 for n in site_ids.values()),
        **{key: counts[key] for key in keys},
        'ids_wlan': dict(ids), 'identidades_site_wlan_repetidas': sum(n > 1 for n in identities.values()),
        'nomes_repetidos_no_mesmo_site': sum(n > 1 for n in names.values()),
        'nomes_repetidos_no_mesmo_site_ignorando_maiusculas': sum(n > 1 for n in folded.values()),
        'nomes_presentes_em_mais_de_um_site': sum(len(values) > 1 for values in name_sites.values()),
        'por_ativo': dict(statuses), 'por_origem_declarada': dict(origins),
        'regional_por_regras_unifi_sem_aproximacao': dict(regional_bindings),
        'coleta_explicita_por_rede': dict(dates), 'coleta_wlan_por_site': dict(site_dates),
    }


def audit_sources(root=ROOT):
    root = Path(root)
    report = {'modo': 'auditoria_wlans_somente_leitura_sem_banco', 'fontes': {}}
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
        payload = _read(root / 'data/unifi.json')
        report['fontes']['unifi_nativo'] = audit_unifi_wlans(payload, regionals)
        separate = {'controller': payload.get('controller'), 'timestamp': payload.get('timestamp'), 'sites': []}
        situations = Counter()
        for site in payload['sites']:
            if not isinstance(site, dict):
                separate['sites'].append(None)
                continue
            projected = {key: site.get(key) for key in ('id', 'nome', 'wlans_coletadas_em', 'coleta_wlans_confirmada')}
            if 'wlans_configuradas' in site:
                projected['redes_wifi'] = site['wlans_configuradas']
            separate['sites'].append(projected)
            situation = site.get('wlans_situacao')
            situations[situation if isinstance(situation, str) and situation in
                       ('confirmada', 'sem_confirmacao_api', 'identidade_ou_estrutura_invalida') else 'ausente_ou_outro'] += 1
        report['fontes']['unifi_configuracao_separada'] = {
            **audit_unifi_wlans(separate, regionals), 'sites_por_situacao': dict(situations)}
    except (OSError, ValueError, RecursionError):
        report['fontes']['unifi_nativo'] = {'situacao': 'ausente_ou_invalido'}
    return report


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(audit_sources(), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
