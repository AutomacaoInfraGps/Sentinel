"""Initial RF import from a reviewed frozen capture; no collection or automatic sync."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.capture_ap_radio_catalog import (
    CaptureError, METRICS, SOURCE, destination_status, summary, validate_capture,
)
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from services.operational_postgres import _identity

SOURCE_COLUMNS = ('id', 'versao', 'controladora_id', 'host_origem', 'porta_origem', 'capturado_em',
                  'publicacao_textual', 'arquivo_origem_sha256', 'projecao_sha256', 'digest_carga')
AP_COLUMNS = ('fonte_id', 'controladora_id', 'mac', 'site_id_origem', 'recebido_em', 'medido_em',
              'data_medicao_confirmada', 'ap_online_declarado', 'configuracoes_situacao',
              'estatisticas_situacao', 'quantidade_configuracoes', 'quantidade_estatisticas')
CONFIG_COLUMNS = ('fonte_id', 'controladora_id', 'mac', 'nome_interface', 'banda_declarada',
                  'banda_situacao', 'canal_valor', 'canal_situacao')
STATS_COLUMNS = CONFIG_COLUMNS + tuple(column for metric in METRICS for column in (metric, metric + '_situacao'))
TABLE_COLUMNS = {
    'fontes_radios_unifi': SOURCE_COLUMNS, 'recebimentos_radios_unifi': AP_COLUMNS,
    'configuracoes_radios_unifi': CONFIG_COLUMNS, 'estatisticas_radios_unifi': STATS_COLUMNS,
}
LOCK = (0x52464901, 27)


@dataclass(frozen=True, repr=False)
class RadioCatalog:
    payload: dict = field(repr=False)
    rows: dict = field(repr=False)

    @property
    def digest(self):
        return self.payload['digest_carga']


def build_catalog(raw):
    payload = validate_capture(raw)
    if len(payload['publicacao_textual']) > 80:
        raise CaptureError('Publicacao textual acima do limite SQL.')
    controller = payload['controladora']
    source = (SOURCE, 1, controller['id'], controller['host'], controller['porta'],
              datetime.fromisoformat(payload['capturado_em'].replace('Z', '+00:00')),
              payload['publicacao_textual'], payload['sha256_arquivo_origem'],
              payload['sha256_projecao'], payload['digest_carga'])
    aps, configs, stats = [], [], []
    for ap in payload['aps']:
        identity = (SOURCE, controller['id'], ap['mac'])
        aps.append((*identity, ap['site_id'], datetime.fromisoformat(ap['recebido_em']),
                    None, False, ap['ap_online_declarado'], ap['configuracoes']['situacao'],
                    ap['estatisticas']['situacao'], len(ap['configuracoes']['registros']),
                    len(ap['estatisticas']['registros'])))
        for name, target in (('configuracoes', configs), ('estatisticas', stats)):
            for row in ap[name]['registros']:
                states = row['situacao_campos']
                record = (*identity, row['nome_interface'], row['banda_declarada'],
                          states['banda_declarada'], row['canal'], states['canal'])
                if name == 'estatisticas':
                    record += tuple(value for metric in METRICS for value in (row[metric], states[metric]))
                target.append(record)
    return RadioCatalog(payload, {
        'fontes_radios_unifi': (source,), 'recebimentos_radios_unifi': tuple(sorted(aps)),
        'configuracoes_radios_unifi': tuple(sorted(configs)), 'estatisticas_radios_unifi': tuple(sorted(stats)),
    })


def _counts(cursor):
    counts = {}
    for table in TABLE_COLUMNS:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return counts


def _matches(cursor, catalog):
    matches = True
    for table, columns in TABLE_COLUMNS.items():
        cursor.execute('SELECT ' + ','.join(columns) + ' FROM operacional.' + table)
        matches = tuple(sorted(cursor.fetchall())) == catalog.rows[table] and matches
    return matches


def inspect_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        result = destination_status(cursor, catalog.payload)
        counts = _counts(cursor)
        return {**result, 'tabelas_rf_conferidas': True, 'contagens': counts,
                'tabelas_rf_vazias': not any(counts.values()),
                'conteudo_confere_com_captura': _matches(cursor, catalog)}


def write_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'validacao_destino'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga RF em andamento.')
        for table in ('controladoras_unifi', 'sites_unifi', 'aps_unifi'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN SHARE MODE')
        for table in TABLE_COLUMNS:
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        if not destination_status(cursor, catalog.payload)['destino_compativel']:
            raise ImportErrorSafe('Destino RF divergente; nenhum vinculo existente sera alterado.')
        if any(_counts(cursor).values()):
            raise ImportErrorSafe('RF ja carregada. Nao repetir a carga inicial.')
        if datetime.fromisoformat(catalog.payload['capturado_em'].replace('Z', '+00:00')) > datetime.now(timezone.utc):
            raise ImportErrorSafe('Captura RF com horario futuro.')
        progress.phase = 'insercao_catalogo_rf'
        for table, columns in TABLE_COLUMNS.items():
            placeholders = ','.join('%s::jsonb' if column == 'canal_valor' else '%s' for column in columns)
            sql = 'INSERT INTO operacional.' + table + ' (' + ','.join(columns) + ') VALUES (' + placeholders + ')'
            for row in catalog.rows[table]:
                params = tuple(json.dumps(value) if column == 'canal_valor' and value is not None else value
                               for column, value in zip(columns, row))
                cursor.execute(sql, params)
        progress.phase = 'conferencia_final'
        if not _matches(cursor, catalog):
            raise ImportErrorSafe('Conferencia RF divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Captura RF congelada, nao JSON bruto UniFi.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_captura')
    try:
        raw = args.source.read_bytes()
        catalog = build_catalog(raw)
        if args.source.read_bytes() != raw:
            raise CaptureError('Captura mudou durante a leitura. Nenhuma gravacao iniciada.')
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **summary(catalog.payload)}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise CaptureError('Execute a operacao SQL somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise CaptureError('Gravacao exige o digest exato da captura revisada.')
            from services.operational_postgres import connect_collector

            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_radios_unifi_confirmada'
                else:
                    result['banco'] = inspect_catalog(connection, catalog)
                    result['modo'] = 'conferencia_somente_leitura'
                progress.phase = 'finalizacao_transacao'
            result.update(postgresql_acessado=True, vinculos_sql_conferidos=True)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (CaptureError, ImportErrorSafe) as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(progress.phase, exc)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
