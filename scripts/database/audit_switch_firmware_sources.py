"""Read only switch_firmware_inventory in SQLite; never initializes the scheduler or jobs."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _time_kind
from scripts.database.audit_server_sources import _read_source, _text, _ip
from scripts.database.audit_switch_sources import _identity

TABLE = 'switch_firmware_inventory'
COLUMNS = ('host', 'switch_name', 'regional', 'ip_address', 'model', 'current_version', 'checked_at_utc', 'source')
MAX_ROWS = 10000


def _authorize(action, first, second, database, trigger):
    if action == sqlite3.SQLITE_READ:
        allowed = (first == TABLE and second in COLUMNS) or (first == 'sqlite_master' and second in ('name', 'type'))
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def read_inventory(path):
    path = Path(path)
    opened = False
    try:
        if not path.is_file():
            return None, {'situacao': 'arquivo_ausente', 'banco_aberto': False}
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&cache=private', uri=True, timeout=2)) as connection:
            opened = True
            connection.execute('PRAGMA query_only=ON')
            connection.set_authorizer(_authorize)
            connection.execute('BEGIN')
            kind = connection.execute('SELECT type FROM sqlite_master WHERE name=?', (TABLE,)).fetchone()
            if kind is None:
                return None, {'situacao': 'tabela_inventario_ausente', 'banco_aberto': True}
            if kind != ('table',):
                return None, {'situacao': 'objeto_inventario_nao_e_tabela', 'banco_aberto': True}
            rows = connection.execute('SELECT ' + ','.join(COLUMNS) + ' FROM ' + TABLE + ' LIMIT ' + str(MAX_ROWS + 1)).fetchall()
            if len(rows) > MAX_ROWS:
                return None, {'situacao': 'limite_de_inventario_excedido', 'banco_aberto': True}
            return [dict(zip(COLUMNS, row)) for row in rows], {'situacao': 'lido_somente_leitura', 'banco_aberto': True}
    except (OSError, sqlite3.Error, ValueError):
        return None, {'situacao': 'leitura_sqlite_ou_schema_indisponivel', 'banco_aberto': opened}


def audit_inventory(rows):
    fields = Counter({key: 0 for key in COLUMNS})
    dates, sources, hosts, names, ips = (Counter() for _ in range(5))
    nontext = missing_hosts = conflicting_addresses = 0
    for row in rows:
        for key in COLUMNS:
            fields[key] += bool(_text(row.get(key)))
            nontext += row.get(key) is not None and not isinstance(row[key], str)
        host, name = _text(row.get('host')), _text(row.get('switch_name'))
        address, host_address = _ip(row.get('ip_address')), _ip(host)
        if host:
            hosts[host] += 1
        else:
            missing_hosts += 1
        if name:
            names[name.casefold()] += 1
        if address:
            ips[address] += 1
        conflicting_addresses += bool(address and host_address and address != host_address)
        dates[_time_kind(row.get('checked_at_utc'))] += 1
        source = _text(row.get('source')).casefold()
        sources[source if source in ('webui', 'bulk_webui', 'snmp', 'ssh', 'manual') else 'ausente_ou_outro'] += 1
    return {'registros': len(rows), 'campos_textuais_preenchidos': dict(fields), 'campos_nao_textuais': nontext,
            'sem_host_textual': missing_hosts, 'hosts_repetidos': sum(count > 1 for count in hosts.values()),
            'nomes_repetidos_sem_fusao': sum(count > 1 for count in names.values()),
            'ips_repetidos_sem_fusao': sum(count > 1 for count in ips.values()),
            'host_ip_e_ip_address_divergentes': conflicting_addresses,
            'horarios_consulta_firmware': dict(dates), 'por_origem_declarada': dict(sources)}


def compare_with_cache(rows, cache):
    by_ip, by_name = defaultdict(list), defaultdict(list)
    invalid_records = 0
    for name, record in cache.items():
        if not isinstance(record, dict):
            invalid_records += 1
            continue
        identity = _identity(name, record)
        address = _ip(record.get('ip'))
        if address:
            by_ip[address].append(identity)
        by_name[_text(name).casefold()].append(identity)
    matches = Counter()
    for row in rows:
        host_ip, declared_ip = _ip(row.get('host')), _ip(row.get('ip_address'))
        if host_ip and declared_ip and host_ip != declared_ip:
            matches['enderecos_da_fonte_conflitantes'] += 1
            continue
        ip_candidates = by_ip.get(declared_ip or host_ip, [])
        name_candidates = by_name.get(_text(row.get('switch_name')).casefold(), [])
        if len(ip_candidates) > 1 or len(name_candidates) > 1:
            category = 'ambiguo_nao_aprovado'
        elif any(candidate is None for candidate in (*ip_candidates, *name_candidates)):
            category = 'candidato_sem_identidade_valida'
        elif ip_candidates and name_candidates and ip_candidates[0] != name_candidates[0]:
            category = 'ip_e_nome_apontam_identidades_diferentes'
        elif ip_candidates and name_candidates:
            category = 'ip_e_nome_concordantes_candidato'
        elif ip_candidates:
            category = 'apenas_ip_candidato_nao_aprovado'
        elif name_candidates:
            category = 'apenas_nome_candidato_nao_aprovado'
        else:
            category = 'sem_correspondencia'
        matches[category] += 1
    return {'registros_invalidos_no_cache': invalid_records, 'candidatos_sem_aprovacao': dict(matches)}


def audit_sources(root=ROOT, database=None):
    root = Path(root)
    rows, source = read_inventory(database or root / 'data/switch_updates/scheduled_updates.sqlite3')
    cache, cache_info = _read_source(root / 'output/switches_status_cache.json')
    comparison = {'comparavel': False}
    if rows is not None:
        source.update(audit_inventory(rows))
        if cache_info['situacao'] == 'lido' and isinstance(cache, dict):
            comparison = {'comparavel': True, **compare_with_cache(rows, cache)}
    return {'modo': 'auditoria_firmware_switches_sqlite_somente_leitura_sem_postgresql',
            'fontes': {'inventario_firmware_sqlite': source, 'cache_status': cache_info},
            'comparacao_com_cache': comparison,
            'vinculos_nao_aprovados_automaticamente': True,
            'modelo_e_versao_nao_comprovam_atualizacao_executada': True,
            'consulta_firmware_nao_confundida_com_status_de_rede': True,
            'nomes_ips_modelos_versoes_e_erros_brutos_exportados': False,
            'tabelas_de_jobs_consultadas': False, 'agendador_importado': False,
            'escrita_sql_habilitada': False, 'equipamentos_consultados': False,
            'cofre_acessado': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, help='Caminho SQLite explicito, inclusive snapshot consistente ja preparado.')
    args = parser.parse_args(argv)
    print(json.dumps(audit_sources(database=args.database), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
