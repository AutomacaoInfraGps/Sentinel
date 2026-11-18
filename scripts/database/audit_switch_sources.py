"""Read-only switch JSON source audit; no PostgreSQL, SQLite, Zabbix or firmware jobs."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _time_kind
from scripts.database.audit_server_sources import _read_source, _text, _present, _ip

SQL_FIELDS = ('hostid', 'regional', 'ip', 'modelo', 'modelo_source', 'is_core', 'core_source',
              'local', 'local_only', 'zabbix_host', 'zabbix_name', 'status', 'ultima_verificacao',
              'em_manutencao', 'maintenance_status', 'maintenance_type', 'maintenanceid', 'maintenance_scope')
EXTRA_FIELDS = ('status_reason', 'status_details', 'warning_resumo', 'firmware_version',
                'firmware_checked_at', 'portas', 'interfaces', 'coletado_em', 'updated_at')
STATUS_MAP = {key: key for key in ('online', 'offline', 'warning', 'inativo', 'maintenance', 'erro', 'desconhecido', 'unknown')}
STATUS_MAP.update({'n\u00e3o encontrado': 'nao_encontrado', 'nao encontrado': 'nao_encontrado'})


def _hostid(value):
    text = str(value) if type(value) is int else _text(value)
    return text if re.fullmatch(r'[1-9][0-9]*', text) else None


def _identity(name, record):
    if record.get('local_only') is True:
        return ('local', _text(name).casefold()) if _text(name) else None
    identifier = _hostid(record.get('hostid'))
    return ('zabbix', identifier) if identifier else None


def audit_records(records):
    sql = Counter({key: 0 for key in SQL_FIELDS})
    extras = Counter({key: 0 for key in EXTRA_FIELDS})
    identities, names, ips, statuses, checked, collected = (Counter() for _ in range(6))
    invalid = missing_id = invalid_flags = invalid_warning_lists = warning_items = invalid_warning_items = 0
    rows_warning_lists = rows_empty_warning_lists = invalid_ips = credentials = 0
    for name, record in records:
        if not isinstance(record, dict):
            invalid += 1
            continue
        for key in SQL_FIELDS:
            sql[key] += _present(record.get(key))
        for key in EXTRA_FIELDS:
            extras[key] += _present(record.get(key))
        identity = _identity(name, record)
        if identity:
            identities[identity] += 1
        else:
            missing_id += 1
        if _text(name):
            names[_text(name).casefold()] += 1
        address = _ip(record.get('ip'))
        if address:
            ips[address] += 1
        invalid_ips += _present(record.get('ip')) and address is None
        invalid_flags += sum(record.get(key) is not None and type(record[key]) is not bool
                             for key in ('is_core', 'local_only', 'em_manutencao'))
        status = _text(record.get('status')).casefold()
        statuses[STATUS_MAP.get(status, 'ausente_ou_outro')] += 1
        checked[_time_kind(record.get('ultima_verificacao'))] += 1
        collected[_time_kind(record.get('coletado_em'))] += 1
        warnings = record.get('warning_problemas')
        if isinstance(warnings, list):
            rows_warning_lists += 1
            rows_empty_warning_lists += not warnings
            warning_items += len(warnings)
            invalid_warning_items += sum(not isinstance(item, str) for item in warnings)
        elif warnings is not None:
            invalid_warning_lists += 1
        credentials += any(_present(record.get(key)) for key in
                           ('username', 'usuario', 'password', 'senha', 'credential_ref', 'snmp_community'))
    return {'registros': len(records), 'registros_invalidos': invalid,
            'cobertura_campos_da_projecao_sql_atual': dict(sql),
            'cobertura_campos_fora_da_projecao_sql_atual': dict(extras),
            'sem_identidade_tipo_origem_id': missing_id,
            'identidades_tipo_origem_id_repetidas': sum(count > 1 for count in identities.values()),
            'nomes_repetidos_sem_fusao': sum(count > 1 for count in names.values()),
            'ips_repetidos_sem_fusao': sum(count > 1 for count in ips.values()),
            'enderecos_nao_ip_sem_validacao_dns': invalid_ips, 'indicadores_booleanos_invalidos': invalid_flags,
            'por_status_declarado': dict(statuses), 'horarios_ultima_verificacao': dict(checked),
            'horarios_coleta_explicita': dict(collected),
            'registros_com_lista_alertas': rows_warning_lists, 'listas_alertas_vazias': rows_empty_warning_lists,
            'listas_alertas_invalidas': invalid_warning_lists, 'alertas_declarados': warning_items,
            'alertas_nao_textuais': invalid_warning_items,
            'registros_com_campos_de_acesso_preenchidos': credentials}


def cache_records(payload):
    if not isinstance(payload, dict):
        raise ValueError('Invalid switch cache')
    return list(payload.items()), {}


def operational_records(payload):
    groups = payload.get('groups') if isinstance(payload, dict) else None
    group = groups.get('switches') if isinstance(groups, dict) else None
    if not isinstance(group, dict) or not isinstance(group.get('records'), list):
        raise ValueError('Invalid operational switch group')
    return [(_text(row.get('host')) or _text(row.get('nome')), row) if isinstance(row, dict) else ('', row)
            for row in group['records']], {'horario_publicacao_grupo': _time_kind(group.get('updated_at'))}


def audit_metadata(payload, records):
    if not isinstance(payload, dict):
        raise ValueError('Invalid metadata')
    coverage = Counter({key: 0 for key in ('modelo', 'modelo_source', 'local', 'is_core', 'updated_at')})
    prefixes, used = Counter(), set()
    invalid = invalid_core = matches = conflicts = 0
    for key, record in payload.items():
        prefixes['hostid' if key.startswith('hostid:') else 'host' if key.startswith('host:') else 'outro'] += 1
        if not isinstance(record, dict):
            invalid += 1
            continue
        for field in coverage:
            coverage[field] += _present(record.get(field))
        invalid_core += 'is_core' in record and type(record['is_core']) is not bool
    for name, record in records:
        if not isinstance(record, dict):
            continue
        identifier = _hostid(record.get('hostid'))
        id_key, host_key = 'hostid:' + identifier if identifier else '', 'host:' + _text(name).casefold()
        by_id, by_host = payload.get(id_key), payload.get(host_key)
        if isinstance(by_id, dict) and isinstance(by_host, dict) and by_id and by_host and by_id != by_host:
            conflicts += 1
        chosen = id_key if isinstance(by_id, dict) and by_id else host_key
        if isinstance(payload.get(chosen), dict) and payload[chosen]:
            matches += 1
            used.add(chosen)
    return {'registros': len(payload), 'registros_invalidos': invalid, 'por_prefixo_chave': dict(prefixes),
            'campos_preenchidos': dict(coverage), 'indicadores_core_invalidos': invalid_core,
            'switches_com_metadado_candidato': matches, 'metadados_sem_uso_por_chave_prioritaria': len(set(payload) - used),
            'conflitos_entre_metadado_id_e_nome': conflicts}


def compare_records(cache, operational):
    def index(records):
        return Counter(identity for name, row in records if isinstance(row, dict)
                       if (identity := _identity(name, row)) is not None)
    left, right = index(cache), index(operational)
    return {'identidades_em_comum': len(left.keys() & right.keys()),
            'identidades_somente_cache_status': len(left.keys() - right.keys()),
            'identidades_somente_cache_operacional': len(right.keys() - left.keys()),
            'identidades_duplicadas_cache_status': sum(count > 1 for count in left.values()),
            'identidades_duplicadas_cache_operacional': sum(count > 1 for count in right.values())}


def audit_sources(root=ROOT):
    root = Path(root)
    sources, records = {}, {}
    for name, relative, extract in (
            ('cache_status', 'output/switches_status_cache.json', cache_records),
            ('cache_operacional', 'output/sentinel_operational_state.json', operational_records)):
        payload, info = _read_source(root / relative)
        if info['situacao'] == 'lido':
            try:
                rows, extra = extract(payload)
                info.update(extra)
                info.update(audit_records(rows))
                records[name] = rows
            except Exception:
                info = {'situacao': 'estrutura_de_switches_invalida'}
        sources[name] = info
    payload, info = _read_source(root / 'output/switches_metadata.json')
    if info['situacao'] == 'lido':
        try:
            info.update(audit_metadata(payload, records.get('cache_status', [])))
            info['comparacao_com_cache_disponivel'] = 'cache_status' in records
        except Exception:
            info = {'situacao': 'estrutura_de_metadados_invalida'}
    sources['metadados_locais'] = info
    firmware_path = root / 'data/switch_updates/scheduled_updates.sqlite3'
    sources['inventario_firmware_sqlite'] = {
        'situacao': 'presente_conteudo_nao_auditado' if firmware_path.is_file() else 'arquivo_padrao_ausente',
        'banco_aberto': False, 'jobs_lidos': False}
    return {'modo': 'auditoria_switches_somente_leitura_sem_banco', 'fontes': sources,
            'comparacao_identidades': {'comparavel': len(records) == 2,
                **(compare_records(records['cache_status'], records['cache_operacional']) if len(records) == 2 else {})},
            'projecao_sql_eh_referencia_do_codigo_nao_conferencia_do_banco': True,
            'prioridade_efetiva_da_tela_e_frescor_nao_avaliados': True,
            'metadados_nao_aplicados_nem_vinculos_aprovados': True,
            'ausencia_nos_jsons_nao_prova_ausencia_no_sqlite': True,
            'nomes_ips_motivos_versoes_e_credenciais_exportados': False,
            'zabbix_consultado': False, 'jobs_executados': False,
            'cofre_acessado': False, 'arquivos_modificados': False}


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(audit_sources(), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
