"""Initial declared AD replication snapshot; no AD calls or changes to the web reader."""

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import (
    DatabaseProgress, ImportErrorSafe, _database_error, _observation, _unique_keys,
)
from scripts.database.import_server_catalog import _identity, _text

SOURCE_ID = 'sentinel_replicacao_ad_local'
TABLES = ('fontes_replicacao_ad', 'observacoes_replicacao_ad', 'erros_operacionais_replicacao_ad')
BOOTSTRAP_LOCK = (0x52455001, 19)
COUNTERS = ('parceiros', 'falhas', 'erros', 'replicacoes')
TOTALS = ('total_servidores', 'servidores_saudaveis', 'servidores_problemas')
ROW_COLUMNS = ('ordem,nome,nome_identidade,secao,status_declarado,delta_declarado,'
               'parceiros_declarados,falhas_declaradas,erros_declarados,replicacoes_declaradas,'
               'ultima_replicacao_textual,ultima_replicacao_declarada,detalhes_declarados')


@dataclass(frozen=True, repr=False)
class ReplicationCatalog:
    digest: str
    source_sha256: str
    source_timezone: str | None
    publication_text: str
    publication: datetime
    totals: tuple
    rows: tuple
    errors: tuple

    def summary(self):
        declared = dict(self.totals)
        unique = len({row[2] for row in self.rows})
        return {'digest_carga': self.digest, 'sha256_arquivo': self.source_sha256,
                'fonte': SOURCE_ID, 'fuso_legado': self.source_timezone,
                'publicacao_declarada_utc': self.publication.isoformat(),
                'registros': len(self.rows), 'controladores_distintos': unique,
                'por_secao': dict(Counter(row[3].lower() for row in self.rows)),
                'por_status_declarado': dict(Counter(row[4].lower() for row in self.rows)),
                'totais_declarados': declared, 'erros_operacionais': len(self.errors),
                'total_declarado_difere_de_linhas': declared.get('total_servidores') != len(self.rows),
                'total_declarado_difere_de_controladores': declared.get('total_servidores') != unique,
                'sem_ultima_replicacao_declarada': sum(row[11] is None for row in self.rows),
                'contadores_preservados_sem_reinterpretacao': True,
                'publicacao_nao_comprova_coleta_ad': True,
                'ultima_replicacao_nao_comprova_sucesso': True,
                'regionais_inferidas': False, 'repadmin_executado': False,
                'sincronizacao_automatica_replicacao_ad': False,
                'arquivo_origem_modificado': False}


def _number(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise ImportErrorSafe('Contador declarado invalido. Nenhum valor foi inferido.')
    return value


def _date(value, zone, *, required=False):
    text = _text(value, 80, required=required)
    if text is None:
        return None, None
    try:
        if 'T' not in text and ' ' not in text:
            raise ValueError()
        moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ImportErrorSafe('Data declarada invalida. Nenhuma data foi criada.') from None
    if moment.utcoffset() is None and zone is None:
        raise ImportErrorSafe('Data legada exige --source-timezone explicito.')
    return text, _observation(text, zone)


def build_replication_catalog(raw, source_timezone=None):
    zone = None
    if source_timezone is not None:
        try:
            if not isinstance(source_timezone, str) or not source_timezone:
                raise ValueError()
            zone = ZoneInfo(source_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ImportErrorSafe('Fuso IANA invalido ou indisponivel.') from None
    payload = None
    for encoding in ('utf-8-sig', 'latin1'):
        try:
            payload = json.loads(raw.decode(encoding), object_pairs_hook=_unique_keys)
            break
        except (ValueError, UnicodeError):
            continue
    if not isinstance(payload, dict) or not isinstance(payload.get('servidores'), list) or not payload['servidores']:
        raise ImportErrorSafe('Carga restrita a fonte local com lista servidores nao vazia.')
    if not isinstance(payload.get('erros_operacionais'), list):
        raise ImportErrorSafe('Lista explicita de erros operacionais obrigatoria, inclusive se vazia.')
    publication_text, publication = _date(payload.get('timestamp'), zone, required=True)
    totals = tuple((key, _number(payload[key])) for key in TOTALS if key in payload)
    if len(totals) != len(TOTALS):
        raise ImportErrorSafe('Totais declarados ausentes. Revise a fonte antes da carga.')
    rows, identities = [], set()
    for order, record in enumerate(payload['servidores'], 1):
        if not isinstance(record, dict):
            raise ImportErrorSafe('Linha de replicacao invalida.')
        name = _text(record.get('nome'), 255, required=True)
        identity = name.casefold()
        section = _text(record.get('tipo'), 20, required=True)
        status = _text(record.get('status'), 40, required=True)
        if section not in ('Origem', 'Destino') or identity in ('desconhecido', 'erro.galaxia.local'):
            raise ImportErrorSafe('Secao ou identidade nao comprovada exige revisao antes da carga.')
        if status.lower() not in ('ok', 'warning', 'error', 'unknown'):
            raise ImportErrorSafe('Status declarado nao reconhecido.')
        key = (identity, section)
        if key in identities:
            raise ImportErrorSafe('Identidade nome completo e secao repetida. Nenhuma linha foi fundida.')
        identities.add(key)
        if record.get('coletado_em') not in (None, ''):
            raise ImportErrorSafe('Nova evidencia de coleta exige revisao do modelo inicial.')
        date_text, date_value = _date(record.get('ultima_replicacao'), zone)
        rows.append((order, name, identity, section, status,
                     _text(record.get('delta'), 240),
                     *(_number(record[key]) if key in record and record[key] is not None else None for key in COUNTERS),
                     date_text, date_value, _text(record.get('detalhes'), 8000)))
    errors = tuple((order, _text(value, 8000, required=True))
                   for order, value in enumerate(payload['erros_operacionais'], 1))
    source_hash = hashlib.sha256(raw).hexdigest()
    canonical = (SOURCE_ID, source_hash, source_timezone, publication_text, publication, totals, rows, errors)
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=True, separators=(',', ':'),
                                      default=lambda value: value.isoformat()).encode()).hexdigest()
    return ReplicationCatalog(digest, source_hash, source_timezone, publication_text,
                              publication, totals, tuple(rows), errors)


def _inspect(cursor):
    counts = {}
    for table in TABLES:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return {'contagens': counts, 'tabelas_replicacao_ad_vazias': not any(counts.values())}


def inspect_replication_catalog(connection):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        return _inspect(cursor)


def write_replication_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'validacao_destino'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga de replicacao em andamento.')
        for table in TABLES:
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        if not _inspect(cursor)['tabelas_replicacao_ad_vazias']:
            raise ImportErrorSafe('Replicacao AD ja carregada. Nao repetir a carga inicial.')
        progress.phase = 'insercao_replicacao_ad'
        source = (SOURCE_ID, catalog.source_sha256, catalog.digest, catalog.source_timezone,
                  catalog.publication_text, catalog.publication, dict(catalog.totals))
        cursor.execute('INSERT INTO operacional.fontes_replicacao_ad '
                       '(id,arquivo_origem_sha256,digest_carga,fuso_legado,publicacao_textual,'
                       'publicado_em_declarado,totais_declarados) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)',
                       (*source[:-1], json.dumps(source[-1])))
        for row in catalog.rows:
            cursor.execute('INSERT INTO operacional.observacoes_replicacao_ad (fonte_id,' + ROW_COLUMNS + ') '
                           'VALUES (' + ','.join(['%s'] * 14) + ')', (SOURCE_ID, *row))
        for row in catalog.errors:
            cursor.execute('INSERT INTO operacional.erros_operacionais_replicacao_ad '
                           '(fonte_id,ordem,mensagem_declarada) VALUES (%s,%s,%s)', (SOURCE_ID, *row))
        progress.phase = 'conferencia_final'
        cursor.execute('SELECT id,arquivo_origem_sha256,digest_carga,fuso_legado,publicacao_textual,'
                       'publicado_em_declarado,totais_declarados FROM operacional.fontes_replicacao_ad ORDER BY id')
        if cursor.fetchall() != [source]:
            raise ImportErrorSafe('Conferencia da fonte divergente. Transacao cancelada.')
        cursor.execute('SELECT ' + ROW_COLUMNS + ' FROM operacional.observacoes_replicacao_ad '
                       'WHERE fonte_id=%s ORDER BY ordem', (SOURCE_ID,))
        if tuple(cursor.fetchall()) != catalog.rows:
            raise ImportErrorSafe('Conferencia das observacoes divergente. Transacao cancelada.')
        cursor.execute('SELECT ordem,mensagem_declarada FROM operacional.erros_operacionais_replicacao_ad '
                       'WHERE fonte_id=%s ORDER BY ordem', (SOURCE_ID,))
        if tuple(cursor.fetchall()) != catalog.errors:
            raise ImportErrorSafe('Conferencia dos erros divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--source-timezone')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        if (args.apply or args.check_database) and args.source is None:
            raise ImportErrorSafe('Operacao SQL exige --source com copia congelada revisada.')
        catalog = build_replication_catalog((args.source or ROOT / 'data/replicacao.json').read_bytes(), args.source_timezone)
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao SQL somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato da simulacao revisada.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_replication_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_replicacao_ad_confirmada'
                else:
                    result['banco'] = inspect_replication_catalog(connection)
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
