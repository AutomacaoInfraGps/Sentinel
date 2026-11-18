"""Opt-in declared replication cache polling; never runs repadmin or queries AD."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading

from core.secret_store import _InterprocessFileLock
from scripts.database.audit_ap_sources import _read
from scripts.database.import_replication_catalog import (
    SOURCE_ID, TABLES, BOOTSTRAP_LOCK, ROW_COLUMNS, build_replication_catalog,
)
from scripts.database.import_vpn_catalog import _aware_time
from services.operational_postgres import (
    PROJECT_ROOT, SnapshotError, _identity, _safe_warning, connect_collector, shadow_enabled,
)

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-replication-shadow.json'
SOURCE_PATH = PROJECT_ROOT / 'data/replicacao.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/replication_postgres_publication.json'
LOCK_PATH = PROJECT_ROOT / 'instance/replication-shadow.lock'
POLL_SECONDS = 300
_worker = None
_worker_lock = threading.Lock()


def _json(value):
    return json.dumps(value, default=lambda item: item.isoformat(), ensure_ascii=True, separators=(',', ':')).encode()


@dataclass(frozen=True, repr=False)
class ReplicationSnapshot:
    captured_at: datetime
    digest: str
    config_hash: str
    catalog: object

    def receipt(self):
        return {'version': 1, 'capturado_em': self.captured_at.isoformat(),
                'sha256_normalizado': self.digest, 'origem_config_sha256': self.config_hash,
                'fuso_origem': self.catalog.source_timezone, 'sha256_arquivo': self.catalog.source_sha256}

    def summary(self):
        summary = self.catalog.summary()
        summary.pop('digest_carga')
        summary.pop('sincronizacao_automatica_replicacao_ad')
        return {**summary, **self.receipt()}


def prepare_replication_snapshot(catalog, source_path, captured_at):
    if not isinstance(captured_at, datetime) or captured_at.utcoffset() is None:
        raise SnapshotError('Captura exige horario com fuso.')
    if catalog.publication > captured_at or any(row[11] and row[11] > captured_at for row in catalog.rows):
        raise SnapshotError('Fonte com horario declarado futuro.')
    config = (SOURCE_ID, os.path.normcase(str(Path(source_path).resolve())), catalog.source_timezone)
    config_hash = hashlib.sha256(_json(config)).hexdigest()
    digest = hashlib.sha256(_json((config_hash, catalog.digest))).hexdigest()
    return ReplicationSnapshot(captured_at, digest, config_hash, catalog)


def read_current_snapshot(source_timezone=None, captured_at=None, *, expected_sha256=None):
    if source_timezone is None:
        settings = _read(CONFIG_PATH)
        source_timezone = settings.get('source_timezone') if isinstance(settings, dict) else None
    if not isinstance(source_timezone, str) or not source_timezone.strip():
        raise SnapshotError('Informe o fuso legado explicitamente antes de capturar.')
    raw = SOURCE_PATH.read_bytes()
    catalog = build_replication_catalog(raw, source_timezone)
    if SOURCE_PATH.read_bytes() != raw:
        raise SnapshotError('Fonte mudou durante a leitura. Banco preservado.')
    if expected_sha256 is not None and catalog.source_sha256 != expected_sha256:
        raise SnapshotError('Fonte mudou desde a captura do recibo. Capture e confira novamente. Banco preservado.')
    return prepare_replication_snapshot(catalog, SOURCE_PATH, captured_at or datetime.now(timezone.utc))


def verify_current(snapshot):
    current = read_current_snapshot(snapshot.catalog.source_timezone, snapshot.captured_at,
                                    expected_sha256=snapshot.catalog.source_sha256)
    if current.receipt() != snapshot.receipt():
        raise SnapshotError('Fonte ou configuracao mudou. Capture e confira novamente.')


def save_replication_publication(snapshot, path=PUBLICATION_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.replication-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json(snapshot.receipt()))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_replication_publication(path=PUBLICATION_PATH):
    receipt = _read(Path(path))
    hashes = {'sha256_normalizado', 'origem_config_sha256', 'sha256_arquivo'}
    if (not isinstance(receipt, dict) or set(receipt) != hashes | {'version', 'capturado_em', 'fuso_origem'}
            or type(receipt.get('version')) is not int or receipt['version'] != 1):
        raise SnapshotError('Recibo invalido.')
    if any(not isinstance(receipt[key], str) or not re.fullmatch(r'[0-9a-f]{64}', receipt[key]) for key in hashes):
        raise SnapshotError('Hash de recibo invalido.')
    captured = _aware_time(receipt['capturado_em'])
    if captured > datetime.now(timezone.utc):
        raise SnapshotError('Recibo com horario futuro.')
    snapshot = read_current_snapshot(receipt['fuso_origem'], captured, expected_sha256=receipt['sha256_arquivo'])
    if snapshot.receipt() != receipt:
        raise SnapshotError('Fonte ou configuracao mudou. Capture e confira novamente.')
    return snapshot


MARKER_SQL = ('SELECT lido_em,conteudo_sha256,origem_config_sha256 '
              'FROM operacional.sincronizacoes_replicacao_ad WHERE fonte_id=%s')
SOURCE_SQL = ('SELECT fuso_legado,publicado_em_declarado,arquivo_origem_sha256 '
              'FROM operacional.fontes_replicacao_ad WHERE id=%s')


def inspect_replication_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        cursor.execute(MARKER_SQL, (SOURCE_ID,))
        marker = cursor.fetchone()
        cursor.execute(SOURCE_SQL, (SOURCE_ID,))
        source = cursor.fetchone()
        counts = {}
        for table in TABLES[1:]:
            cursor.execute('SELECT count(*) FROM operacional.' + table + ' WHERE fonte_id=%s AND presente_na_fonte', (SOURCE_ID,))
            counts[table] = cursor.fetchone()[0]
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao', 'banco_presentes': counts,
            'fonte_inicial_compativel': bool(source and source[0] == snapshot.catalog.source_timezone),
            'ultima_leitura_sincronizada': marker[0].isoformat() if marker else None,
            'conteudo_ja_sincronizado': bool(marker and marker[1:] == (snapshot.digest, snapshot.config_hash)),
            'publicacao_mais_antiga': bool(source and source[1] > snapshot.catalog.publication),
            'captura_mais_antiga': bool(marker and marker[0] > snapshot.captured_at)}


def _write_rows(cursor, catalog):
    cursor.execute('UPDATE operacional.observacoes_replicacao_ad SET presente_na_fonte=false WHERE fonte_id=%s', (SOURCE_ID,))
    updates = ','.join(column + '=EXCLUDED.' + column for column in ROW_COLUMNS.split(',')
                       if column not in ('nome_identidade', 'secao'))
    for row in catalog.rows:
        cursor.execute('INSERT INTO operacional.observacoes_replicacao_ad (fonte_id,' + ROW_COLUMNS + ') '
                       'VALUES (' + ','.join(['%s'] * 14) + ') ON CONFLICT(fonte_id,nome_identidade,secao) '
                       'DO UPDATE SET ' + updates + ',presente_na_fonte=true', (SOURCE_ID, *row))
    cursor.execute('UPDATE operacional.erros_operacionais_replicacao_ad SET presente_na_fonte=false WHERE fonte_id=%s', (SOURCE_ID,))
    for row in catalog.errors:
        cursor.execute('INSERT INTO operacional.erros_operacionais_replicacao_ad '
                       '(fonte_id,ordem,mensagem_declarada) VALUES (%s,%s,%s) '
                       'ON CONFLICT(fonte_id,ordem) DO UPDATE SET '
                       'mensagem_declarada=EXCLUDED.mensagem_declarada,presente_na_fonte=true', (SOURCE_ID, *row))


def _verify_rows(cursor, catalog):
    cursor.execute('SELECT ' + ROW_COLUMNS + ' FROM operacional.observacoes_replicacao_ad '
                   'WHERE fonte_id=%s AND presente_na_fonte ORDER BY ordem', (SOURCE_ID,))
    if tuple(cursor.fetchall()) != catalog.rows:
        raise SnapshotError('Observacoes divergentes. Transacao cancelada.')
    cursor.execute('SELECT ordem,mensagem_declarada FROM operacional.erros_operacionais_replicacao_ad '
                   'WHERE fonte_id=%s AND presente_na_fonte ORDER BY ordem', (SOURCE_ID,))
    if tuple(cursor.fetchall()) != catalog.errors:
        raise SnapshotError('Erros operacionais divergentes. Transacao cancelada.')


def write_replication_snapshot(connection, snapshot, *, validate_source=verify_current):
    catalog = snapshot.catalog
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='2s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise SnapshotError('Outra carga de replicacao em andamento.')
        for table in (*TABLES, 'sincronizacoes_replicacao_ad'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        cursor.execute(SOURCE_SQL + ' FOR UPDATE', (SOURCE_ID,))
        source = cursor.fetchone()
        if not source or source[0] != catalog.source_timezone:
            raise SnapshotError('Fonte inicial ausente ou fuso divergente.')
        if source[1] > catalog.publication:
            return 'publicacao_mais_antiga_ignorada'
        if source[1] == catalog.publication and source[2] != catalog.source_sha256:
            raise SnapshotError('Conteudo conflitante no mesmo horario de publicacao.')
        cursor.execute(MARKER_SQL, (SOURCE_ID,))
        marker = cursor.fetchone()
        if marker and marker[2] != snapshot.config_hash:
            raise SnapshotError('Origem ou fuso mudou. Revisao manual exigida.')
        if marker and marker[0] > snapshot.captured_at:
            return 'captura_mais_antiga_ignorada'
        if marker and marker[0] == snapshot.captured_at and marker[1] != snapshot.digest:
            raise SnapshotError('Conteudo conflitante no mesmo horario de captura.')
        validate_source(snapshot)
        changed = not marker or marker[1] != snapshot.digest
        if changed:
            _write_rows(cursor, catalog)
        _verify_rows(cursor, catalog)
        validate_source(snapshot)
        cursor.execute('UPDATE operacional.fontes_replicacao_ad SET arquivo_origem_sha256=%s,digest_carga=%s,'
                       'publicacao_textual=%s,publicado_em_declarado=%s,totais_declarados=%s::jsonb WHERE id=%s',
                       (catalog.source_sha256, catalog.digest, catalog.publication_text,
                        catalog.publication, json.dumps(dict(catalog.totals)), SOURCE_ID))
        cursor.execute('INSERT INTO operacional.sincronizacoes_replicacao_ad '
                       '(fonte_id,lido_em,conteudo_sha256,origem_config_sha256) VALUES (%s,%s,%s,%s) '
                       'ON CONFLICT(fonte_id) DO UPDATE SET lido_em=EXCLUDED.lido_em,conteudo_sha256=EXCLUDED.conteudo_sha256,'
                       'origem_config_sha256=EXCLUDED.origem_config_sha256,sincronizado_em=CURRENT_TIMESTAMP',
                       (SOURCE_ID, snapshot.captured_at, snapshot.digest, snapshot.config_hash))
    return 'sincronizado' if changed else 'sem_alteracoes'


def poll_replication_catalog(logger):
    if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL' or not shadow_enabled(CONFIG_PATH):
        return False
    try:
        with _InterprocessFileLock(LOCK_PATH, timeout=0.25):
            snapshot = read_current_snapshot()
            save_replication_publication(snapshot, PUBLICATION_PATH)
            if not shadow_enabled(CONFIG_PATH):
                return False
            with connect_collector() as connection:
                write_replication_snapshot(connection, snapshot)
        return True
    except Exception as exc:
        _safe_warning(logger, 'falha_sincronizacao_replicacao_ad', exc)
        return False


def start_replication_sync_worker(logger=None):
    global _worker
    logger = logger or logging.getLogger(__name__)
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return _worker
        def run():
            while True:
                poll_replication_catalog(logger)
                threading.Event().wait(POLL_SECONDS)
        _worker = threading.Thread(target=run, name='sentinel-replication-shadow', daemon=True)
        _worker.start()
        return _worker
