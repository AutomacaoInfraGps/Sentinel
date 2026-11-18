"""Bootstrap admin observations and approved baseline separately; simulation by default."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _read
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error, _observation
from scripts.database.import_server_catalog import _identity, _text
from scripts.database.import_switch_catalog import _load

SOURCE_ID = 'sentinel_admin_monitor'
TABLES = ('fontes_monitor_admins', 'dispositivos_monitor_admins', 'contas_admins_observadas',
          'baseline_admins_aprovada', 'divergencias_monitor_admins')
BOOTSTRAP_LOCK = (0x41444D01, 16)
CENTRAL = {'__fortimanager__': 'fortimanager', '__fortianalyzer__': 'fortianalyzer'}


@dataclass(frozen=True, repr=False)
class AdminCatalog:
    digest: str
    hashes: tuple
    source_timezone: str
    published_at: object
    regional_codes: tuple = field(repr=False)
    devices: tuple = field(repr=False)
    observed: tuple = field(repr=False)
    approved: tuple = field(repr=False)
    differences: tuple = field(repr=False)

    def summary(self):
        return {'digest_carga': self.digest,
                **dict(zip(('sha256_cache_admins', 'sha256_baseline', 'sha256_cache_firewalls',
                            'sha256_catalogo_regionais'), self.hashes)),
                'fuso_origem': self.source_timezone, 'publicado_em': self.published_at.isoformat(),
                'dispositivos': len(self.devices), 'dispositivos_no_cache': sum(row[5] for row in self.devices),
                'dispositivos_somente_na_baseline': sum(not row[5] and row[6] for row in self.devices),
                'por_vinculo_regional': dict(Counter(row[4] for row in self.devices)),
                'consulta_valida_declarada': dict(Counter('ausente' if row[7] is None else
                                                        'sim' if row[7] else 'nao'
                                                        for row in self.devices if row[5])),
                'contas_observadas_incluindo_cache_anterior': len(self.observed),
                'contas_baseline_aprovada': len(self.approved),
                'divergencias_declaradas_no_cache': dict(Counter(row[2] for row in self.differences)),
                'baseline_modificada': False, 'contas_aprovadas_automaticamente': False,
                'sincronizacao_automatica_admins': False}


def _identifier(value):
    text = _text(value, 240, required=True)
    if text != value:
        raise ImportErrorSafe('Identificador com espacos externos. Revise a origem sem fundir contas.')
    return text


def _accounts(value):
    if not isinstance(value, list):
        raise ImportErrorSafe('Lista de contas ausente ou invalida.')
    accounts = tuple(_identifier(item) for item in value)
    if len(set(accounts)) != len(accounts):
        raise ImportErrorSafe('Conta duplicada no mesmo dispositivo. Nenhuma conta foi descartada.')
    return accounts


def _flag(device, name):
    value = device.get(name)
    if value is not None and type(value) is not bool:
        raise ImportErrorSafe('Indicador de consulta invalido.')
    return value


def build_admin_catalog(raw_cache, raw_baseline, raw_firewalls, raw_regionals, source_timezone):
    try:
        zone = ZoneInfo(source_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ImportErrorSafe('Fuso IANA invalido ou indisponivel. Confira tzdata.') from None
    cache, baseline, firewalls, catalog = map(_load, (raw_cache, raw_baseline, raw_firewalls, raw_regionals))
    regions = catalog.get('regionais') if isinstance(catalog, dict) else None
    devices = cache.get('dispositivos') if isinstance(cache, dict) else None
    groups = firewalls.get('firewalls_por_regional') if isinstance(firewalls, dict) else None
    if (not isinstance(regions, dict) or not regions or
            any(not isinstance(entry, dict) or _text(code, 120, required=True) != code or code != code.upper()
                for code, entry in regions.items())):
        raise ImportErrorSafe('Catalogo regional invalido ou vazio.')
    if not isinstance(devices, dict) or not devices or not isinstance(baseline, dict) or not baseline:
        raise ImportErrorSafe('Cache ou baseline ausente, invalido ou vazio. Carga bloqueada.')
    if not isinstance(groups, dict) or not groups:
        raise ImportErrorSafe('Cache de firewalls ausente ou invalido.')
    index = defaultdict(set)
    for code, entries in groups.items():
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise ImportErrorSafe('Lista de firewalls invalida.')
        if code not in regions:
            raise ImportErrorSafe('Regional do cache de firewalls ausente no catalogo.')
        for entry in entries:
            name = _text(entry.get('nome'), required=True)
            index[name.casefold()].add(code)
    published = _observation(cache.get('atualizado_em'), zone)
    if published is None:
        raise ImportErrorSafe('Publicacao do cache sem data completa.')
    rows, observed, approved, differences = [], [], [], []
    for key in sorted(set(devices) | set(baseline)):
        _identifier(key)
        present, has_baseline = key in devices, key in baseline
        device = devices[key] if present else {}
        if not isinstance(device, dict):
            raise ImportErrorSafe('Dispositivo invalido no cache.')
        kind = device.get('tipo') if present else CENTRAL.get(key, 'nao_identificado')
        if kind not in ('fortigate', 'fortimanager', 'fortianalyzer', 'nao_identificado'):
            raise ImportErrorSafe('Tipo de dispositivo nao reconhecido.')
        if (key in CENTRAL and kind != CENTRAL[key]) or (kind in CENTRAL.values() and CENTRAL.get(key) != kind):
            raise ImportErrorSafe('Identidade central incoerente. Nenhum equipamento foi fundido.')
        name = _text(device.get('nome'), required=True) if present else key
        matches = index.get(name.casefold(), set()) if present and kind == 'fortigate' else set()
        binding = ('central_sem_regional' if key in CENTRAL else 'somente_baseline' if not present else
                   'unico' if len(matches) == 1 else 'ambiguo' if matches else 'nao_encontrado')
        regional = next(iter(matches)) if len(matches) == 1 else None
        valid, unavailable, limited, offline, denied = (
            _flag(device, flag) for flag in ('consulta_valida', 'consulta_indisponivel',
                                           'monitoramento_limitado', 'offline', 'sem_permissao'))
        if valid is True and any(value is True for value in (unavailable, limited, offline, denied)):
            raise ImportErrorSafe('Evidencia de consulta contraditoria. Revise antes de importar.')
        last_valid = _observation(device.get('ultima_coleta_valida'), zone)
        if last_valid and last_valid > published:
            raise ImportErrorSafe('Ultima coleta valida posterior a publicacao do cache.')
        rows.append((key, name, kind, regional, binding, present, has_baseline, valid,
                     unavailable, limited, offline, denied, last_valid))
        if present:
            # Missing evidence (including legacy FMG) never becomes a fresh successful observation.
            evidence = 'consulta_valida_declarada' if valid is True else 'cache_sem_confirmacao_atual'
            observed.extend((key, account, evidence) for account in _accounts(device.get('admins')))
            for column, category in (('novos', 'novo'), ('removidos', 'removido'),
                                     ('remocoes_pendentes', 'remocao_pendente')):
                differences.extend((key, account, category) for account in _accounts(device.get(column, [])))
        if has_baseline:
            approved.extend((key, account) for account in _accounts(baseline[key]))
    observed.sort()
    approved.sort()
    differences.sort()
    hashes = tuple(hashlib.sha256(raw).hexdigest() for raw in (raw_cache, raw_baseline, raw_firewalls, raw_regionals))
    canonical = (SOURCE_ID, hashes, source_timezone, published, rows, observed, approved, differences)
    digest = hashlib.sha256(json.dumps(canonical, default=lambda value: value.isoformat(),
                                      ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    return AdminCatalog(digest, hashes, source_timezone, published, tuple(sorted(regions)),
                        tuple(rows), tuple(observed), tuple(approved), tuple(differences))


def _inspect(cursor, catalog):
    cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(catalog.regional_codes),))
    missing = len(set(catalog.regional_codes) - {row[0] for row in cursor.fetchall()})
    counts = {}
    for table in TABLES:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return {'regionais_do_catalogo_ausentes_no_banco': missing, 'contagens': counts,
            'tabelas_monitor_admins_vazias': not any(counts.values())}


def inspect_admin_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        return _inspect(cursor, catalog)


def write_admin_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'validacao_destino'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga de admins em andamento. Nao repetir agora.')
        cursor.execute('LOCK TABLE operacional.regionais IN ACCESS SHARE MODE')
        for table in TABLES:
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        progress.phase = 'conferencia_destino'
        inspection = _inspect(cursor, catalog)
        if not inspection['tabelas_monitor_admins_vazias']:
            raise ImportErrorSafe('Monitor de admins ja carregado. Nao repetir a carga inicial.')
        if inspection['regionais_do_catalogo_ausentes_no_banco']:
            raise ImportErrorSafe('Regionais ausentes no banco. Carga bloqueada.')
        progress.phase = 'insercao_monitor_admins'
        cursor.execute('INSERT INTO operacional.fontes_monitor_admins '
                       '(id,cache_sha256,baseline_sha256,firewalls_sha256,catalogo_regionais_sha256,'
                       'fuso_origem,publicado_em,digest_carga) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                       (SOURCE_ID, *catalog.hashes, catalog.source_timezone, catalog.published_at, catalog.digest))
        for row in catalog.devices:
            cursor.execute('INSERT INTO operacional.dispositivos_monitor_admins '
                           '(fonte_id,chave_dispositivo,nome,tipo,codigo_regional,vinculo_regional,'
                           'presente_no_cache,presente_na_baseline,consulta_valida,consulta_indisponivel,'
                           'monitoramento_limitado,offline,sem_permissao,ultima_coleta_valida) '
                           'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (SOURCE_ID, *row))
        for row in catalog.observed:
            cursor.execute('INSERT INTO operacional.contas_admins_observadas '
                           '(fonte_id,chave_dispositivo,usuario,evidencia) VALUES (%s,%s,%s,%s)', (SOURCE_ID, *row))
        for row in catalog.approved:
            cursor.execute('INSERT INTO operacional.baseline_admins_aprovada '
                           '(fonte_id,chave_dispositivo,usuario) VALUES (%s,%s,%s)', (SOURCE_ID, *row))
        for row in catalog.differences:
            cursor.execute('INSERT INTO operacional.divergencias_monitor_admins '
                           '(fonte_id,chave_dispositivo,usuario,categoria) VALUES (%s,%s,%s,%s)', (SOURCE_ID, *row))
        progress.phase = 'conferencia_final'
        expected = (1, len(catalog.devices), len(catalog.observed), len(catalog.approved), len(catalog.differences))
        for table, count in zip(TABLES, expected):
            cursor.execute('SELECT count(*) FROM operacional.' + table)
            if cursor.fetchone() != (count,):
                raise ImportErrorSafe('Contagem divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cache', 'baseline', 'firewalls', 'regionals'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--source-timezone', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        if (args.apply or args.check_database) and any(getattr(args, name) is None for name in
                                                     ('cache', 'baseline', 'firewalls', 'regionals')):
            raise ImportErrorSafe('Operacao de banco exige as quatro copias explicitas revisadas.')
        baseline = args.baseline
        if baseline is None:
            configured = (_read(ROOT / 'environment.json').get('fortianalyzer') or {}).get(
                'admin_baseline_file', 'admin_baseline.json')
            if not isinstance(configured, str) or not configured.strip():
                raise ImportErrorSafe('Caminho da baseline invalido.')
            baseline = Path(configured)
            if not baseline.is_absolute():
                baseline = ROOT / baseline
        paths = (args.cache or ROOT / 'output/dashboard_admins_cache.json', baseline,
                 args.firewalls or ROOT / 'output/dashboard_firewalls_cache.json',
                 args.regionals or ROOT / 'estrutura_regionais.json')
        catalog = build_admin_catalog(*(path.read_bytes() for path in paths), args.source_timezone)
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao de banco somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato da simulacao revisada.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_admin_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_monitor_admins_confirmada'
                else:
                    result['banco'] = inspect_admin_catalog(connection, catalog)
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
