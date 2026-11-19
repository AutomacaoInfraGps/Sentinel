"""Capture only regional metadata, then inspect or import the reviewed frozen projection."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_regional_metadata_sources import UFS
from scripts.database.audit_ap_sources import _time_kind
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error, _unique_keys
from scripts.database.import_server_catalog import _identity, _text

SOURCE = 'sentinel_metadados_regionais'
FIELDS = ('codigo', 'nome', 'descricao', 'estado', 'uf')
TABLES = ('fontes_metadados_regionais', 'metadados_regionais')
SOURCE_COLUMNS = 'id,versao,capturado_em,publicacao_textual,arquivo_origem_sha256,metadados_sha256,digest_carga'
ROW_COLUMNS = 'codigo_regional,nome_origem,descricao,estado,uf'
ENVELOPE = {'version', 'fonte', 'capturado_em', 'publicacao_textual', 'sha256_arquivo_origem',
            'sha256_metadados', 'digest_carga', 'regionais'}
LOCK = (0x524d4401, 25)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def _json(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise ImportErrorSafe('Arquivo acima do limite de leitura.')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError):
        raise ImportErrorSafe('JSON invalido ou com chaves duplicadas.') from None


def _strict_text(value, length):
    text = _text(value, length, required=True)
    if value != text:
        raise ImportErrorSafe('Espacos externos exigem revisao; nenhum texto sera normalizado silenciosamente.')
    return text


def _rows(records):
    if not isinstance(records, list) or not 0 < len(records) <= 10000:
        raise ImportErrorSafe('Lista regional vazia ou invalida.')
    rows, codes = [], set()
    for record in records:
        if not isinstance(record, dict) or set(record) != set(FIELDS):
            raise ImportErrorSafe('Campos fora do escopo dos metadados regionais.')
        code = _strict_text(record['codigo'], 120)
        if code != code.upper() or code in codes:
            raise ImportErrorSafe('Codigo regional invalido ou repetido.')
        codes.add(code)
        row = (code, _strict_text(record['nome'], 240), _strict_text(record['descricao'], 500),
               _strict_text(record['estado'], 2), _strict_text(record['uf'], 2))
        if row[3] not in UFS or row[4] != row[3]:
            raise ImportErrorSafe('UF desconhecida ou estado/uf divergentes. Nenhum vinculo sera inferido.')
        rows.append(row)
    return tuple(sorted(rows))


def capture_payload(raw, now=None):
    original = _json(raw)
    entries = original.get('regionais') if isinstance(original, dict) else None
    config = original.get('configuracao') if isinstance(original, dict) else None
    if not isinstance(entries, dict) or not isinstance(config, dict):
        raise ImportErrorSafe('Envelope do cadastro invalido.')
    records = []
    for code, entry in entries.items():
        if not isinstance(entry, dict):
            raise ImportErrorSafe('Registro regional invalido.')
        records.append({'codigo': code, **{key: entry.get(key) for key in FIELDS if key != 'codigo'}})
    rows = _rows(records)
    publication = _strict_text(config.get('ultima_atualizacao'), 80)
    if _time_kind(publication) not in ('sem_fuso', 'com_fuso'):
        raise ImportErrorSafe('Publicacao textual invalida; nenhum horario sera adivinhado.')
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.utcoffset() is None:
        raise ImportErrorSafe('Captura exige horario com fuso.')
    records = [dict(zip(FIELDS, row)) for row in rows]
    payload = {'version': 1, 'fonte': SOURCE, 'capturado_em': timestamp.astimezone(timezone.utc).isoformat(),
               'publicacao_textual': publication, 'sha256_arquivo_origem': hashlib.sha256(raw).hexdigest(),
               'sha256_metadados': _hash(records), 'regionais': records}
    payload['digest_carga'] = _hash(payload)
    return payload


@dataclass(frozen=True, repr=False)
class RegionalMetadataCatalog:
    digest: str
    source: tuple
    rows: tuple

    def summary(self):
        return {'version': 1, 'fonte': SOURCE, 'digest_carga': self.digest,
                'capturado_em': self.source[2].isoformat(), 'publicacao_cadastro': _time_kind(self.source[3]),
                'sha256_arquivo_origem': self.source[4], 'sha256_metadados': self.source[5],
                'regionais': len(self.rows), 'com_descricao': len(self.rows), 'com_estado_uf_concordantes': len(self.rows),
                'estado_uf_inferidos': False, 'cadastro_original_modificado': False,
                'credenciais_exportadas': False, 'sincronizacao_automatica_metadados': False}


def build_catalog(raw):
    payload = _json(raw)
    if not isinstance(payload, dict) or set(payload) != ENVELOPE:
        raise ImportErrorSafe('Formato de captura invalido.')
    if type(payload['version']) is not int or payload['version'] != 1 or payload['fonte'] != SOURCE:
        raise ImportErrorSafe('Fonte ou versao de captura divergente.')
    for key in ('sha256_arquivo_origem', 'sha256_metadados', 'digest_carga'):
        value = payload[key]
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ImportErrorSafe('Hash de captura invalido.')
    rows = _rows(payload['regionais'])
    if [dict(zip(FIELDS, row)) for row in rows] != payload['regionais']:
        raise ImportErrorSafe('Captura nao canonica.')
    if _hash(payload['regionais']) != payload['sha256_metadados'] or _hash(
            {key: value for key, value in payload.items() if key != 'digest_carga'}) != payload['digest_carga']:
        raise ImportErrorSafe('Captura alterada; hashes divergentes.')
    captured_text = _strict_text(payload['capturado_em'], 80)
    if _time_kind(captured_text) != 'com_fuso':
        raise ImportErrorSafe('Captura exige horario ISO com fuso.')
    captured = datetime.fromisoformat(captured_text.replace('Z', '+00:00')).astimezone(timezone.utc)
    publication = _strict_text(payload['publicacao_textual'], 80)
    if _time_kind(publication) not in ('sem_fuso', 'com_fuso'):
        raise ImportErrorSafe('Publicacao textual invalida.')
    source = (SOURCE, 1, captured, publication, payload['sha256_arquivo_origem'], payload['sha256_metadados'], payload['digest_carga'])
    return RegionalMetadataCatalog(payload['digest_carga'], source, rows)


def _destination(cursor, catalog):
    cursor.execute('SELECT codigo,nome,presente_no_cadastro FROM operacional.regionais')
    existing = {row[0]: row[1:] for row in cursor.fetchall()}
    missing = sum(row[0] not in existing for row in catalog.rows)
    names = sum(row[0] in existing and existing[row[0]][0] != row[1] for row in catalog.rows)
    absent = sum(row[0] in existing and existing[row[0]][1] is not True for row in catalog.rows)
    counts = {}
    for table in TABLES:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return {'regionais_ausentes_no_banco': missing, 'nomes_regionais_divergentes': names,
            'regionais_fora_do_cadastro_atual': absent, 'contagens': counts,
            'tabelas_metadados_vazias': not any(counts.values())}


def _matches(cursor, catalog):
    cursor.execute('SELECT ' + SOURCE_COLUMNS + ' FROM operacional.fontes_metadados_regionais')
    sources = cursor.fetchall()
    cursor.execute('SELECT ' + ROW_COLUMNS + ' FROM operacional.metadados_regionais WHERE fonte_id=%s', (SOURCE,))
    rows = tuple(sorted(cursor.fetchall()))
    return sources == [catalog.source] and rows == catalog.rows


def inspect_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        result = _destination(cursor, catalog)
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
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga de metadados regionais em andamento.')
        cursor.execute('LOCK TABLE operacional.regionais IN SHARE MODE')
        for table in TABLES:
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        destination = _destination(cursor, catalog)
        if any(destination[key] for key in ('regionais_ausentes_no_banco', 'nomes_regionais_divergentes', 'regionais_fora_do_cadastro_atual')):
            raise ImportErrorSafe('Regionais do banco divergentes; nenhum cadastro ou vinculo sera alterado.')
        if not destination['tabelas_metadados_vazias']:
            raise ImportErrorSafe('Metadados ja carregados. Nao repetir a carga inicial.')
        progress.phase = 'insercao_metadados_regionais'
        cursor.execute('INSERT INTO operacional.fontes_metadados_regionais (' + SOURCE_COLUMNS + ') '
                       'VALUES (%s,%s,%s,%s,%s,%s,%s)', catalog.source)
        for row in catalog.rows:
            cursor.execute('INSERT INTO operacional.metadados_regionais (fonte_id,' + ROW_COLUMNS + ') '
                           'VALUES (%s,%s,%s,%s,%s,%s)', (SOURCE, *row))
        progress.phase = 'conferencia_final'
        if not _matches(cursor, catalog):
            raise ImportErrorSafe('Conferencia final divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Captura JSON congelada, nao cadastro com dispositivos.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--capture', type=Path, help='Cria novo JSON de metadados sem credenciais; nao sobrescreve.')
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        if (args.check_database or args.apply) and args.source is None:
            raise ImportErrorSafe('Operacao SQL exige --source congelado revisado.')
        if args.capture and args.source:
            raise ImportErrorSafe('--capture usa somente a fonte atual, nao outra captura.')
        path = args.source or ROOT / 'estrutura_regionais.json'
        raw = path.read_bytes()
        payload = None if args.source else capture_payload(raw)
        catalog = build_catalog(raw if args.source else json.dumps(payload, ensure_ascii=True).encode())
        if path.read_bytes() != raw:
            raise ImportErrorSafe('Fonte mudou durante a leitura. Nenhuma gravacao iniciada.')
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.summary()}
        if args.capture:
            with args.capture.open('x', encoding='utf-8') as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=True)
            result['modo'] = 'captura_congelada_sem_postgresql'
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao SQL somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato da captura revisada.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_metadados_regionais_confirmada'
                else:
                    result['banco'] = inspect_catalog(connection, catalog)
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
