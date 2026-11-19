"""Manually synchronize frozen regional metadata without changing parent identities or SLA."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_regional_metadata_catalog import (
    SOURCE, SOURCE_COLUMNS, ROW_COLUMNS, FIELDS, LOCK, _hash, build_catalog,
)
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from scripts.database.import_server_catalog import _identity

MARKER_COLUMNS = ('capturado_em,publicacao_textual,arquivo_origem_sha256,'
                  'metadados_sha256,digest_carga,regionais')


def _marker(catalog):
    return (*catalog.source[2:], len(catalog.rows))


def _publication_flags(previous, current, previous_hash, current_hash):
    try:
        old = datetime.fromisoformat(previous.replace('Z', '+00:00'))
        new = datetime.fromisoformat(current.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        raise ImportErrorSafe('Publicacao SQL invalida; revise antes de sincronizar.') from None
    incompatible = (old.utcoffset() is None) != (new.utcoffset() is None)
    # Naive values are ordered only on their declared wall-clock axis, never converted to UTC.
    return {'fuso_declarado_incompativel': incompatible,
            'publicacao_mais_antiga': not incompatible and new < old,
            'conflito_mesma_publicacao': not incompatible and new == old and previous_hash != current_hash}


def _state(cursor):
    cursor.execute('SELECT ' + SOURCE_COLUMNS + ' FROM operacional.fontes_metadados_regionais WHERE id=%s', (SOURCE,))
    initial = cursor.fetchone()
    if initial is None or initial[:2] != (SOURCE, 1):
        raise ImportErrorSafe('Carga inicial de metadados ausente ou incompativel.')
    cursor.execute('SELECT ' + MARKER_COLUMNS + ' FROM operacional.sincronizacoes_metadados_regionais WHERE fonte_id=%s', (SOURCE,))
    marker = cursor.fetchone()
    cursor.execute('SELECT ' + ROW_COLUMNS + ',presente_na_captura FROM operacional.metadados_regionais WHERE fonte_id=%s', (SOURCE,))
    rows = cursor.fetchall()
    if not rows:
        raise ImportErrorSafe('Metadados SQL vazios; sincronizacao nao substitui carga inicial.')
    if marker is None:
        projected = [dict(zip(FIELDS, row[:-1])) for row in sorted(rows)]
        if _hash(projected) != initial[5] or not all(row[-1] is True for row in rows):
            raise ImportErrorSafe('Metadados iniciais SQL divergentes; carga preservada.')
    cursor.execute('SELECT codigo,nome,presente_no_cadastro FROM operacional.regionais')
    parents = {row[0]: row[1:] for row in cursor.fetchall()}
    return initial, marker, rows, parents


def _report(state, catalog):
    initial, marker, rows, parents = state
    previous = marker or (*initial[2:], len(rows))
    active = tuple(sorted(row[:-1] for row in rows if row[-1]))
    missing = sum(row[0] not in parents for row in catalog.rows)
    names = sum(row[0] in parents and parents[row[0]][0] != row[1] for row in catalog.rows)
    absent = sum(row[0] in parents and parents[row[0]][1] is not True for row in catalog.rows)
    compatible = not (missing or names or absent)
    return {'banco_metadados_preservados': len(rows), 'banco_metadados_presentes': len(active),
            'regionais_ausentes_no_banco': missing, 'nomes_regionais_divergentes': names,
            'regionais_fora_do_cadastro_atual': absent,
            'ultima_captura_sincronizada': marker[0].isoformat() if marker else None,
            'captura_mais_antiga': catalog.source[2] < previous[0],
            'conflito_mesmo_horario': catalog.source[2] == previous[0] and catalog.digest != previous[4],
            **_publication_flags(previous[1], catalog.source[3], previous[3], catalog.source[5]),
            'conteudo_atual_confere': compatible and active == catalog.rows,
            'conteudo_ja_sincronizado': compatible and marker == _marker(catalog) and active == catalog.rows}


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
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga ou sincronizacao de metadados em andamento.')
        cursor.execute('LOCK TABLE operacional.regionais IN SHARE MODE')
        state = _state(cursor)
        report = _report(state, catalog)
        if any(report[key] for key in ('regionais_ausentes_no_banco', 'nomes_regionais_divergentes',
                                       'regionais_fora_do_cadastro_atual')):
            raise ImportErrorSafe('Cadastro principal divergente. Nenhum codigo ou nome sera alterado.')
        if any(report[key] for key in ('captura_mais_antiga', 'conflito_mesmo_horario',
                                       'fuso_declarado_incompativel', 'publicacao_mais_antiga', 'conflito_mesma_publicacao')):
            raise ImportErrorSafe('Captura/publicacao antiga, conflitante ou fuso divergente. Banco preservado.')
        if report['conteudo_ja_sincronizado']:
            return 'ja_sincronizado'
        progress.phase = 'sincronizacao_metadados'
        if not report['conteudo_atual_confere']:
            cursor.execute('UPDATE operacional.metadados_regionais SET presente_na_captura=false, '
                           'atualizado_em=CURRENT_TIMESTAMP WHERE fonte_id=%s AND presente_na_captura', (SOURCE,))
            assignments = ','.join(column + '=EXCLUDED.' + column for column in ROW_COLUMNS.split(',') if column != 'codigo_regional')
            for row in catalog.rows:
                cursor.execute('INSERT INTO operacional.metadados_regionais (fonte_id,' + ROW_COLUMNS + ',presente_na_captura,atualizado_em) '
                               'VALUES (%s,%s,%s,%s,%s,%s,true,CURRENT_TIMESTAMP) '
                               'ON CONFLICT (codigo_regional) DO UPDATE SET ' + assignments +
                               ',presente_na_captura=true,atualizado_em=CURRENT_TIMESTAMP', (SOURCE, *row))
        cursor.execute('INSERT INTO operacional.sincronizacoes_metadados_regionais (fonte_id,' + MARKER_COLUMNS + ') '
                       'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (fonte_id) DO UPDATE SET ' +
                       ','.join(column + '=EXCLUDED.' + column for column in MARKER_COLUMNS.split(',')) +
                       ',sincronizado_em=CURRENT_TIMESTAMP', (SOURCE, *_marker(catalog)))
        progress.phase = 'conferencia_final'
        if not _report(_state(cursor), catalog)['conteudo_ja_sincronizado']:
            raise ImportErrorSafe('Conferencia final divergente. Transacao cancelada.')
        return 'sincronizado'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--source', type=Path, help='Captura congelada somente dos metadados.')
    sources.add_argument('--current', action='store_true', help='Confere cadastro atual contra SQL, sem gravar.')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_captura')
    try:
        if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise ImportErrorSafe('Execute a operacao SQL somente no Rigel.')
        if args.current:
            if args.apply:
                raise ImportErrorSafe('--current e somente leitura; gravacao manual exige --source congelado.')
            from services.operational_regional_metadata import read_current_catalog, automatic_enabled
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
        result = catalog.summary()
        if args.current:
            result['sincronizacao_automatica_metadados'] = automatic_enabled()
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
