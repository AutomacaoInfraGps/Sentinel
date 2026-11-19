"""Manually synchronize frozen native RF snapshots, preserving absent records and the initial source."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_ap_radio_catalog import (
    SOURCE, SOURCE_COLUMNS, TABLE_COLUMNS, LOCK, build_catalog,
)
from scripts.database.capture_ap_radio_catalog import CaptureError, destination_status, summary
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from services.operational_postgres import _identity

RF_TABLES = tuple(table for table in TABLE_COLUMNS if table != 'fontes_radios_unifi')
MARKER_COLUMNS = ('capturado_em', 'publicacao_textual', 'arquivo_origem_sha256', 'projecao_sha256',
                  'digest_carga', 'aps', 'configuracoes', 'estatisticas')


def _marker(catalog):
    return (*catalog.rows['fontes_radios_unifi'][0][5:], *(len(catalog.rows[table]) for table in RF_TABLES))


def _state(cursor):
    cursor.execute('SELECT ' + ','.join(SOURCE_COLUMNS) + ' FROM operacional.fontes_radios_unifi WHERE id=%s', (SOURCE,))
    initial = cursor.fetchone()
    if initial is None or initial[:2] != (SOURCE, 1):
        raise ImportErrorSafe('Carga inicial RF ausente ou incompativel.')
    cursor.execute('SELECT ' + ','.join(MARKER_COLUMNS) + ' FROM operacional.sincronizacoes_radios_unifi WHERE fonte_id=%s', (SOURCE,))
    marker = cursor.fetchone()
    rows = {}
    for table in RF_TABLES:
        cursor.execute('SELECT ' + ','.join(TABLE_COLUMNS[table]) + ',presente_na_captura FROM operacional.' + table + ' WHERE fonte_id=%s', (SOURCE,))
        rows[table] = tuple(sorted(cursor.fetchall()))
    if not rows[RF_TABLES[0]]:
        raise ImportErrorSafe('Recebimentos SQL vazios; sincronizacao nao substitui carga inicial.')
    return initial, marker, rows


def _publication_flags(previous, current, old_hash, new_hash):
    try:
        old = datetime.fromisoformat(previous.replace('Z', '+00:00'))
        new = datetime.fromisoformat(current.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        raise ImportErrorSafe('Publicacao SQL invalida; revise antes de sincronizar.') from None
    incompatible = (old.utcoffset() is None) != (new.utcoffset() is None)
    return {'fuso_declarado_incompativel': incompatible,
            'publicacao_mais_antiga': not incompatible and new < old,
            'conflito_mesma_publicacao': not incompatible and new == old and old_hash != new_hash}


def _report(state, catalog, destination):
    initial, marker, rows = state
    source = catalog.rows['fontes_radios_unifi'][0]
    active = {table: tuple(row[:-1] for row in rows[table] if row[-1]) for table in RF_TABLES}
    equal = all(active[table] == catalog.rows[table] for table in RF_TABLES)
    previous = marker or (*initial[5:], *(len(rows[table]) for table in RF_TABLES))
    initial_required = marker is None and source != initial
    initial_bad = marker is None and not initial_required and (not equal or any(not row[-1] for values in rows.values() for row in values))
    old_aps = {row[:3]: row for row in rows[RF_TABLES[0]]}
    incoming = {table: {} for table in RF_TABLES[1:]}
    old_radios = {table: {} for table in RF_TABLES[1:]}
    for table in incoming:
        for row in catalog.rows[table]:
            incoming[table].setdefault(row[:3], []).append(row)
        for row in active[table]:
            old_radios[table].setdefault(row[:3], []).append(row)
    older = conflict = 0
    for row in catalog.rows[RF_TABLES[0]]:
        old = old_aps.get(row[:3])
        if old is None:
            continue
        older += row[4] < old[4]
        if row[4] == old[4]:
            conflict += (not old[-1] or row != old[:-1] or any(
                incoming[table].get(row[:3], []) != old_radios[table].get(row[:3], []) for table in incoming))
    compatible = initial[:5] == source[:5]
    current = destination['destino_compativel'] and compatible and equal
    return {**destination, 'tabelas_rf_conferidas': True,
            'fonte_inicial_compativel': compatible,
            'banco_contagens_preservadas': {table: len(rows[table]) for table in RF_TABLES},
            'banco_contagens_presentes': {table: len(active[table]) for table in RF_TABLES},
            'ultima_captura_sincronizada': marker[0].isoformat() if marker else None,
            'inicializacao_exige_captura_inicial': initial_required,
            'base_inicial_divergente': initial_bad,
            'captura_mais_antiga': source[5] < previous[0],
            'conflito_mesmo_horario': source[5] == previous[0] and catalog.digest != previous[4],
            **_publication_flags(previous[1], source[6], previous[3], source[8]),
            'aps_com_recebimento_mais_antigo': older,
            'aps_com_conflito_no_mesmo_recebimento': conflict,
            'conteudo_atual_confere': current,
            'conteudo_ja_sincronizado': current and marker == _marker(catalog)}


def inspect_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        state = _state(cursor)
        return _report(state, catalog, destination_status(cursor, catalog.payload))


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
            raise ImportErrorSafe('Outra carga ou sincronizacao RF em andamento.')
        for table in ('controladoras_unifi', 'sites_unifi', 'aps_unifi'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN SHARE MODE')
        for table in (*RF_TABLES, 'sincronizacoes_radios_unifi'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        state = _state(cursor)
        destination = destination_status(cursor, catalog.payload)
        report = _report(state, catalog, destination)
        if not report['destino_compativel'] or not report['fonte_inicial_compativel']:
            raise ImportErrorSafe('Destino RF divergente. Fonte inicial e vinculos existentes preservados.')
        if report['inicializacao_exige_captura_inicial']:
            raise ImportErrorSafe('Primeira sincronizacao exige a captura congelada da carga inicial conferida.')
        blocked = ('base_inicial_divergente', 'captura_mais_antiga', 'conflito_mesmo_horario',
                   'fuso_declarado_incompativel', 'publicacao_mais_antiga', 'conflito_mesma_publicacao',
                   'aps_com_recebimento_mais_antigo', 'aps_com_conflito_no_mesmo_recebimento')
        if any(report[key] for key in blocked):
            raise ImportErrorSafe('Captura/publicacao/recebimento antigo, conflitante ou base divergente. Banco preservado.')
        if _marker(catalog)[0] > datetime.now(timezone.utc):
            raise ImportErrorSafe('Captura RF com horario futuro.')
        if report['conteudo_ja_sincronizado']:
            return 'ja_sincronizado'
        progress.phase = 'sincronizacao_rf'
        if not report['conteudo_atual_confere']:
            for table in RF_TABLES:
                cursor.execute('UPDATE operacional.' + table + ' SET presente_na_captura=false, '
                               'atualizado_em=CURRENT_TIMESTAMP WHERE fonte_id=%s AND presente_na_captura', (SOURCE,))
            for table in RF_TABLES:
                columns = TABLE_COLUMNS[table]
                key_size = 3 if table == RF_TABLES[0] else 4
                placeholders = ','.join('%s::jsonb' if column == 'canal_valor' else '%s' for column in columns)
                assignments = ','.join(column + '=EXCLUDED.' + column for column in columns[key_size:])
                sql = ('INSERT INTO operacional.' + table + ' (' + ','.join(columns) + ',presente_na_captura,atualizado_em) '
                       'VALUES (' + placeholders + ',true,CURRENT_TIMESTAMP) ON CONFLICT (' + ','.join(columns[:key_size]) +
                       ') DO UPDATE SET ' + assignments + ',presente_na_captura=true,atualizado_em=CURRENT_TIMESTAMP')
                for row in catalog.rows[table]:
                    params = tuple(json.dumps(value) if column == 'canal_valor' and value is not None else value
                                   for column, value in zip(columns, row))
                    cursor.execute(sql, params)
        cursor.execute('INSERT INTO operacional.sincronizacoes_radios_unifi (fonte_id,' + ','.join(MARKER_COLUMNS) + ') '
                       'VALUES (' + ','.join(['%s'] * (len(MARKER_COLUMNS) + 1)) + ') '
                       'ON CONFLICT (fonte_id) DO UPDATE SET ' +
                       ','.join(column + '=EXCLUDED.' + column for column in MARKER_COLUMNS) + ',sincronizado_em=CURRENT_TIMESTAMP',
                       (SOURCE, *_marker(catalog)))
        progress.phase = 'conferencia_final'
        if not _report(_state(cursor), catalog, destination)['conteudo_ja_sincronizado']:
            raise ImportErrorSafe('Conferencia final RF divergente. Transacao cancelada.')
        return 'sincronizado'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Captura RF congelada revisada.')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_captura')
    try:
        if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise ImportErrorSafe('Execute a operacao SQL somente no Rigel.')
        raw = args.source.read_bytes()
        catalog = build_catalog(raw)
        if args.source.read_bytes() != raw:
            raise CaptureError('Captura mudou durante a leitura.')
        if args.apply and args.expected_digest != catalog.digest:
            raise CaptureError('Gravacao exige o digest exato da captura revisada.')
        from services.operational_postgres import connect_collector

        result = summary(catalog.payload)
        progress.phase = 'conexao'
        with connect_collector(read_only=not args.apply) as connection:
            if args.apply:
                result['modo'] = write_catalog(connection, catalog, progress=progress)
            else:
                result.update(inspect_catalog(connection, catalog))
                result['modo'] = 'conferencia_sem_gravacao'
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
