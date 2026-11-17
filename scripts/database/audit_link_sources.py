"""Count link identities, sources and timestamps without network, SQL or writes."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import ipaddress
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ('id', 'nome', 'interface_monitorada', 'fortigate_host', 'firewall_serial',
          'vdom', 'origem_sync', 'modo_verificacao', 'status', 'ultima_verificacao',
          'coletado_em', 'provedor', 'ip', 'sdwan_member_id', 'packet_loss_percent')
SOURCES = {'fortigate', 'fortimanager', 'fortimanager_config+proxy_monitor',
           'fortimanager_proxy_monitor', 'fallback_local'}
STATUSES = {'online', 'offline', 'unknown', 'warning', 'inativo', 'maintenance',
            'up', 'down', 'unavailable'}
MODES = {'sla', 'interface', 'fortimanager_device_offline', 'ping', 'fisico',
         'monitor_zabbix_packet_loss', 'link_mode'}


def _value(value):
    if type(value) in (int, float):
        return str(value)
    return value.strip() if isinstance(value, str) else ''


def _time_kind(value):
    if value is None or value == '':
        return 'ausente'
    if not isinstance(value, str):
        return 'outro_formato'
    try:
        if 'T' not in value and ' ' not in value:
            return 'outro_formato'
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return 'com_fuso' if parsed.utcoffset() is not None else 'sem_fuso'
    except ValueError:
        return 'outro_formato'


def _ip_kind(value):
    if value is None or value == '':
        return 'ausente'
    if not isinstance(value, str):
        return 'outro_formato'
    try:
        ipaddress.ip_address(value.strip())
        return 'endereco_ip'
    except ValueError:
        try:
            ipaddress.ip_interface(value.strip())
            return 'ip_com_prefixo'
        except ValueError:
            return 'outro_formato'


def audit_records(scoped_records, codes):
    fields, times, collected, sources, statuses, modes, ips = (Counter() for _ in range(7))
    ids, interfaces, endpoint_interfaces = Counter(), Counter(), Counter()
    id_scopes = defaultdict(set)
    invalid = unbound = records = 0
    for scope, item in scoped_records:
        records += 1
        if not isinstance(item, dict):
            invalid += 1
            continue
        unbound += scope not in codes
        for key in FIELDS:
            fields[key] += bool(_value(item.get(key)))
        for counter, key, allowed in ((sources, 'origem_sync', SOURCES),
                                      (statuses, 'status', STATUSES),
                                      (modes, 'modo_verificacao', MODES)):
            value = _value(item.get(key)).lower()
            counter[value if value in allowed else 'outro_ou_ausente'] += 1
        times[_time_kind(item.get('ultima_verificacao'))] += 1
        collected[_time_kind(item.get('coletado_em'))] += 1
        ips[_ip_kind(item.get('ip'))] += 1
        source_id = _value(item.get('id'))
        interface = _value(item.get('interface_monitorada'))
        endpoint = _value(item.get('fortigate_host'))
        if source_id:
            ids[(scope, source_id)] += 1
            id_scopes[source_id].add(scope)
        if interface:
            interfaces[(scope, interface)] += 1
        if endpoint and interface:
            endpoint_interfaces[(scope, endpoint, interface)] += 1
    return {
        'registros': records, 'registros_invalidos': invalid,
        'sem_vinculo_exato_ao_catalogo': unbound,
        'campos_presentes': dict(fields), 'por_origem_sync': dict(sources),
        'por_status': dict(statuses), 'por_modo_verificacao': dict(modes),
        'horarios_verificacao': dict(times), 'horarios_coleta_explicita': dict(collected),
        'formatos_ip': dict(ips),
        'identidades_regional_id_completas': sum(ids.values()),
        'identidades_regional_id_repetidas': sum(count > 1 for count in ids.values()),
        'ids_reutilizados_entre_regionais': sum(len(scopes) > 1 for scopes in id_scopes.values()),
        'interfaces_repetidas_na_regional': sum(count > 1 for count in interfaces.values()),
        'identidades_regional_endpoint_interface_completas': sum(endpoint_interfaces.values()),
        'identidades_regional_endpoint_interface_repetidas': sum(count > 1 for count in endpoint_interfaces.values()),
    }


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Chaves duplicadas.')
        result[key] = value
    return result


def _read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_pairs)


def _catalog_stats(entries, category, codes):
    records = []
    absent = empty = malformed = 0
    for code, entry in entries.items():
        if not isinstance(entry, dict):
            malformed += 1
        elif category not in entry:
            absent += 1
        elif not isinstance(entry[category], list):
            malformed += 1
        else:
            empty += not entry[category]
            records.extend((code, item) for item in entry[category])
    return {**audit_records(records, codes), 'regionais_sem_lista': absent,
            'regionais_com_lista_vazia': empty, 'listas_ou_regionais_invalidas': malformed}


def audit_sources(root=ROOT):
    root = Path(root)
    report = {'modo': 'auditoria_links_somente_leitura_sem_banco', 'fontes': {}}
    codes = set()
    path = root / 'estrutura_regionais.json'
    try:
        catalog = _read(path)
        entries = catalog.get('regionais') if isinstance(catalog, dict) else None
        if (not isinstance(entries, dict) or not entries
                or any(not isinstance(code, str) or not code.strip() for code in entries)):
            raise ValueError()
        codes = set(entries)
        info = {'situacao': 'lido', 'regionais': len(codes)}
        for category in ('links', 'links_internet_auto'):
            info[category] = _catalog_stats(entries, category, codes)
        # These categories may contain the SAME links. Never sum them as inventory.
        overlap = 0
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            lists = [entry.get(key) for key in ('links', 'links_internet_auto')]
            if all(isinstance(items, list) for items in lists):
                sets = [{_value(item.get('id')) for item in items
                         if isinstance(item, dict) and _value(item.get('id'))} for items in lists]
                overlap += len(sets[0] & sets[1])
        info['ids_em_ambas_listas_na_mesma_regional'] = overlap
        report['fontes']['catalogo_regional'] = info
    except (OSError, ValueError, RecursionError):
        report['fontes']['catalogo_regional'] = {'situacao': 'ausente_ou_invalido'}
    for source, filename in (('estado_operacional', 'sentinel_operational_state.json'),
                             ('mapa_consolidado', 'mapa_monitoramento_cache.json')):
        path = root / 'output' / filename
        if not path.is_file():
            report['fontes'][source] = {'situacao': 'ausente'}
            continue
        try:
            payload = _read(path)
            if not isinstance(payload, dict):
                raise ValueError()
            if source == 'estado_operacional':
                groups = payload.get('groups')
                group = groups.get('links') if isinstance(groups, dict) else None
                if not isinstance(group, dict) or not isinstance(group.get('records'), list):
                    raise ValueError()
                records = [(_value(item.get('regional')) if isinstance(item, dict) else '', item)
                           for item in group['records']]
                publication = group.get('updated_at')
            else:
                entries = payload.get('regionais')
                if not isinstance(entries, list):
                    raise ValueError()
                records = []
                for regional in entries:
                    if not isinstance(regional, dict) or not isinstance(regional.get('links'), list):
                        raise ValueError()
                    records.extend((_value(regional.get('codigo')), item) for item in regional['links'])
                unmapped = payload.get('unmapped', {})
                if not isinstance(unmapped, dict) or not isinstance(unmapped.get('links', []), list):
                    raise ValueError()
                records.extend(('', item) for item in unmapped.get('links', []))
                publication = payload.get('cache_atualizado_em') or payload.get('atualizado_em')
            report['fontes'][source] = {'situacao': 'lido', 'publicacao': _time_kind(publication),
                                        **audit_records(records, codes)}
        except (OSError, ValueError, RecursionError):
            report['fontes'][source] = {'situacao': 'leitura_ou_estrutura_invalida'}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    print(json.dumps(audit_sources(), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
