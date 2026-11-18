"""Read-only server screen source coverage; no SQL, vault or equipment queries."""

import argparse
from collections import Counter, defaultdict
import hashlib
import ipaddress
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _unique_object, _time_kind

SQL_FIELDS = ('id', 'nome', 'tipo', 'ip', 'modelo', 'funcao', 'sistema_operacional',
              'status', 'ativo', 'ultima_verificacao', 'tempo_resposta')
EXTRA_FIELDS = ('tipo_monitoramento', 'descricao', 'erro', 'em_manutencao',
                'maintenance_status', 'maintenanceid', 'status_reason', 'status_details',
                'hardware', 'details', 'detalhes', 'coletado_em', 'updated_at')
HARDWARE_FIELDS = ('memoria_gib', 'cpu', 'discos', 'bitdefender', 'temperaturas',
                   'ventoinhas', 'fabricante', 'uptime')
STATUSES = {'online', 'offline', 'warning', 'maintenance', 'unknown', 'error', 'unreachable'}


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _present(value):
    return value is not None and value != '' and value != [] and value != {}


def _ip(value):
    try:
        return str(ipaddress.ip_address(_text(value)))
    except ValueError:
        return None


def _read_source(path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
        if path.read_bytes() != raw:
            return None, {'situacao': 'alterado_durante_leitura'}
        return value, {'situacao': 'lido', 'sha256_arquivo': hashlib.sha256(raw).hexdigest(),
                       'bom_utf8_presente': raw.startswith(b'\xef\xbb\xbf')}
    except FileNotFoundError:
        return None, {'situacao': 'ausente'}
    except Exception:
        return None, {'situacao': 'leitura_ou_estrutura_invalida'}


def audit_records(records):
    sql = Counter({field: 0 for field in SQL_FIELDS})
    extras = Counter({field: 0 for field in EXTRA_FIELDS})
    hardware = Counter({field: 0 for field in HARDWARE_FIELDS})
    identities, addresses, statuses, checked, collected = Counter(), Counter(), Counter(), Counter(), Counter()
    invalid = missing_id = nontext_id = padded_id = invalid_ip = invalid_hardware = 0
    credential_fields = rows_with_hardware = 0
    for regional, record in records:
        if not isinstance(record, dict):
            invalid += 1
            continue
        for field in SQL_FIELDS:
            sql[field] += _present(record.get(field))
        for field in EXTRA_FIELDS:
            extras[field] += _present(record.get(field))
        identifier = _text(record.get('id'))
        missing_id += not bool(identifier)
        nontext_id += record.get('id') is not None and not isinstance(record['id'], str)
        padded_id += isinstance(record.get('id'), str) and record['id'] != identifier
        if identifier:
            identities[(regional, identifier.casefold())] += 1
        address = _ip(record.get('ip'))
        if address:
            addresses[(regional, address)] += 1
        invalid_ip += _present(record.get('ip')) and address is None
        status = _text(record.get('status')).lower()
        statuses[status if status in STATUSES else 'ausente_ou_outro'] += 1
        checked[_time_kind(record.get('ultima_verificacao'))] += 1
        collected[_time_kind(record.get('coletado_em'))] += 1
        credential_fields += any(_present(record.get(key)) for key in
                                 ('usuario', 'username', 'senha', 'password', 'credential_ref', 'snmp_community'))
        nested = record.get('hardware')
        if _present(nested):
            rows_with_hardware += 1
            invalid_hardware += not isinstance(nested, dict)
        for field in HARDWARE_FIELDS:
            hardware[field] += _present(record.get(field)) or (
                isinstance(nested, dict) and _present(nested.get(field)))
    return {'registros': len(records), 'registros_invalidos': invalid,
            'cobertura_campos_da_projecao_sql_atual': dict(sql),
            'cobertura_campos_fora_da_projecao_sql_atual': dict(extras),
            'sem_id_textual': missing_id, 'ids_nao_textuais': nontext_id, 'ids_com_espacos_externos': padded_id,
            'identidades_regional_id_repetidas_normalizadas': sum(count > 1 for count in identities.values()),
            'ips_repetidos_na_mesma_regional': sum(count > 1 for count in addresses.values()),
            'enderecos_ip_invalidos': invalid_ip, 'por_status_declarado': dict(statuses),
            'horarios_ultima_verificacao': dict(checked), 'horarios_coleta_explicita': dict(collected),
            'registros_com_hardware': rows_with_hardware, 'objetos_hardware_invalidos': invalid_hardware,
            'campos_hardware_presentes_sem_validacao_de_medicao': dict(hardware),
            'registros_com_campos_de_acesso_preenchidos': credential_fields}


def catalog_records(payload):
    regions = payload.get('regionais') if isinstance(payload, dict) else None
    if not isinstance(regions, dict) or not regions:
        raise ValueError('Invalid regional catalog')
    records, invalid_lists = [], 0
    for code, entry in regions.items():
        servers = entry.get('servidores') if isinstance(entry, dict) else None
        if not isinstance(servers, list):
            invalid_lists += 1
            continue
        records.extend((code, record) for record in servers)
    config = payload.get('configuracao')
    return records, {'regionais': len(regions), 'listas_servidores_invalidas_ou_ausentes': invalid_lists,
                     'horario_publicacao_cadastro': _time_kind(config.get('ultima_atualizacao') if isinstance(config, dict) else None)}


def operational_records(payload):
    groups = payload.get('groups') if isinstance(payload, dict) else None
    group = groups.get('servidores') if isinstance(groups, dict) else None
    if not isinstance(group, dict) or not isinstance(group.get('records'), list):
        raise ValueError('Invalid server group')
    records = [(_text(row.get('regional')), row) if isinstance(row, dict) else ('', row) for row in group['records']]
    return records, {'horario_publicacao_grupo': _time_kind(group.get('updated_at')),
                     'registros_sem_regional_textual': sum(not code for code, _ in records)}


def compare_records(catalog, operational):
    ids, ips = defaultdict(list), defaultdict(list)
    for code, record in catalog:
        if not isinstance(record, dict):
            continue
        identifier, address = _text(record.get('id')), _ip(record.get('ip'))
        if identifier:
            ids[(code, identifier)].append(record)
        if address:
            ips[(code, address)].append(record)
    matches = Counter()
    differences = Counter({field: 0 for field in ('status', 'ultima_verificacao', 'tempo_resposta',
                                                'erro', 'em_manutencao', 'status_reason', 'status_details')})
    for code, record in operational:
        if not isinstance(record, dict):
            matches['registro_invalido'] += 1
            continue
        identifier, address = _text(record.get('id')), _ip(record.get('ip'))
        by_id, by_ip = ids.get((code, identifier), []), ips.get((code, address), [])
        if len(by_id) > 1 or len(by_ip) > 1:
            category = 'ambiguo_nao_aprovado'
        elif by_id and by_ip and by_id[0] is not by_ip[0]:
            category = 'id_e_ip_apontam_cadastros_diferentes'
        elif by_id:
            category = 'id_exato_na_regional'
            for field in differences:
                differences[field] += record.get(field) != by_id[0].get(field)
        elif by_ip:
            category = 'apenas_ip_na_regional_candidato_nao_aprovado'
        else:
            category = 'sem_correspondencia_na_regional'
        matches[category] += 1
    return {'vinculos_candidatos': dict(matches), 'divergencias_em_pares_por_id_exato': dict(differences)}


def audit_sources(root=ROOT):
    root = Path(root)
    sources, records_by_source = {}, {}
    for name, relative, extract in (
            ('cadastro_regional', 'estrutura_regionais.json', catalog_records),
            ('cache_operacional_servidores', 'output/sentinel_operational_state.json', operational_records)):
        payload, info = _read_source(root / relative)
        if info['situacao'] == 'lido':
            try:
                records, metadata = extract(payload)
                info.update(metadata)
                info.update(audit_records(records))
                records_by_source[name] = records
            except Exception:
                info = {'situacao': 'estrutura_de_servidores_invalida'}
        sources[name] = info
    comparison = {'comparavel': False}
    if len(records_by_source) == 2 and not sources['cadastro_regional']['listas_servidores_invalidas_ou_ausentes']:
        comparison = {'comparavel': True, 'comparacao_sem_alteracao_de_vinculos': compare_records(
            records_by_source['cadastro_regional'], records_by_source['cache_operacional_servidores'])}
    return {'modo': 'auditoria_servidores_somente_leitura_sem_banco', 'fontes': sources,
            'comparacao_cache_cadastro': comparison,
            'projecao_sql_eh_referencia_do_codigo_nao_conferencia_do_banco': True,
            'frescor_e_prioridade_efetiva_do_cache_nao_avaliados': True,
            'fontes_lidas_separadamente_sem_snapshot_atomico': True,
            'cache_nao_aprovado_como_cadastro_ou_medicao_de_hardware': True,
            'consulta_hardware_sob_demanda_nao_executada': True,
            'nomes_ips_erros_e_credenciais_exportados': False,
            'cofre_acessado': False, 'arquivos_modificados': False}


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(audit_sources(), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
