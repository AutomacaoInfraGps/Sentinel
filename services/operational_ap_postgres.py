"""Opt-in AP upserts after native UniFi JSON publication, without absence inference."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from core.secret_store import _InterprocessFileLock
from scripts.database.import_ap_catalog import AP_COLUMNS, SITE_COLUMNS, build_ap_catalog
from scripts.database.import_vpn_catalog import _aware_time
from services.operational_postgres import (
    PROJECT_ROOT, SnapshotError, _identity, _safe_warning, connect_collector, shadow_enabled,
)

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-aps-shadow.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/aps_postgres_publication.json'
SOURCE_PATH = PROJECT_ROOT / 'data/unifi.json'
REGIONALS_PATH = PROJECT_ROOT / 'estrutura_regionais.json'
NATIVE_FIELDS = ('mac', 'site_id', 'site', 'nome', 'ip', 'modelo_codigo', 'modelo', 'firmware',
                 'status', 'clientes', 'uptime', 'coletado_em', 'em_manutencao', 'coleta_status_confirmada')


def _json(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'),
                      default=lambda item: item.isoformat()).encode()


@dataclass(frozen=True, repr=False)
class ApSnapshot:
    captured_at: datetime
    digest: str
    catalog: object = field(repr=False)
    sites: tuple = field(repr=False)
    artifact: bytes = field(repr=False)

    def summary(self):
        aps = self.catalog.aps
        return {'capturado_em': self.captured_at.isoformat(), 'sha256_normalizado': self.digest,
                'sites_com_coleta_confirmada': len(self.sites), 'aps_com_observacao_confirmada': len(aps),
                'coleta_mais_antiga_na_publicacao': min(row[11] for row in aps).isoformat(),
                'coleta_mais_recente_na_publicacao': max(row[11] for row in aps).isoformat(),
                'por_status': self.catalog.summary()['por_status'],
                'aps_sem_regional': self.catalog.summary()['aps_sem_regional']}


def prepare_ap_snapshot(payload, regional_payload, captured_at):
    if not isinstance(captured_at, datetime) or captured_at.utcoffset() is None:
        raise SnapshotError('Captura sem fuso.')
    if not isinstance(payload, dict) or not isinstance(payload.get('sites'), list) or not isinstance(payload.get('aps'), list):
        raise SnapshotError('Publicacao UniFi invalida.')
    entries = regional_payload.get('regionais') if isinstance(regional_payload, dict) else None
    if not isinstance(entries, dict) or not entries or any(not isinstance(item, dict) for item in entries.values()):
        raise SnapshotError('Catalogo regional invalido.')
    controller = payload.get('controller')
    if not isinstance(controller, dict):
        raise SnapshotError('Controladora ausente.')
    safe = {'timestamp': captured_at.isoformat(),
            'controller': {key: controller.get(key) for key in ('ip', 'porta')}, 'sites': [], 'aps': []}
    safe_regionals = {'regionais': {code: {'nome': entry.get('nome')} for code, entry in entries.items()}}
    times = {}
    for site in payload['sites']:
        if not isinstance(site, dict):
            raise SnapshotError('Site invalido.')
        if site.get('coleta_aps_confirmada') is not True:
            continue
        site_id = site.get('id')
        if not isinstance(site_id, str) or site_id in times:
            raise SnapshotError('ID de site invalido ou duplicado.')
        collected = _aware_time(site.get('coletado_em'))
        if collected > captured_at:
            raise SnapshotError('Coleta do site posterior a captura.')
        times[site_id] = collected
        safe['sites'].append({'id': site_id, 'nome': site.get('nome'),
                              'coletado_em': collected.isoformat(), 'coleta_aps_confirmada': True})
    for ap in payload['aps']:
        if not isinstance(ap, dict):
            raise SnapshotError('AP invalido.')
        if ap.get('coleta_status_confirmada') is not True:
            continue
        site_id = ap.get('site_id')
        if not isinstance(site_id, str) or site_id not in times:
            raise SnapshotError('AP sem site com coleta confirmada.')
        collected = _aware_time(ap.get('coletado_em'))
        if collected != times[site_id]:
            raise SnapshotError('Coleta individual diverge da resposta do site.')
        record = {key: ap.get(key) for key in NATIVE_FIELDS}
        record['coletado_em'] = collected.isoformat()
        safe['aps'].append(record)
    if not safe['aps']:
        raise SnapshotError('Nenhum AP com observacao confirmada. Banco e publicacao anteriores preservados.')
    catalog = build_ap_catalog(_json(safe), _json(safe_regionals), 'UTC')
    site_rows = tuple((*row, times[row[1]]) for row in catalog.sites)
    canonical = (catalog.controller[:3], catalog.regional_codes, site_rows, catalog.aps)
    artifact = _json({'version': 1, 'captured_at': captured_at.isoformat(),
                      'unifi': safe, 'regionals': safe_regionals})
    return ApSnapshot(captured_at, hashlib.sha256(_json(canonical)).hexdigest(), catalog, site_rows, artifact)


def load_ap_publication(path=PUBLICATION_PATH):
    from scripts.database.import_switch_catalog import _load
    payload = _load(Path(path).read_bytes())
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise SnapshotError('Versao de publicacao invalida.')
    return prepare_ap_snapshot(payload.get('unifi'), payload.get('regionals'), _aware_time(payload.get('captured_at')))


def save_ap_publication(snapshot, path=PUBLICATION_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _InterprocessFileLock(path.with_suffix('.lock'), timeout=0.25):
        if path.exists():
            current = load_ap_publication(path)
            if current.catalog.controller[:3] != snapshot.catalog.controller[:3]:
                raise SnapshotError('Endpoint da controladora mudou. Revise antes de sincronizar.')
            if current.digest == snapshot.digest or current.captured_at > snapshot.captured_at:
                return current
            if current.captured_at == snapshot.captured_at:
                raise SnapshotError('Capturas conflitantes.')
            old = {row[:2]: row for row in current.catalog.aps}
            for row in snapshot.catalog.aps:
                previous = old.get(row[:2])
                if previous and row[11] < previous[11]:
                    raise SnapshotError('Publicacao contem observacao anterior. Controle preservado.')
                if previous and row[11] == previous[11] and _row_digest(current, previous) != _row_digest(snapshot, row):
                    raise SnapshotError('Observacao conflitante no mesmo horario. Controle preservado.')
        fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.aps-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(snapshot.artifact)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return snapshot


MARKER_SQL = ('SELECT coletado_em,conteudo_sha256 FROM operacional.sincronizacoes_aps '
              'WHERE controladora_id=%s AND mac=%s')


def _row_digest(snapshot, row):
    site = next(site for site in snapshot.sites if site[1] == row[2])
    return hashlib.sha256(_json((snapshot.catalog.controller[:3], site, row))).hexdigest()


def inspect_ap_snapshot(connection, snapshot):
    processed = 0
    older = 0
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        for row in snapshot.catalog.aps:
            cursor.execute(MARKER_SQL, row[:2])
            current = cursor.fetchone()
            processed += bool(current and current[1] == _row_digest(snapshot, row))
            older += bool(current and current[0] > row[11])
        cursor.execute('SELECT count(*),count(coletado_em) FROM operacional.aps_unifi')
        counts = cursor.fetchone()
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao',
            'banco_aps': counts[0], 'banco_aps_com_coleta_explicita': counts[1],
            'aps_processados_desta_publicacao': processed,
            'aps_pendentes_desta_publicacao': len(snapshot.catalog.aps) - processed,
            'aps_com_coleta_mais_recente_no_banco': older,
            'conteudo_ja_sincronizado': processed == len(snapshot.catalog.aps)}


def write_ap_snapshot(connection, snapshot):
    changed = False
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='1s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        for table in ('regionais', 'controladoras_unifi', 'sites_unifi', 'aps_unifi', 'sincronizacoes_aps'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN SHARE ROW EXCLUSIVE MODE')
        cursor.execute('SELECT host,porta FROM operacional.controladoras_unifi WHERE id=%s', (snapshot.catalog.controller[0],))
        if cursor.fetchone() != snapshot.catalog.controller[1:3]:
            raise SnapshotError('Controladora SQL ausente ou endpoint divergente. Carga bloqueada.')
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(snapshot.catalog.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(snapshot.catalog.regional_codes):
            raise SnapshotError('Catalogo regional divergente do banco.')
        for site in snapshot.sites:
            cursor.execute('SELECT nome,codigo_regional,vinculo_regional,coletado_em '
                           'FROM operacional.sites_unifi WHERE controladora_id=%s AND id_origem=%s', site[:2])
            current = cursor.fetchone()
            if current and current[3] is not None:
                if current[3] == site[5] and current != site[2:]:
                    raise SnapshotError('Site com conteudo conflitante no mesmo horario.')
                if current[3] >= site[5]:
                    continue
            columns = (*SITE_COLUMNS, 'coletado_em')
            cursor.execute('INSERT INTO operacional.sites_unifi AS s (' + ','.join(columns) + ',atualizado_no_banco_em) '
                           'VALUES (%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP) '
                           'ON CONFLICT(controladora_id,id_origem) DO UPDATE SET '
                           'nome=EXCLUDED.nome,codigo_regional=EXCLUDED.codigo_regional,'
                           'vinculo_regional=EXCLUDED.vinculo_regional,coletado_em=EXCLUDED.coletado_em,'
                           'atualizado_no_banco_em=CURRENT_TIMESTAMP '
                           'WHERE s.coletado_em IS NULL OR EXCLUDED.coletado_em>s.coletado_em', site)
            changed = True
        for row in snapshot.catalog.aps:
            cursor.execute(MARKER_SQL, row[:2])
            current = cursor.fetchone()
            digest = _row_digest(snapshot, row)
            if current and (current[1] == digest or current[0] > row[11]):
                continue
            if current and current[0] == row[11]:
                raise SnapshotError('AP com conteudo conflitante no mesmo horario.')
            cursor.execute('SELECT coletado_em FROM operacional.aps_unifi WHERE controladora_id=%s AND mac=%s', row[:2])
            existing = cursor.fetchone()
            if existing and existing[0] is not None and existing[0] > row[11]:
                continue
            columns = ','.join(AP_COLUMNS)
            updates = ','.join(name + '=EXCLUDED.' + name for name in AP_COLUMNS[2:])
            cursor.execute('INSERT INTO operacional.aps_unifi AS a (' + columns + ',atualizado_no_banco_em) VALUES ('
                           + ','.join(['%s'] * len(AP_COLUMNS)) + ',CURRENT_TIMESTAMP) '
                           'ON CONFLICT(controladora_id,mac) DO UPDATE SET ' + updates + ',atualizado_no_banco_em=CURRENT_TIMESTAMP '
                           'WHERE a.coletado_em IS NULL OR EXCLUDED.coletado_em>=a.coletado_em', row)
            cursor.execute('SELECT count(*) FROM operacional.aps_unifi WHERE controladora_id=%s AND mac=%s AND coletado_em=%s',
                           (*row[:2], row[11]))
            if cursor.fetchone() != (1,):
                raise SnapshotError('AP nao confirmado apos gravacao. Transacao cancelada.')
            cursor.execute('INSERT INTO operacional.sincronizacoes_aps (controladora_id,mac,coletado_em,conteudo_sha256) '
                           'VALUES (%s,%s,%s,%s) ON CONFLICT(controladora_id,mac) DO UPDATE SET '
                           'coletado_em=EXCLUDED.coletado_em,conteudo_sha256=EXCLUDED.conteudo_sha256,'
                           'sincronizado_em=CURRENT_TIMESTAMP', (*row[:2], row[11], digest))
            changed = True
        if changed:
            cursor.execute('UPDATE operacional.controladoras_unifi SET '
                           'publicacao_fonte_em=GREATEST(publicacao_fonte_em,%s),publicacao_sem_fuso_na_origem=false,'
                           'arquivo_origem_sha256=NULL,catalogo_regionais_sha256=NULL,fuso_publicacao_legada=\'UTC\','
                           'atualizado_no_banco_em=CURRENT_TIMESTAMP WHERE id=%s',
                           (snapshot.captured_at, snapshot.catalog.controller[0]))
    return 'sincronizado' if changed else 'sem_alteracoes'


def publish_ap_catalog(payload, source_path, logger):
    if Path(source_path).resolve() != SOURCE_PATH.resolve():
        return False
    try:
        from scripts.database.import_switch_catalog import _load
        snapshot = prepare_ap_snapshot(payload, _load(REGIONALS_PATH.read_bytes()), datetime.now(timezone.utc))
        snapshot = save_ap_publication(snapshot, PUBLICATION_PATH)
        # The native collectors are short-lived subprocesses: do not use a daemon queue.
        if shadow_enabled(CONFIG_PATH):
            with connect_collector() as connection:
                write_ap_snapshot(connection, snapshot)
        return True
    except Exception as exc:
        _safe_warning(logger, 'falha_sincronizacao_aps', exc)
        return False
