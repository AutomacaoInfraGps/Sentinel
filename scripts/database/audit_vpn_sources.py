"""Audit VPN identity and time coverage without DB, network or record exports."""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FILES = {
    'estado_operacional': 'output/sentinel_operational_state.json',
    'mapa_consolidado': 'output/mapa_monitoramento_cache.json',
}
FIELDS = ('tunel', 'nome', 'device', 'firewall_serial', 'vdom', 'regional',
          'interface', 'status', 'ultima_verificacao', 'coletado_em',
          'vpn_source', 'device_namespace')


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def time_kind(value):
    if value is not None and not isinstance(value, str):
        return 'invalido'
    value = _text(value)
    if not value:
        return 'ausente'
    if re.fullmatch(r'\d{2}:\d{2}:\d{2}', value):
        try:
            datetime.strptime(value, '%H:%M:%S')
            return 'somente_hora_sem_data'
        except ValueError:
            return 'invalido'
    try:
        if 'T' not in value and ' ' not in value:
            return 'invalido'
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return 'com_fuso' if parsed.utcoffset() is not None else 'sem_fuso'
    except ValueError:
        return 'invalido'


def audit_records(records, publication=None, regional_codes=()):
    present, times, collected_times, statuses = Counter(), Counter(), Counter(), Counter()
    sources = Counter()
    tunnels, identities = Counter(), Counter()
    invalid = unbound = complete = 0
    for record in records:
        if not isinstance(record, dict):
            invalid += 1
            continue
        for key in FIELDS:
            present[key] += bool(_text(record.get(key)))
        times[time_kind(record.get('ultima_verificacao'))] += 1
        collected_times[time_kind(record.get('coletado_em'))] += 1
        source = _text(record.get('vpn_source'))
        sources[source if source in ('fortigate_ssh', 'fortimanager_proxy')
                else 'outro_ou_ausente'] += 1
        status = _text(record.get('status')).lower()
        # Never echo arbitrary status strings or other source values.
        statuses[status if status in ('online', 'offline', 'up', 'down', 'warning',
                                     'unknown', 'unavailable') else 'outro_ou_ausente'] += 1
        regional = _text(record.get('regional'))
        unbound += regional not in regional_codes
        tunnel = _text(record.get('tunel'))
        if tunnel:
            tunnels[tunnel] += 1
        device = _text(record.get('firewall_serial')) or _text(record.get('device'))
        vdom = _text(record.get('vdom'))
        if device and vdom and tunnel:
            complete += 1
            identities[(_text(record.get('device_namespace')), device, vdom, tunnel)] += 1
    return {
        'registros': len(records), 'registros_invalidos': invalid,
        'publicacao': time_kind(publication),
        'campos_presentes': dict(present), 'horarios_observacao': dict(times),
        'horarios_coleta': dict(collected_times),
        'por_fonte_coleta': dict(sources),
        'por_status': dict(statuses), 'sem_vinculo_exato_ao_catalogo': unbound,
        'nomes_de_tunel_repetidos': sum(n > 1 for n in tunnels.values()),
        'identidade_dispositivo_vdom_tunel_completa': complete,
        'identidades_compostas_repetidas': sum(n > 1 for n in identities.values()),
    }


def _read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def audit_sources(root=PROJECT_ROOT):
    root = Path(root)
    report = {'modo': 'auditoria_vpns_somente_leitura_sem_banco',
              'catalogo_regionais': {}, 'fontes': {}}
    try:
        catalog = _read(root / 'estrutura_regionais.json')
        regions = catalog.get('regionais') if isinstance(catalog, dict) else None
        if not isinstance(regions, dict) or any(not _text(code) for code in regions):
            raise ValueError()
        codes = set(regions)
        report['catalogo_regionais'] = {'situacao': 'lido', 'regionais': len(codes)}
    except (OSError, ValueError, RecursionError):
        report['catalogo_regionais'] = {'situacao': 'ausente_ou_invalido'}
        # An unavailable catalogue cannot establish regional authorization.
        codes = set()
    for source, relative in FILES.items():
        path = root / relative
        if not path.is_file():
            report['fontes'][source] = {'situacao': 'ausente'}
            continue
        try:
            payload = _read(path)
            if not isinstance(payload, dict):
                raise ValueError()
            if source == 'estado_operacional':
                groups = payload.get('groups')
                group = groups.get('vpns') if isinstance(groups, dict) else None
                if not isinstance(group, dict) or not isinstance(group.get('records'), list):
                    raise ValueError()
                records = group['records']
                publication = group.get('updated_at')
            else:
                regions = payload.get('regionais')
                if not isinstance(regions, list):
                    raise ValueError()
                records = []
                for regional in regions:
                    if not isinstance(regional, dict) or not isinstance(regional.get('vpns'), list):
                        raise ValueError()
                    records.extend(
                        {**record, 'regional': regional.get('codigo')}
                        if isinstance(record, dict) else record
                        for record in regional['vpns'])
                unmapped = payload.get('unmapped', {})
                if not isinstance(unmapped, dict) or not isinstance(unmapped.get('vpns', []), list):
                    raise ValueError()
                records.extend(unmapped.get('vpns', []))
                publication = payload.get('cache_atualizado_em') or payload.get('atualizado_em')
            report['fontes'][source] = {
                'situacao': 'lido', **audit_records(records, publication, codes)}
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
