"""Opt-in configured WLAN upserts; missing observations never imply removal."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from core.secret_store import _InterprocessFileLock
from scripts.database.import_wlan_catalog import COLUMNS, build_wlan_catalog, _inspect_parents
from scripts.database.import_switch_catalog import _load
from scripts.database.import_vpn_catalog import _aware_time
from services.operational_postgres import (
    PROJECT_ROOT, SnapshotError, _identity, _safe_warning, connect_collector, shadow_enabled,
)

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-wlans-shadow.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/wlans_postgres_publication.json'
SOURCE_PATH = PROJECT_ROOT / 'data/unifi.json'
REGIONALS_PATH = PROJECT_ROOT / 'estrutura_regionais.json'
WLAN_FIELDS = ('wlan_id', 'nome', 'networkconf_id', 'ativo', 'bandas', 'coletado_em', 'origem')
MARKER_SQL = ('SELECT coletado_em,conteudo_sha256 FROM operacional.sincronizacoes_wlans '
              'WHERE controladora_id=%s AND site_id=%s AND id_origem=%s')


def _json(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'),
                      default=lambda item: item.isoformat()).encode()


@dataclass(frozen=True, repr=False)
class WlanSnapshot:
    captured_at: datetime
    digest: str
    catalog: object = field(repr=False)
    artifact: bytes = field(repr=False)

    def summary(self):
        summary = self.catalog.summary()
        return {'capturado_em': self.captured_at.isoformat(), 'sha256_normalizado': self.digest,
                'sites_com_coleta_confirmada': len(self.catalog.sites),
                'wlans_com_observacao_confirmada': len(self.catalog.rows),
                'coleta_mais_antiga_na_publicacao': summary['coleta_mais_antiga'],
                'coleta_mais_recente_na_publicacao': summary['coleta_mais_recente'],
                'por_ativo': summary['por_ativo'], 'wlans_sem_regional': summary['wlans_sem_regional']}


def prepare_wlan_snapshot(payload, regional_payload, captured_at):
    if not isinstance(captured_at, datetime) or captured_at.utcoffset() is None:
        raise SnapshotError('Captura sem fuso.')
    if not isinstance(payload, dict) or not isinstance(payload.get('sites'), list):
        raise SnapshotError('Publicacao UniFi invalida.')
    regions = regional_payload.get('regionais') if isinstance(regional_payload, dict) else None
    if not isinstance(regions, dict) or not regions or any(not isinstance(item, dict) for item in regions.values()):
        raise SnapshotError('Catalogo regional invalido.')
    controller = payload.get('controller')
    if not isinstance(controller, dict):
        raise SnapshotError('Controladora ausente.')
    safe = {'controller': {key: controller.get(key) for key in ('ip', 'porta')}, 'sites': []}
    safe_regions = {'regionais': {code: {'nome': item.get('nome')} for code, item in regions.items()}}
    for site in payload['sites']:
        if not isinstance(site, dict):
            raise SnapshotError('Site invalido.')
        if site.get('coleta_wlans_confirmada') is not True:
            continue
        wlans = site.get('wlans_configuradas')
        if not isinstance(wlans, list) or any(not isinstance(wlan, dict) for wlan in wlans):
            raise SnapshotError('Lista WLAN invalida.')
        if _aware_time(site.get('wlans_coletadas_em')) > captured_at:
            raise SnapshotError('Coleta posterior a captura.')
        safe['sites'].append({
            'id': site.get('id'), 'nome': site.get('nome'),
            'coleta_wlans_confirmada': True, 'wlans_situacao': site.get('wlans_situacao'),
            'wlans_coletadas_em': site.get('wlans_coletadas_em'),
            'wlans_configuradas': [{key: wlan.get(key) for key in WLAN_FIELDS} for wlan in wlans],
        })
    # Reuse bootstrap validation of IDs, bindings, bands and matching site/record clocks.
    catalog = build_wlan_catalog(_json(safe), _json(safe_regions))
    canonical = (catalog.controller, catalog.regional_codes, catalog.sites, catalog.rows)
    artifact = _json({'version': 1, 'captured_at': captured_at.isoformat(),
                      'unifi': safe, 'regionals': safe_regions})
    return WlanSnapshot(captured_at, hashlib.sha256(_json(canonical)).hexdigest(), catalog, artifact)


def load_wlan_publication(path=PUBLICATION_PATH):
    payload = _load(Path(path).read_bytes())
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise SnapshotError('Versao de publicacao invalida.')
    return prepare_wlan_snapshot(payload.get('unifi'), payload.get('regionals'), _aware_time(payload.get('captured_at')))


def _row_digest(snapshot, row):
    site = next(site for site in snapshot.catalog.sites if site[0] == row[1])
    return hashlib.sha256(_json((snapshot.catalog.controller, site, row))).hexdigest()


def save_wlan_publication(snapshot, path=PUBLICATION_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _InterprocessFileLock(path.with_suffix('.lock'), timeout=0.25):
        if path.exists():
            current = load_wlan_publication(path)
            if current.catalog.controller != snapshot.catalog.controller:
                raise SnapshotError('Endpoint da controladora mudou. Revise antes de sincronizar.')
            if current.digest == snapshot.digest or current.captured_at > snapshot.captured_at:
                return current
            if current.captured_at == snapshot.captured_at:
                raise SnapshotError('Capturas conflitantes.')
            old = {row[:3]: row for row in current.catalog.rows}
            for row in snapshot.catalog.rows:
                previous = old.get(row[:3])
                if previous and (previous[7] > row[7] or (
                        previous[7] == row[7] and _row_digest(current, previous) != _row_digest(snapshot, row))):
                    raise SnapshotError('Observacao WLAN anterior ou conflitante. Controle preservado.')
        fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.wlans-', suffix='.tmp')
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


def inspect_wlan_snapshot(connection, snapshot):
    processed = older = 0
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        parents = _inspect_parents(cursor, snapshot.catalog)
        for row in snapshot.catalog.rows:
            cursor.execute(MARKER_SQL, row[:3])
            current = cursor.fetchone()
            processed += bool(current and current[1] == _row_digest(snapshot, row))
            older += bool(current and current[0] > row[7])
        cursor.execute('SELECT count(*),count(coletado_em) FROM operacional.wlans_unifi')
        counts = cursor.fetchone()
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao', 'banco': parents,
            'banco_wlans': counts[0], 'banco_wlans_com_coleta_explicita': counts[1],
            'wlans_processadas_desta_publicacao': processed,
            'wlans_pendentes_desta_publicacao': len(snapshot.catalog.rows) - processed,
            'wlans_com_coleta_mais_recente_no_banco': older,
            'conteudo_ja_sincronizado': processed == len(snapshot.catalog.rows)}


def write_wlan_snapshot(connection, snapshot):
    changed = False
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='1s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        for table in ('regionais', 'controladoras_unifi', 'sites_unifi', 'wlans_unifi', 'sincronizacoes_wlans'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN SHARE ROW EXCLUSIVE MODE')
        parents = _inspect_parents(cursor, snapshot.catalog)
        if not parents['controladora_compativel'] or any(value for key, value in parents.items() if key != 'controladora_compativel'):
            raise SnapshotError('Controladora, sites ou vinculos divergentes. Sincronizacao bloqueada.')
        for row in snapshot.catalog.rows:
            digest = _row_digest(snapshot, row)
            cursor.execute(MARKER_SQL, row[:3])
            marker = cursor.fetchone()
            if marker and (marker[1] == digest or marker[0] > row[7]):
                continue
            if marker and marker[0] == row[7]:
                raise SnapshotError('WLAN com conteudo conflitante no mesmo horario.')
            cursor.execute('SELECT ' + ','.join(COLUMNS) + ' FROM operacional.wlans_unifi '
                           'WHERE controladora_id=%s AND site_id=%s AND id_origem=%s', row[:3])
            existing = cursor.fetchone()
            if existing:
                existing = (*existing[:6], tuple(existing[6]), *existing[7:])
                if existing[7] > row[7]:
                    continue
                if existing[7] == row[7] and existing != row:
                    raise SnapshotError('WLAN cadastrada com conteudo conflitante no mesmo horario.')
            values = (*row[:6], list(row[6]), *row[7:])
            updates = ','.join(name + '=EXCLUDED.' + name for name in COLUMNS[3:])
            cursor.execute('INSERT INTO operacional.wlans_unifi AS w (' + ','.join(COLUMNS)
                           + ',atualizado_no_banco_em) VALUES (' + ','.join(['%s'] * len(COLUMNS))
                           + ',CURRENT_TIMESTAMP) ON CONFLICT(controladora_id,site_id,id_origem) DO UPDATE SET '
                           + updates + ',arquivo_origem_sha256=NULL,catalogo_regionais_sha256=NULL,'
                           'atualizado_no_banco_em=CURRENT_TIMESTAMP WHERE EXCLUDED.coletado_em>=w.coletado_em', values)
            cursor.execute('SELECT count(*) FROM operacional.wlans_unifi WHERE '
                           'controladora_id=%s AND site_id=%s AND id_origem=%s AND coletado_em=%s', (*row[:3], row[7]))
            if cursor.fetchone() != (1,):
                raise SnapshotError('WLAN nao confirmada apos gravacao. Transacao cancelada.')
            cursor.execute('INSERT INTO operacional.sincronizacoes_wlans '
                           '(controladora_id,site_id,id_origem,coletado_em,conteudo_sha256) VALUES (%s,%s,%s,%s,%s) '
                           'ON CONFLICT(controladora_id,site_id,id_origem) DO UPDATE SET '
                           'coletado_em=EXCLUDED.coletado_em,conteudo_sha256=EXCLUDED.conteudo_sha256,'
                           'sincronizado_em=CURRENT_TIMESTAMP', (*row[:3], row[7], digest))
            changed = True
    return 'sincronizado' if changed else 'sem_alteracoes'


def publish_wlan_catalog(payload, source_path, logger):
    if Path(source_path).resolve() != SOURCE_PATH.resolve():
        return False
    try:
        snapshot = prepare_wlan_snapshot(payload, _load(REGIONALS_PATH.read_bytes()), datetime.now(timezone.utc))
        snapshot = save_wlan_publication(snapshot, PUBLICATION_PATH)
        # Native collectors are short-lived: finish the transaction before returning.
        if shadow_enabled(CONFIG_PATH):
            with connect_collector() as connection:
                write_wlan_snapshot(connection, snapshot)
        return True
    except Exception as exc:
        _safe_warning(logger, 'falha_sincronizacao_wlans', exc)
        return False
