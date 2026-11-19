"""Initial import of frozen firmware metadata; no device bindings, jobs or live collection."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.capture_switch_firmware_catalog import SOURCE, _json, validate, summary
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from scripts.database.import_server_catalog import _identity

TABLES = ('fontes_firmware_switches', 'inventario_firmware_switches')
BOOTSTRAP_LOCK = (0x46575201, 23)
SOURCE_COLUMNS = 'id,versao,capturado_em,inventario_projetado_sha256,cache_status_sha256,digest_carga'
ROW_COLUMNS = ('ordem,host_origem,nome_origem,regional_origem,ip_origem,modelo_declarado,'
               'versao_declarada,consulta_textual,consulta_declarada_em,origem_consulta,'
               'diagnostico_vinculo,vinculo_confirmado')


def _utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


@dataclass(frozen=True, repr=False)
class FirmwareCatalog:
    digest: str
    source: tuple
    rows: tuple
    report: dict


def build_catalog(raw):
    payload = validate(_json(raw))
    rows = []
    for order, row in enumerate(payload['registros'], 1):
        rows.append((order, row['host'], row['switch_name'], row['regional'], row['ip_address'],
                     row['model'], row['current_version'], row['checked_at_utc'],
                     _utc(row['checked_at_utc']), row['source'], row['diagnostico_vinculo'], False))
    source = (SOURCE, payload['version'], _utc(payload['capturado_em']),
              payload['sha256_inventario_projetado'], payload['sha256_cache_status'], payload['digest_carga'])
    return FirmwareCatalog(payload['digest_carga'], source, tuple(rows), summary(payload))


def _inspect(cursor):
    counts = {}
    for table in TABLES:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return {'contagens': counts, 'tabelas_firmware_vazias': not any(counts.values())}


def _matches(cursor, catalog):
    cursor.execute('SELECT ' + SOURCE_COLUMNS + ' FROM operacional.fontes_firmware_switches ORDER BY id')
    sources = cursor.fetchall()
    cursor.execute('SELECT ' + ROW_COLUMNS + ' FROM operacional.inventario_firmware_switches '
                   'WHERE fonte_id=%s ORDER BY ordem', (SOURCE,))
    rows = cursor.fetchall()
    return sources == [catalog.source] and tuple(rows) == catalog.rows


def inspect_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        result = _inspect(cursor)
        result['conteudo_confere_com_captura'] = _matches(cursor, catalog)
        return result


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
            raise ImportErrorSafe('Outra carga inicial de firmware em andamento.')
        for table in TABLES:
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        if not _inspect(cursor)['tabelas_firmware_vazias']:
            raise ImportErrorSafe('Firmware ja carregado. Nao repetir a carga inicial.')
        progress.phase = 'insercao_firmware'
        cursor.execute('INSERT INTO operacional.fontes_firmware_switches (' + SOURCE_COLUMNS + ') '
                       'VALUES (%s,%s,%s,%s,%s,%s)', catalog.source)
        for row in catalog.rows:
            cursor.execute('INSERT INTO operacional.inventario_firmware_switches (fonte_id,' + ROW_COLUMNS + ') '
                           'VALUES (' + ','.join(['%s'] * 13) + ')', (SOURCE, *row))
        progress.phase = 'conferencia_final'
        if not _matches(cursor, catalog):
            raise ImportErrorSafe('Conferencia final do firmware divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='JSON congelado, nao o arquivo SQLite.')
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
            raise ImportErrorSafe('Captura mudou durante a leitura. Nenhuma gravacao iniciada.')
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.report}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao SQL somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato da captura congelada revisada.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_firmware_confirmada'
                else:
                    result['banco'] = inspect_catalog(connection, catalog)
                    result['modo'] = 'conferencia_somente_leitura'
                result['postgresql_acessado'] = True
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
