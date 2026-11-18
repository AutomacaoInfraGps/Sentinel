"""Opt-in, one-way polling of admin cache and baseline; no approvals or device calls."""

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
from scripts.database.import_admin_catalog import SOURCE_ID, TABLES, BOOTSTRAP_LOCK, build_admin_catalog
from scripts.database.import_vpn_catalog import _aware_time
from services.operational_postgres import (
    PROJECT_ROOT, SnapshotError, _identity, _safe_warning, connect_collector, shadow_enabled,
)

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-admins-shadow.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/admins_postgres_publication.json'
LOCK_PATH = PROJECT_ROOT / 'instance/admins-shadow.lock'
POLL_SECONDS = 300
_worker = None
_worker_lock = threading.Lock()


def _json(value):
    return json.dumps(value, default=lambda item: item.isoformat(), ensure_ascii=True, separators=(',', ':')).encode()


@dataclass(frozen=True, repr=False)
class AdminSnapshot:
    captured_at: datetime
    digest: str
    config_hash: str
    catalog: object

    def receipt(self):
        return {'version': 1, 'capturado_em': self.captured_at.isoformat(),
                'sha256_normalizado': self.digest, 'origem_config_sha256': self.config_hash,
                'fuso_origem': self.catalog.source_timezone,
                **dict(zip(('sha256_cache_admins', 'sha256_baseline', 'sha256_cache_firewalls',
                            'sha256_catalogo_regionais'), self.catalog.hashes))}

    def summary(self):
        summary = self.catalog.summary()
        for key in ('digest_carga', 'sincronizacao_automatica_admins'):
            summary.pop(key)
        return {**summary, **self.receipt()}


def prepare_admin_snapshot(catalog, baseline_path, captured_at):
    if not isinstance(captured_at, datetime) or captured_at.utcoffset() is None:
        raise SnapshotError('Captura exige horario com fuso.')
    if catalog.published_at > captured_at:
        raise SnapshotError('Cache com publicacao futura.')
    config = (SOURCE_ID, os.path.normcase(str(Path(baseline_path).resolve())), catalog.source_timezone)
    config_hash = hashlib.sha256(_json(config)).hexdigest()
    # Regional/firewall files contain unrelated live state. Their bindings are in devices.
    canonical = (config_hash, catalog.hashes[:2], catalog.published_at, catalog.devices,
                 catalog.observed, catalog.approved, catalog.differences)
    return AdminSnapshot(captured_at, hashlib.sha256(_json(canonical)).hexdigest(), config_hash, catalog)


def read_current_snapshot(source_timezone=None, captured_at=None):
    if source_timezone is None:
        settings = _read(CONFIG_PATH)
        source_timezone = settings.get('source_timezone') if isinstance(settings, dict) else None
    if not isinstance(source_timezone, str) or not source_timezone.strip():
        raise SnapshotError('Informe o fuso legado explicitamente antes de capturar.')
    environment = _read(PROJECT_ROOT / 'environment.json')
    configured = (environment.get('fortianalyzer') or {}).get('admin_baseline_file', 'admin_baseline.json')
    if not isinstance(configured, str) or not configured.strip():
        raise SnapshotError('Caminho da baseline invalido.')
    baseline = Path(configured)
    if not baseline.is_absolute():
        baseline = PROJECT_ROOT / baseline
    paths = (PROJECT_ROOT / 'output/dashboard_admins_cache.json', baseline,
             PROJECT_ROOT / 'output/dashboard_firewalls_cache.json', PROJECT_ROOT / 'estrutura_regionais.json')
    raw = tuple(path.read_bytes() for path in paths)
    catalog = build_admin_catalog(*raw, source_timezone)
    if tuple(path.read_bytes() for path in paths) != raw:
        raise SnapshotError('Fonte mudou durante a leitura. Banco preservado.')
    return prepare_admin_snapshot(catalog, baseline, captured_at or datetime.now(timezone.utc))


def _same_revision(first, second):
    return all(first.get(key) == second.get(key) for key in (
        'version', 'capturado_em', 'sha256_normalizado', 'origem_config_sha256',
        'fuso_origem', 'sha256_cache_admins', 'sha256_baseline'))


def verify_current(snapshot):
    current = read_current_snapshot(snapshot.catalog.source_timezone, snapshot.captured_at)
    if not _same_revision(snapshot.receipt(), current.receipt()):
        raise SnapshotError('Cache, baseline, origem ou vinculos mudaram. Capture e confira novamente.')


def save_admin_publication(snapshot, path=PUBLICATION_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.admins-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_json(snapshot.receipt()))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_admin_publication(path=PUBLICATION_PATH):
    receipt = _read(Path(path))
    hashes = {'sha256_normalizado', 'origem_config_sha256', 'sha256_cache_admins',
              'sha256_baseline', 'sha256_cache_firewalls', 'sha256_catalogo_regionais'}
    fields = hashes | {'version', 'capturado_em', 'fuso_origem'}
    if (not isinstance(receipt, dict) or set(receipt) != fields or
            type(receipt.get('version')) is not int or receipt['version'] != 1):
        raise SnapshotError('Recibo invalido.')
    if any(not isinstance(receipt[key], str) or not re.fullmatch(r'[0-9a-f]{64}', receipt[key]) for key in hashes):
        raise SnapshotError('Hash de recibo invalido.')
    captured = _aware_time(receipt['capturado_em'])
    if captured > datetime.now(timezone.utc):
        raise SnapshotError('Recibo com horario futuro.')
    snapshot = read_current_snapshot(receipt['fuso_origem'], captured)
    if not _same_revision(snapshot.receipt(), receipt):
        raise SnapshotError('Cache, baseline, origem ou vinculos mudaram. Capture e confira novamente.')
    return snapshot


MARKER_SQL = ('SELECT lido_em,conteudo_sha256,origem_config_sha256 '
              'FROM operacional.sincronizacoes_monitor_admins WHERE fonte_id=%s')


def inspect_admin_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        cursor.execute(MARKER_SQL, (SOURCE_ID,))
        marker = cursor.fetchone()
        counts = {}
        for table in TABLES[1:]:
            cursor.execute('SELECT count(*) FROM operacional.' + table + ' WHERE fonte_id=%s AND presente_na_fonte', (SOURCE_ID,))
            counts[table] = cursor.fetchone()[0]
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao', 'banco_presentes': counts,
            'ultima_leitura_sincronizada': marker[0].isoformat() if marker else None,
            'conteudo_ja_sincronizado': bool(marker and marker[1:] == (snapshot.digest, snapshot.config_hash)),
            'publicacao_mais_antiga': bool(marker and marker[0] > snapshot.captured_at)}


def _write_devices(cursor, snapshot):
    catalog = snapshot.catalog
    cursor.execute('SELECT chave_dispositivo,ultima_coleta_valida FROM operacional.dispositivos_monitor_admins '
                   'WHERE fonte_id=%s', (SOURCE_ID,))
    previous = dict(cursor.fetchall())
    for row in catalog.devices:
        if row[5] and previous.get(row[0]) and (row[-1] is None or row[-1] < previous[row[0]]):
            raise SnapshotError('Coleta de dispositivo regrediu. Banco preservado.')
    # Absence from a partial cache is not evidence that a device/account was removed.
    cursor.execute('UPDATE operacional.dispositivos_monitor_admins SET presente_na_fonte=false WHERE fonte_id=%s', (SOURCE_ID,))
    for row in catalog.devices:
        cursor.execute('INSERT INTO operacional.dispositivos_monitor_admins AS existing_device '
                       '(fonte_id,chave_dispositivo,nome,tipo,codigo_regional,vinculo_regional,presente_no_cache,'
                       'presente_na_baseline,consulta_valida,consulta_indisponivel,monitoramento_limitado,offline,'
                       'sem_permissao,ultima_coleta_valida) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                       'ON CONFLICT(fonte_id,chave_dispositivo) DO UPDATE SET nome=EXCLUDED.nome,tipo=EXCLUDED.tipo,'
                       'codigo_regional=EXCLUDED.codigo_regional,vinculo_regional=EXCLUDED.vinculo_regional,'
                       'presente_no_cache=EXCLUDED.presente_no_cache,presente_na_baseline=EXCLUDED.presente_na_baseline,'
                       'consulta_valida=EXCLUDED.consulta_valida,consulta_indisponivel=EXCLUDED.consulta_indisponivel,'
                       'monitoramento_limitado=EXCLUDED.monitoramento_limitado,offline=EXCLUDED.offline,'
                       'sem_permissao=EXCLUDED.sem_permissao,ultima_coleta_valida=COALESCE(EXCLUDED.ultima_coleta_valida,'
                       'existing_device.ultima_coleta_valida),presente_na_fonte=true', (SOURCE_ID, *row))
    cursor.execute('UPDATE operacional.contas_admins_observadas SET evidencia=%s '
                   'WHERE fonte_id=%s AND presente_na_fonte', ('cache_sem_confirmacao_atual', SOURCE_ID))
    for row in catalog.devices:
        if row[5] and row[7] is True and row[-1] is not None:
            cursor.execute('UPDATE operacional.contas_admins_observadas SET presente_na_fonte=false '
                           'WHERE fonte_id=%s AND chave_dispositivo=%s', (SOURCE_ID, row[0]))
    for row in catalog.observed:
        cursor.execute('INSERT INTO operacional.contas_admins_observadas (fonte_id,chave_dispositivo,usuario,evidencia) '
                       'VALUES (%s,%s,%s,%s) ON CONFLICT(fonte_id,chave_dispositivo,usuario) DO UPDATE SET '
                       'evidencia=EXCLUDED.evidencia,presente_na_fonte=true', (SOURCE_ID, *row))


def _write_baseline_and_differences(cursor, catalog):
    for table in ('baseline_admins_aprovada', 'divergencias_monitor_admins'):
        cursor.execute('UPDATE operacional.' + table + ' SET presente_na_fonte=false WHERE fonte_id=%s', (SOURCE_ID,))
    for row in catalog.approved:
        cursor.execute('INSERT INTO operacional.baseline_admins_aprovada (fonte_id,chave_dispositivo,usuario) VALUES (%s,%s,%s) '
                       'ON CONFLICT(fonte_id,chave_dispositivo,usuario) DO UPDATE SET presente_na_fonte=true', (SOURCE_ID, *row))
    for row in catalog.differences:
        cursor.execute('INSERT INTO operacional.divergencias_monitor_admins (fonte_id,chave_dispositivo,usuario,categoria) '
                       'VALUES (%s,%s,%s,%s) ON CONFLICT(fonte_id,chave_dispositivo,usuario,categoria) '
                       'DO UPDATE SET presente_na_fonte=true', (SOURCE_ID, *row))


def _verify_rows(cursor, catalog):
    for table, columns, expected in (
        ('dispositivos_monitor_admins', 'chave_dispositivo', tuple((row[0],) for row in catalog.devices)),
        ('baseline_admins_aprovada', 'chave_dispositivo,usuario', catalog.approved),
        ('divergencias_monitor_admins', 'chave_dispositivo,usuario,categoria', catalog.differences)):
        cursor.execute('SELECT ' + columns + ' FROM operacional.' + table +
                       ' WHERE fonte_id=%s AND presente_na_fonte ORDER BY ' + columns, (SOURCE_ID,))
        if tuple(cursor.fetchall()) != expected:
            raise SnapshotError('Conferencia de admins divergente. Transacao cancelada.')
    cursor.execute('SELECT chave_dispositivo,usuario,evidencia FROM operacional.contas_admins_observadas '
                   'WHERE fonte_id=%s AND presente_na_fonte ORDER BY chave_dispositivo,usuario', (SOURCE_ID,))
    actual = tuple(cursor.fetchall())
    if not set(catalog.observed).issubset(set(actual)):
        raise SnapshotError('Contas observadas divergentes. Transacao cancelada.')
    complete = {row[0] for row in catalog.devices if row[5] and row[7] is True and row[-1] is not None}
    if tuple(row for row in actual if row[0] in complete) != tuple(row for row in catalog.observed if row[0] in complete):
        raise SnapshotError('Lista de consulta valida divergente. Transacao cancelada.')


def write_admin_snapshot(connection, snapshot, *, validate_source=verify_current):
    catalog = snapshot.catalog
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='2s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise SnapshotError('Outra carga de admins em andamento.')
        cursor.execute('LOCK TABLE operacional.regionais IN ACCESS SHARE MODE')
        for table in (*TABLES, 'sincronizacoes_monitor_admins'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        cursor.execute('SELECT fuso_origem,publicado_em,cache_sha256 FROM operacional.fontes_monitor_admins '
                       'WHERE id=%s FOR UPDATE', (SOURCE_ID,))
        source = cursor.fetchone()
        if not source or source[0] != catalog.source_timezone:
            raise SnapshotError('Fonte inicial ausente ou fuso divergente.')
        if source[1] > catalog.published_at:
            return 'cache_mais_antigo_ignorado'
        if source[1] == catalog.published_at and source[2] != catalog.hashes[0]:
            raise SnapshotError('Cache conflitante no mesmo horario de publicacao.')
        cursor.execute(MARKER_SQL, (SOURCE_ID,))
        marker = cursor.fetchone()
        if marker and marker[2] != snapshot.config_hash:
            raise SnapshotError('Origem da baseline mudou. Revisao manual exigida.')
        if marker and marker[0] > snapshot.captured_at:
            return 'publicacao_mais_antiga_ignorada'
        if marker and marker[0] == snapshot.captured_at and marker[1] != snapshot.digest:
            raise SnapshotError('Conteudo conflitante no mesmo horario de captura.')
        validate_source(snapshot)
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(catalog.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(catalog.regional_codes):
            raise SnapshotError('Regionais ausentes no banco.')
        changed = not marker or marker[1] != snapshot.digest
        if changed:
            _write_devices(cursor, snapshot)
            _write_baseline_and_differences(cursor, catalog)
        _verify_rows(cursor, catalog)
        validate_source(snapshot)
        cursor.execute('UPDATE operacional.fontes_monitor_admins SET cache_sha256=%s,baseline_sha256=%s,'
                       'firewalls_sha256=%s,catalogo_regionais_sha256=%s,publicado_em=%s WHERE id=%s',
                       (*catalog.hashes, catalog.published_at, SOURCE_ID))
        cursor.execute('INSERT INTO operacional.sincronizacoes_monitor_admins '
                       '(fonte_id,lido_em,conteudo_sha256,origem_config_sha256) VALUES (%s,%s,%s,%s) '
                       'ON CONFLICT(fonte_id) DO UPDATE SET lido_em=EXCLUDED.lido_em,conteudo_sha256=EXCLUDED.conteudo_sha256,'
                       'origem_config_sha256=EXCLUDED.origem_config_sha256,sincronizado_em=CURRENT_TIMESTAMP',
                       (SOURCE_ID, snapshot.captured_at, snapshot.digest, snapshot.config_hash))
    return 'sincronizado' if changed else 'sem_alteracoes'


def poll_admin_catalog(logger):
    if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL' or not shadow_enabled(CONFIG_PATH):
        return False
    try:
        with _InterprocessFileLock(LOCK_PATH, timeout=0.25):
            snapshot = read_current_snapshot()
            save_admin_publication(snapshot, PUBLICATION_PATH)
            if not shadow_enabled(CONFIG_PATH):
                return False
            with connect_collector() as connection:
                write_admin_snapshot(connection, snapshot)
        return True
    except Exception as exc:
        _safe_warning(logger, 'falha_sincronizacao_admins', exc)
        return False


def start_admin_sync_worker(logger=None):
    global _worker
    logger = logger or logging.getLogger(__name__)
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return _worker
        def run():
            while True:
                poll_admin_catalog(logger)
                threading.Event().wait(POLL_SECONDS)
        _worker = threading.Thread(target=run, name='sentinel-admins-shadow', daemon=True)
        _worker.start()
        return _worker
