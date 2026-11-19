"""Inspect or manually synchronize a frozen firmware capture, without jobs or device bindings."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.capture_switch_firmware_catalog import COLUMNS, _hash
from scripts.database.import_switch_firmware_catalog import (
    SOURCE, SOURCE_COLUMNS, ROW_COLUMNS, BOOTSTRAP_LOCK, build_catalog,
)
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from scripts.database.import_server_catalog import _identity

MARKER_COLUMNS = 'capturado_em,digest_carga,inventario_projetado_sha256,cache_status_sha256,registros'


def _marker(catalog):
    return (catalog.source[2], catalog.digest, catalog.source[3], catalog.source[4], len(catalog.rows))


def _state(cursor):
    cursor.execute('SELECT ' + SOURCE_COLUMNS + ' FROM operacional.fontes_firmware_switches WHERE id=%s', (SOURCE,))
    initial = cursor.fetchone()
    if initial is None or initial[:2] != (SOURCE, 1):
        raise ImportErrorSafe('Carga inicial de firmware ausente ou incompativel.')
    cursor.execute('SELECT ' + MARKER_COLUMNS + ' FROM operacional.sincronizacoes_firmware_switches WHERE fonte_id=%s', (SOURCE,))
    marker = cursor.fetchone()
    cursor.execute('SELECT ' + ROW_COLUMNS + ',presente_na_captura FROM operacional.inventario_firmware_switches '
                   'WHERE fonte_id=%s', (SOURCE,))
    rows = cursor.fetchall()
    if not rows:
        raise ImportErrorSafe('Inventario SQL vazio; sincronizacao nao substitui carga inicial.')
    if marker is None:
        projected = [dict(zip(COLUMNS, (row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[9])))
                     for row in sorted(rows, key=lambda row: row[1])]
        if _hash(projected) != initial[3] or not all(row[-1] is True for row in rows):
            raise ImportErrorSafe('Inventario inicial SQL divergente. Revise antes de sincronizar.')
    return initial, marker, rows


def _report(state, catalog):
    initial, marker, rows = state
    active = tuple(sorted((row[:-1] for row in rows if row[-1]), key=lambda row: row[0]))
    last_time, last_digest = (marker[0], marker[1]) if marker else (initial[2], initial[-1])
    return {'banco_registros_preservados': len(rows), 'banco_registros_presentes': len(active),
            'ultima_captura_sincronizada': marker[0].isoformat() if marker else None,
            'captura_mais_antiga': catalog.source[2] < last_time,
            'conflito_mesmo_horario': catalog.source[2] == last_time and catalog.digest != last_digest,
            'conteudo_atual_confere': active == catalog.rows,
            'conteudo_ja_sincronizado': marker == _marker(catalog) and active == catalog.rows}


def inspect_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        return _report(_state(cursor), catalog)


def write_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'validacao_destino'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga ou sincronizacao de firmware em andamento.')
        state = _state(cursor)
        report = _report(state, catalog)
        if report['captura_mais_antiga'] or report['conflito_mesmo_horario']:
            raise ImportErrorSafe('Captura antiga ou conflitante. Nenhum dado sera substituido.')
        if report['conteudo_ja_sincronizado']:
            return 'ja_sincronizado'
        # A newer export is not evidence of a newer firmware observation for each host.
        previous = {row[1]: row for row in state[2]}
        for row in catalog.rows:
            old = previous.get(row[1])
            if old and (row[8] < old[8] or (row[8] == old[8] and row[1:10] != old[1:10])):
                raise ImportErrorSafe('Consulta de firmware antiga ou conflitante para host existente.')
        progress.phase = 'sincronizacao_firmware'
        if not report['conteudo_atual_confere']:
            cursor.execute('UPDATE operacional.inventario_firmware_switches SET presente_na_captura=false, '
                           'atualizado_em=CURRENT_TIMESTAMP WHERE fonte_id=%s AND presente_na_captura', (SOURCE,))
            columns = ROW_COLUMNS.split(',')
            assignments = ','.join(column + '=EXCLUDED.' + column for column in columns if column != 'host_origem')
            for row in catalog.rows:
                cursor.execute('INSERT INTO operacional.inventario_firmware_switches (fonte_id,' + ROW_COLUMNS + ',presente_na_captura,atualizado_em) '
                               'VALUES (' + ','.join(['%s'] * 13) + ',true,CURRENT_TIMESTAMP) '
                               'ON CONFLICT (fonte_id,host_origem) DO UPDATE SET ' + assignments +
                               ',presente_na_captura=true,atualizado_em=CURRENT_TIMESTAMP', (SOURCE, *row))
        marker_columns = MARKER_COLUMNS.split(',')
        cursor.execute('INSERT INTO operacional.sincronizacoes_firmware_switches (fonte_id,' + MARKER_COLUMNS + ') '
                       'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (fonte_id) DO UPDATE SET ' +
                       ','.join(column + '=EXCLUDED.' + column for column in marker_columns) +
                       ',sincronizado_em=CURRENT_TIMESTAMP', (SOURCE, *_marker(catalog)))
        progress.phase = 'conferencia_final'
        if not _report(_state(cursor), catalog)['conteudo_ja_sincronizado']:
            raise ImportErrorSafe('Conferencia final divergente. Transacao cancelada.')
        return 'sincronizado'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--source', type=Path, help='JSON congelado de firmware, nao SQLite.')
    sources.add_argument('--current', action='store_true', help='Confere fontes atuais contra SQL, sem gravar.')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_captura')
    try:
        if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise ImportErrorSafe('Execute a operacao SQL somente no Rigel.')
        if args.current:
            if args.apply:
                raise ImportErrorSafe('--current e somente leitura. Gravacao manual exige --source congelado.')
            from services.operational_switch_firmware import read_current_catalog, automatic_enabled
            catalog = read_current_catalog()
        else:
            raw = args.source.read_bytes()
            catalog = build_catalog(raw)
            if args.source.read_bytes() != raw:
                raise ImportErrorSafe('Captura mudou durante a leitura.')
        if args.apply and args.expected_digest != catalog.digest:
            raise ImportErrorSafe('Gravacao exige o digest exato da captura revisada.')
        from services.operational_postgres import connect_collector
        progress.phase = 'conexao'
        result = {**catalog.report, 'postgresql_acessado': True}
        if args.current:
            result['sincronizacao_automatica_firmware'] = automatic_enabled()
        with connect_collector(read_only=not args.apply) as connection:
            if args.apply:
                result['modo'] = write_catalog(connection, catalog, progress=progress)
            else:
                result.update(inspect_catalog(connection, catalog))
                result['modo'] = 'conferencia_sem_gravacao'
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
