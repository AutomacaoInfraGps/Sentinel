"""One-way, opt-in polling of the existing SLA workbook; receipts contain no PII."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import threading

from core.secret_store import _InterprocessFileLock
from scripts.database.audit_ap_sources import _read
from scripts.database.import_sla_contacts import SOURCE_ID, TABLES, BOOTSTRAP_LOCK, build_contact_catalog
from scripts.database.import_vpn_catalog import _aware_time
from services.operational_postgres import PROJECT_ROOT, SnapshotError, _identity, _safe_warning, connect_collector, shadow_enabled

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-contatos-sla-shadow.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/contatos_sla_postgres_publication.json'
LOCK_PATH = PROJECT_ROOT / 'instance/contatos-sla-shadow.lock'
POLL_SECONDS = 300
_worker = None
_worker_lock = threading.Lock()


def _json(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()


@dataclass(frozen=True, repr=False)
class ContactSnapshot:
    captured_at: datetime
    digest: str
    config_hash: str
    catalog: object = field(repr=False)

    def receipt(self):
        return {'version': 1, 'capturado_em': self.captured_at.isoformat(),
                'sha256_normalizado': self.digest, 'origem_config_sha256': self.config_hash,
                'sha256_planilha': self.catalog.workbook_sha256,
                'sha256_catalogo_regionais': self.catalog.regionals_sha256}

    def summary(self):
        original = self.catalog.summary()
        return {**self.receipt(), 'regionais_sla': len(self.catalog.assignments),
                'vinculos_preenchidos': len(self.catalog.contacts), 'por_papel': original['por_papel'],
                'planilha_modificada': False}


def prepare_contact_snapshot(catalog, source, captured_at):
    if not isinstance(captured_at, datetime) or captured_at.utcoffset() is None:
        raise SnapshotError('Leitura exige horario com fuso.')
    config_hash = hashlib.sha256(_json((SOURCE_ID, os.path.normcase(str(Path(source).resolve())), catalog.sheet))).hexdigest()
    canonical = (config_hash, catalog.assignments, catalog.contacts)
    return ContactSnapshot(captured_at, hashlib.sha256(_json(canonical)).hexdigest(), config_hash, catalog)


def read_current_snapshot(captured_at=None):
    settings = _read(PROJECT_ROOT / 'environment.json').get('email_contatos') or {}
    configured, sheet = settings.get('xlsx_path'), settings.get('sheet_name')
    if not isinstance(configured, str) or not configured.strip() or not isinstance(sheet, str) or not sheet.strip():
        raise SnapshotError('Planilha e aba exata precisam estar configuradas.')
    source = Path(configured).expanduser()
    if not source.is_absolute() or source.suffix.lower() != '.xlsx':
        raise SnapshotError('Fonte configurada exige XLSX absoluto.')
    regional_path = PROJECT_ROOT / 'estrutura_regionais.json'
    raw, regionals = source.read_bytes(), regional_path.read_bytes()
    catalog = build_contact_catalog(raw, regionals, sheet)
    if source.read_bytes() != raw or regional_path.read_bytes() != regionals:
        raise SnapshotError('Origem mudou durante a leitura. Banco preservado.')
    return prepare_contact_snapshot(catalog, source, captured_at or datetime.now(timezone.utc))


def verify_current(snapshot):
    current = read_current_snapshot(snapshot.captured_at)
    if current.receipt() != snapshot.receipt():
        raise SnapshotError('Fonte mudou apos a captura. Gere e confira uma publicacao nova.')


def save_contact_publication(snapshot, path=PUBLICATION_PATH):
    """Caller holds LOCK_PATH across capture, receipt replacement and optional SQL."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.contatos-sla-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json(snapshot.receipt()))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_contact_publication(path=PUBLICATION_PATH):
    receipt = _read(Path(path))
    if not isinstance(receipt, dict) or receipt.get('version') != 1:
        raise SnapshotError('Recibo invalido.')
    captured = _aware_time(receipt.get('capturado_em'))
    if captured > datetime.now(timezone.utc):
        raise SnapshotError('Recibo com horario futuro.')
    snapshot = read_current_snapshot(captured)
    if receipt != snapshot.receipt():
        raise SnapshotError('Recibo nao corresponde as fontes atuais. Capture novamente.')
    return snapshot


MARKER_SQL = ('SELECT lido_em,conteudo_sha256,origem_config_sha256 '
              'FROM operacional.sincronizacoes_contatos_sla WHERE fonte_id=%s')


def inspect_contact_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        cursor.execute(MARKER_SQL, (SOURCE_ID,))
        marker = cursor.fetchone()
        cursor.execute('SELECT count(*) FROM operacional.regionais_contatos_sla WHERE fonte_id=%s AND presente_na_fonte', (SOURCE_ID,))
        regions = cursor.fetchone()[0]
        cursor.execute('SELECT count(*) FROM operacional.contatos_regionais_sla WHERE fonte_id=%s AND presente_na_fonte', (SOURCE_ID,))
        contacts = cursor.fetchone()[0]
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao',
            'banco_regionais_presentes': regions, 'banco_vinculos_presentes': contacts,
            'ultima_leitura_sincronizada': marker[0].isoformat() if marker else None,
            'conteudo_ja_sincronizado': bool(marker and marker[1:] == (snapshot.digest, snapshot.config_hash)),
            'publicacao_mais_antiga': bool(marker and marker[0] > snapshot.captured_at)}


def write_contact_snapshot(connection, snapshot, *, validate_source=verify_current):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='2s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise SnapshotError('Outra carga SLA em andamento.')
        cursor.execute('LOCK TABLE operacional.regionais IN ACCESS SHARE MODE')
        for table in (*TABLES, 'sincronizacoes_contatos_sla'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        cursor.execute('SELECT aba FROM operacional.fontes_contatos_sla WHERE id=%s FOR UPDATE', (SOURCE_ID,))
        if cursor.fetchone() != (snapshot.catalog.sheet,):
            raise SnapshotError('Fonte inicial ausente ou aba divergente. Revise antes de sincronizar.')
        cursor.execute(MARKER_SQL, (SOURCE_ID,))
        marker = cursor.fetchone()
        if marker and marker[2] != snapshot.config_hash:
            raise SnapshotError('Caminho ou aba da fonte mudou. Revisao manual exigida.')
        if marker and marker[0] > snapshot.captured_at:
            return 'publicacao_mais_antiga_ignorada'
        if marker and marker[0] == snapshot.captured_at and marker[1] != snapshot.digest:
            raise SnapshotError('Conteudo conflitante no mesmo horario de leitura.')
        validate_source(snapshot)
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(snapshot.catalog.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(snapshot.catalog.regional_codes):
            raise SnapshotError('Catalogo regional divergente do banco.')
        changed = not marker or marker[1] != snapshot.digest
        if changed:
            for table in ('regionais_contatos_sla', 'contatos_regionais_sla'):
                cursor.execute('UPDATE operacional.' + table + ' SET presente_na_fonte=false '
                               'WHERE fonte_id=%s AND presente_na_fonte', (SOURCE_ID,))
            for row in snapshot.catalog.assignments:
                cursor.execute('INSERT INTO operacional.regionais_contatos_sla '
                               '(fonte_id,codigo_regional,rotulo_regional_origem,rotulo_fortianalyzer_origem,regra_vinculo,linha_planilha_origem) '
                               'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(fonte_id,codigo_regional) DO UPDATE SET '
                               'rotulo_regional_origem=EXCLUDED.rotulo_regional_origem,rotulo_fortianalyzer_origem=EXCLUDED.rotulo_fortianalyzer_origem,'
                               'regra_vinculo=EXCLUDED.regra_vinculo,linha_planilha_origem=EXCLUDED.linha_planilha_origem,presente_na_fonte=true',
                               (SOURCE_ID, *row))
            for row in snapshot.catalog.contacts:
                cursor.execute('INSERT INTO operacional.contatos_regionais_sla '
                               '(fonte_id,codigo_regional,papel,nome_origem,email_origem) VALUES (%s,%s,%s,%s,%s) '
                               'ON CONFLICT(fonte_id,codigo_regional,papel) DO UPDATE SET nome_origem=EXCLUDED.nome_origem,'
                               'email_origem=EXCLUDED.email_origem,presente_na_fonte=true', (SOURCE_ID, *row))
        cursor.execute('SELECT count(*) FROM operacional.regionais_contatos_sla WHERE fonte_id=%s AND presente_na_fonte', (SOURCE_ID,))
        if cursor.fetchone() != (len(snapshot.catalog.assignments),):
            raise SnapshotError('Contagem regional divergente. Transacao cancelada.')
        cursor.execute('SELECT codigo_regional,papel,nome_origem,email_origem FROM operacional.contatos_regionais_sla '
                       'WHERE fonte_id=%s AND presente_na_fonte ORDER BY codigo_regional,papel', (SOURCE_ID,))
        if tuple(cursor.fetchall()) != snapshot.catalog.contacts:
            raise SnapshotError('Contatos divergentes apos sincronizacao. Transacao cancelada.')
        validate_source(snapshot)
        cursor.execute('UPDATE operacional.fontes_contatos_sla SET arquivo_origem_sha256=%s,catalogo_regionais_sha256=%s WHERE id=%s',
                       (snapshot.catalog.workbook_sha256, snapshot.catalog.regionals_sha256, SOURCE_ID))
        cursor.execute('INSERT INTO operacional.sincronizacoes_contatos_sla '
                       '(fonte_id,lido_em,conteudo_sha256,origem_config_sha256) VALUES (%s,%s,%s,%s) '
                       'ON CONFLICT(fonte_id) DO UPDATE SET lido_em=EXCLUDED.lido_em,conteudo_sha256=EXCLUDED.conteudo_sha256,'
                       'origem_config_sha256=EXCLUDED.origem_config_sha256,sincronizado_em=CURRENT_TIMESTAMP',
                       (SOURCE_ID, snapshot.captured_at, snapshot.digest, snapshot.config_hash))
    return 'sincronizado' if changed else 'sem_alteracoes'


def poll_contact_catalog(logger):
    if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL' or not shadow_enabled(CONFIG_PATH):
        return False
    try:
        with _InterprocessFileLock(LOCK_PATH, timeout=0.25):
            snapshot = read_current_snapshot()
            save_contact_publication(snapshot, PUBLICATION_PATH)
            if not shadow_enabled(CONFIG_PATH):
                return False
            with connect_collector() as connection:
                write_contact_snapshot(connection, snapshot)
        return True
    except Exception as exc:
        _safe_warning(logger, 'falha_sincronizacao_contatos_sla', exc)
        return False


def start_contact_sync_worker(logger=None):
    global _worker
    logger = logger or logging.getLogger(__name__)
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return _worker
        def run():
            while True:
                poll_contact_catalog(logger)
                threading.Event().wait(POLL_SECONDS)
        _worker = threading.Thread(target=run, name='sentinel-contatos-sla-shadow', daemon=True)
        _worker.start()
        return _worker
