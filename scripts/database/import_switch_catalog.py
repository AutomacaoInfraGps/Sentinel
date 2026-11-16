"""Bootstrap switches from the native cache, including unbound regional records."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import (
    DatabaseProgress, ImportErrorSafe, _database_error, _observation, _unique_keys,
)
from scripts.database.import_server_catalog import _identity, _text


SOURCE = 'sentinel_zabbix_principal'


@dataclass(frozen=True, repr=False)
class SwitchCatalog:
    digest: str
    cache_sha256: str
    regionals_sha256: str
    source_timezone: str
    regional_codes: tuple = field(repr=False)
    rows: tuple = field(repr=False)

    def summary(self):
        bindings = Counter(row[7] for row in self.rows)
        return {"digest_carga": self.digest, "sha256_cache": self.cache_sha256,
                "sha256_catalogo_regionais": self.regionals_sha256,
                "fuso_origem": self.source_timezone, "regionais_no_catalogo": len(self.regional_codes),
                "switches": len(self.rows), "vinculos": dict(bindings),
                "por_origem": dict(Counter(row[0] for row in self.rows)),
                "sem_data_de_observacao": sum(row[16] is None for row in self.rows),
                "enderecos_dns": sum(row[8] is not None and row[9] is None for row in self.rows),
                "sincronizacao_automatica_switches": False}


def _load(raw):
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError):
        raise ImportErrorSafe('JSON invalido ou com chaves duplicadas.') from None


def _regional_key(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().upper()
    return '_'.join(token for token in re.split(r'[^A-Z0-9]+', value)
                    if token and token not in {'REG', 'REGIONAL', 'REGIAO'})


def _aliases(payload):
    entries = payload.get('regionais') if isinstance(payload, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise ImportErrorSafe('Catalogo regional ausente ou vazio.')
    aliases = defaultdict(set)
    for code, entry in entries.items():
        canonical = _text(code, 120, required=True)
        if canonical != code or canonical != canonical.upper() or not isinstance(entry, dict):
            raise ImportErrorSafe('Codigo ou cadastro regional invalido.')
        name = _text(entry.get('nome'))
        for value in (code, name):
            if value and _regional_key(value):
                aliases[_regional_key(value)].add(code)
    return tuple(sorted(entries)), aliases


def _boolean(record, key):
    value = record.get(key)
    if value is not None and type(value) is not bool:
        raise ImportErrorSafe('Indicador booleano invalido no switch.')
    return value


def _scalar_text(value, length=120):
    if type(value) is int:
        value = str(value)
    return _text(value, length)


def build_switch_catalog(raw_cache, raw_regionals, source_timezone):
    try:
        zone = ZoneInfo(source_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ImportErrorSafe('Fuso IANA indisponivel. Confira tzdata.') from None
    cache = _load(raw_cache)
    codes, aliases = _aliases(_load(raw_regionals))
    if not isinstance(cache, dict) or not cache:
        raise ImportErrorSafe('Cache de switches ausente ou vazio.')
    rows, identities = [], set()
    for host, record in sorted(cache.items()):
        name = _text(host, required=True)
        if not isinstance(record, dict):
            raise ImportErrorSafe('Registro de switch invalido.')
        local = _boolean(record, 'local_only') is True
        kind = 'local' if local else 'zabbix'
        source_id = _text(name.casefold(), required=True) if local else _scalar_text(record.get('hostid'), 240)
        if not source_id or (not local and not re.fullmatch(r'[1-9][0-9]*', source_id)):
            raise ImportErrorSafe('Switch sem hostid valido. Revise a origem; nenhum registro foi descartado.')
        identity = (kind, source_id)
        if identity in identities:
            raise ImportErrorSafe('Identidade de switch duplicada no cache.')
        identities.add(identity)
        regional = _text(record.get('regional'))
        matches = aliases.get(_regional_key(regional), set()) if regional else set()
        binding = ('ausente' if not regional else 'nao_encontrado' if not matches
                   else 'ambiguo' if len(matches) > 1 else 'vinculado')
        code = next(iter(matches)) if binding == 'vinculado' else None
        address = _text(record.get('ip'), 253)
        ip = None
        if address:
            try:
                ip = str(ipaddress.ip_address(address))
            except ValueError:
                if (re.fullmatch(r'[0-9.]+', address)
                        or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?', address)):
                    raise ImportErrorSafe('Endereco de switch invalido.') from None
        warnings = record.get('warning_problemas')
        if warnings is not None and not isinstance(warnings, list):
            raise ImportErrorSafe('Lista de alertas do switch invalida.')
        rows.append((kind, source_id, name, _text(record.get('zabbix_host')),
                     _text(record.get('zabbix_name')), code, regional, binding, address, ip,
                     _text(record.get('modelo')), _text(record.get('modelo_source'), 120),
                     _text(record.get('local')), _boolean(record, 'is_core'),
                     _text(record.get('core_source'), 120), _text(record.get('status'), 120),
                     _observation(record.get('ultima_verificacao'), zone),
                     _boolean(record, 'em_manutencao'), _scalar_text(record.get('maintenance_status'), 40),
                     _scalar_text(record.get('maintenance_type'), 40),
                     _scalar_text(record.get('maintenanceid')), _text(record.get('maintenance_scope'), 120),
                     len(warnings) if warnings is not None else None))
    rows.sort(key=lambda row: row[:2])
    cache_hash, regionals_hash = hashlib.sha256(raw_cache).hexdigest(), hashlib.sha256(raw_regionals).hexdigest()
    canonical = json.dumps((SOURCE, source_timezone, cache_hash, regionals_hash, codes, rows),
                           default=lambda value: value.isoformat(), ensure_ascii=True, separators=(',', ':'))
    return SwitchCatalog(hashlib.sha256(canonical.encode()).hexdigest(), cache_hash, regionals_hash,
                         source_timezone, codes, tuple(rows))


def inspect_switch_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute("SET LOCAL statement_timeout = '5s'")
        _identity(cursor)
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo = ANY(%s)',
                       (list(catalog.regional_codes),))
        existing = {row[0] for row in cursor.fetchall()}
        missing = set(catalog.regional_codes) - existing
        cursor.execute('SELECT count(*) FROM operacional.switches')
        count = cursor.fetchone()[0]
    return {"switches_existentes": count, "tabela_switches_vazia": count == 0,
            "regionais_do_catalogo_ausentes_no_banco": len(missing)}


def write_switch_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'configuracao_transacao'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '30s'")
        progress.phase = 'validacao_destino'
        _identity(cursor)
        progress.phase = 'bloqueio_tabelas'
        cursor.execute('LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE')
        cursor.execute('LOCK TABLE operacional.switches IN ROW EXCLUSIVE MODE')
        progress.phase = 'contagem_inicial'
        cursor.execute('SELECT count(*) FROM operacional.switches')
        if cursor.fetchone() != (0,):
            raise ImportErrorSafe('Switches ja cadastrados. Nao repetir a carga inicial.')
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo = ANY(%s)',
                       (list(catalog.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(catalog.regional_codes):
            raise ImportErrorSafe('Catalogo regional divergente do banco. Carga bloqueada.')
        for row in catalog.rows:
            progress.phase = 'insercao_switches'
            cursor.execute('''INSERT INTO operacional.switches
                (fonte,tipo_origem,id_origem,nome,zabbix_host,zabbix_nome,codigo_regional,
                 regional_origem,vinculo_regional,endereco,ip,modelo,modelo_origem,
                 localizacao,is_core,core_origem,status,ultima_verificacao,em_manutencao,
                 maintenance_status,maintenance_type,maintenance_id,maintenance_scope,
                 alertas_ativos,arquivo_origem_sha256,catalogo_regionais_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (SOURCE, *row, catalog.cache_sha256, catalog.regionals_sha256))
        progress.phase = 'contagem_final'
        cursor.execute('SELECT count(*) FROM operacional.switches')
        if cursor.fetchone() != (len(catalog.rows),):
            raise ImportErrorSafe('Contagem de switches divergente. Reverta a transacao.')
        cursor.execute('SELECT vinculo_regional,count(*) FROM operacional.switches GROUP BY vinculo_regional')
        if dict(cursor.fetchall()) != dict(Counter(row[7] for row in catalog.rows)):
            raise ImportErrorSafe('Contagem de vinculos divergente. Reverta a transacao.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'output/switches_status_cache.json')
    parser.add_argument('--regionals', type=Path, default=ROOT / 'estrutura_regionais.json')
    parser.add_argument('--source-timezone', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        catalog = build_switch_catalog(args.cache.read_bytes(), args.regionals.read_bytes(), args.source_timezone)
        result = {"modo": "simulacao_sem_conexao_ao_banco", **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao de banco somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato dos dois arquivos revisados.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_switch_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_switches_confirmada'
                else:
                    progress.phase = 'conferencia_somente_leitura'
                    result['banco'] = inspect_switch_catalog(connection, catalog)
                    result['modo'] = 'conferencia_somente_leitura'
                progress.phase = 'finalizacao_transacao'
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(progress.phase, exc)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
