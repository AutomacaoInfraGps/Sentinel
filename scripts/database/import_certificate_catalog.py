"""Bootstrap legacy certificate metadata with unconfirmed origin and no collection evidence."""

import argparse
from collections import Counter
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

from scripts.database.audit_certificate_sources import ALIASES, _thumbprint, _expiration
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error, _unique_keys
from scripts.database.import_server_catalog import _identity, _text

SOURCE_ID = 'sentinel_certificados_relatorio_legado'
TABLES = ('fontes_certificados_legados', 'certificados_legados')
BOOTSTRAP_LOCK = (0x43455201, 21)
SOURCE_COLUMNS = ('id,arquivo_origem_sha256,digest_carga,origem_confirmada,'
                  'host_origem,repositorio_origem,codigo_regional,coletado_em')
ROW_COLUMNS = 'ordem,thumbprint_textual,thumbprint_normalizado,assunto,emissor,vencimento_textual,vencimento_declarado'


@dataclass(frozen=True, repr=False)
class CertificateCatalog:
    digest: str
    source_sha256: str
    rows: tuple

    def summary(self, now=None):
        now = now or datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ImportErrorSafe('Conferencia temporal exige horario com fuso.')
        return {'digest_carga': self.digest, 'sha256_arquivo': self.source_sha256,
                'fonte': SOURCE_ID, 'certificados': len(self.rows),
                'thumbprints_distintos': len({row[2] for row in self.rows}),
                'assuntos_repetidos_sem_fusao': sum(count > 1 for count in Counter(row[3].casefold() for row in self.rows).values()),
                'validade_avaliada_em_utc': now.astimezone(timezone.utc).isoformat(),
                'validade_apenas_temporal': dict(Counter(_expiration(row[5], now)[1] for row in self.rows)),
                'origem_confirmada': False, 'host_origem': None, 'repositorio_origem': None,
                'codigo_regional': None, 'coletado_em': None,
                'status_de_validade_persistido': False, 'confianca_criptografica_validada': False,
                'chaves_ou_credenciais_importadas': False, 'coletor_executado': False,
                'arquivo_origem_modificado': False, 'sincronizacao_automatica_certificados': False}


def _value(record, field):
    lower, upper = ALIASES[field]
    for key in (lower, upper):
        if key in record and record[key] is not None and not isinstance(record[key], str):
            raise ImportErrorSafe('Metadado de certificado nao textual. Carga bloqueada.')
    if record.get(lower) and record.get(upper) and record[lower] != record[upper]:
        raise ImportErrorSafe('Aliases conflitantes. Nenhum metadado foi escolhido por aproximacao.')
    return _text(record.get(lower) or record.get(upper), 4000 if field in ('subject', 'issuer') else 200 if field == 'thumbprint' else 80,
                 required=True)


def _expiration_time(text):
    try:
        if 'T' not in text:
            raise ValueError()
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ImportErrorSafe('Vencimento exige data ISO completa com fuso. Nenhum fuso sera inferido.') from None


def build_certificate_catalog(raw):
    try:
        payload = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_keys)
    except (UnicodeError, ValueError):
        raise ImportErrorSafe('JSON invalido ou com chaves duplicadas.') from None
    records = [payload] if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not records:
        raise ImportErrorSafe('Relatorio legado vazio ou invalido. Carga bloqueada.')
    allowed = {key for pair in ALIASES.values() for key in pair}
    rows, identities = [], set()
    for order, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ImportErrorSafe('Registro de certificado invalido.')
        if set(record) - allowed:
            raise ImportErrorSafe('Campos fora do escopo legado exigem revisao; nenhum dado extra sera importado.')
        fingerprint_text = _value(record, 'thumbprint')
        fingerprint = _thumbprint(fingerprint_text)
        if fingerprint is None:
            raise ImportErrorSafe('Formato de thumbprint nao reconhecido.')
        if fingerprint in identities:
            raise ImportErrorSafe('Thumbprint repetido na fonte. Nenhum certificado foi fundido.')
        identities.add(fingerprint)
        subject, issuer, expires = (_value(record, key) for key in ('subject', 'issuer', 'notAfter'))
        rows.append((order, fingerprint_text, fingerprint, subject, issuer, expires, _expiration_time(expires)))
    source_hash = hashlib.sha256(raw).hexdigest()
    canonical = (SOURCE_ID, source_hash, False, None, None, None, None, rows)
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=True, separators=(',', ':'),
                                      default=lambda value: value.isoformat()).encode()).hexdigest()
    return CertificateCatalog(digest, source_hash, tuple(rows))


def _inspect(cursor):
    counts = {}
    for table in TABLES:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return {'contagens': counts, 'tabelas_certificados_legados_vazias': not any(counts.values())}


def inspect_certificate_catalog(connection):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        return _inspect(cursor)


def write_certificate_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'validacao_destino'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga de certificados em andamento.')
        for table in TABLES:
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        if not _inspect(cursor)['tabelas_certificados_legados_vazias']:
            raise ImportErrorSafe('Certificados legados ja carregados. Nao repetir a carga inicial.')
        progress.phase = 'insercao_certificados_legados'
        source = (SOURCE_ID, catalog.source_sha256, catalog.digest, False, None, None, None, None)
        cursor.execute('INSERT INTO operacional.fontes_certificados_legados (' + SOURCE_COLUMNS + ') '
                       'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)', source)
        for row in catalog.rows:
            cursor.execute('INSERT INTO operacional.certificados_legados (fonte_id,' + ROW_COLUMNS + ') '
                           'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)', (SOURCE_ID, *row))
        progress.phase = 'conferencia_final'
        cursor.execute('SELECT ' + SOURCE_COLUMNS + ' FROM operacional.fontes_certificados_legados ORDER BY id')
        if cursor.fetchall() != [source]:
            raise ImportErrorSafe('Conferencia da origem desconhecida divergente. Transacao cancelada.')
        cursor.execute('SELECT ' + ROW_COLUMNS + ' FROM operacional.certificados_legados WHERE fonte_id=%s ORDER BY ordem', (SOURCE_ID,))
        if tuple(cursor.fetchall()) != catalog.rows:
            raise ImportErrorSafe('Conferencia dos certificados divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        if (args.apply or args.check_database) and args.source is None:
            raise ImportErrorSafe('Operacao SQL exige --source com copia congelada revisada.')
        source = args.source or ROOT / 'certificate_disk_report_acrab.json'
        raw = source.read_bytes()
        catalog = build_certificate_catalog(raw)
        if source.read_bytes() != raw:
            raise ImportErrorSafe('Fonte mudou durante a leitura. Nenhuma gravacao foi iniciada.')
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
                    write_certificate_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_certificados_legados_confirmada'
                else:
                    result['banco'] = inspect_certificate_catalog(connection)
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
