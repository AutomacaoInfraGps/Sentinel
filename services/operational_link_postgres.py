"""Parallel link observations with per-link clocks, never freshen fallback data."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import tempfile
import threading

from core.secret_store import _InterprocessFileLock
from scripts.database.import_link_catalog import COLUMNS, ORIGINS, build_link_catalog, _identifier
from scripts.database.import_switch_catalog import _load
from scripts.database.import_vpn_catalog import _aware_time
from services.operational_postgres import (
    PROJECT_ROOT, ShadowWorker, SnapshotError, _identity, _safe_warning,
    connect_collector, shadow_enabled,
)

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-links-shadow.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/links_postgres_publication.json'
CATALOG_PATH = PROJECT_ROOT / 'estrutura_regionais.json'
RECORD_KEYS = ('id', 'nome', 'interface_monitorada', 'fortigate_host', 'fortigate_porta',
               'firewall_serial', 'vdom', 'provedor', 'ip', 'mascara', 'velocidade',
               'status', 'ativo', 'origem_sync', 'modo_verificacao', 'sla_status',
               'link_mode_status', 'sdwan_member_id', 'priority', 'packet_loss_percent',
               'ultima_verificacao', 'coletado_em')
BASES = {'sdwan_monitor', 'proxy_interface'}
MARKER_SQL = '''SELECT coletado_em,conteudo_sha256 FROM operacional.sincronizacoes_links
    WHERE codigo_regional=%s AND id_origem=%s'''


def _json(value):
    return json.dumps(value, default=lambda item: item.isoformat(), sort_keys=True,
                      ensure_ascii=True, separators=(',', ':')).encode()


def _row_digest(row):
    return hashlib.sha256(_json(row)).hexdigest()


@dataclass(frozen=True, repr=False)
class LinkSnapshot:
    published_at: datetime
    digest: str
    regional_codes: tuple = field(repr=False)
    rows: tuple = field(repr=False)
    artifact: bytes = field(repr=False)

    def summary(self):
        times = [row[22] for row in self.rows]
        return {'capturado_em': self.published_at.isoformat(), 'sha256_normalizado': self.digest,
                'links_com_observacao_confirmada': len(self.rows),
                'regionais_com_observacao_confirmada': len({row[0] for row in self.rows}),
                'coleta_mais_antiga_na_publicacao': min(times).isoformat(),
                'coleta_mais_recente_na_publicacao': max(times).isoformat(),
                'por_status': dict(Counter(row[12] for row in self.rows)),
                'por_evidencia': dict(Counter(row[24] for row in self.rows))}


def _snapshot(rows, codes, captured):
    catalog = {'regionais': {code: {'links_internet_auto': []} for code in sorted(codes)}}
    rows = tuple(sorted(rows, key=lambda row: row[:2]))
    for row in rows:
        record = dict(zip(RECORD_KEYS, row[1:23]))
        record.update(coleta_status_confirmada=True, coleta_status_origem=row[24])
        catalog['regionais'][row[0]]['links_internet_auto'].append(record)
    artifact = _json({'version': 1, 'captured_at': captured.isoformat(), 'catalog': catalog})
    return LinkSnapshot(captured, hashlib.sha256(artifact).hexdigest(), tuple(sorted(codes)), rows, artifact)


def prepare_link_snapshot(payload, captured_at):
    if not isinstance(captured_at, datetime) or captured_at.utcoffset() is None:
        raise SnapshotError('Publicacao de links exige horario com fuso.')
    entries = payload.get('regionais') if isinstance(payload, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise SnapshotError('Catalogo regional invalido.')
    selected, bases = {'regionais': {}}, {}
    for code, entry in entries.items():
        if not isinstance(entry, dict):
            raise SnapshotError('Cadastro regional invalido.')
        selected['regionais'][code] = {'links_internet_auto': []}
        records = entry.get('links_internet_auto', [])
        if not isinstance(records, list):
            raise SnapshotError('Lista automatica invalida.')
        for item in records:
            if not isinstance(item, dict):
                raise SnapshotError('Link invalido.')
            if item.get('coleta_status_confirmada') is not True:
                continue
            basis = item.get('coleta_status_origem')
            if basis not in BASES or item.get('origem_sync') not in ORIGINS - {'fallback_local'}:
                raise SnapshotError('Evidencia de coleta nao reconhecida.')
            if (basis == 'sdwan_monitor' and item.get('modo_verificacao') not in
                    {'monitor_zabbix_packet_loss', 'sla'}):
                raise SnapshotError('Modo incoerente com evidencia SD-WAN.')
            if basis == 'proxy_interface' and item.get('link_mode_status') not in {'online', 'offline'}:
                raise SnapshotError('Estado runtime de interface ausente.')
            collected = _aware_time(item.get('coletado_em'))
            record = {key: item.get(key) for key in RECORD_KEYS}
            record['coletado_em'] = collected.isoformat()
            # SQL observation time is the confirmed response, not a cache save.
            record['ultima_verificacao'] = collected.isoformat()
            if item.get('modo_verificacao') != 'monitor_zabbix_packet_loss':
                record['packet_loss_percent'] = None
            selected['regionais'][code]['links_internet_auto'].append(record)
            bases[(code, _identifier(item.get('id')))] = basis
    if not bases:
        raise SnapshotError('Nenhum link com coleta confirmada. Banco e controle anteriores preservados.')
    catalog = build_link_catalog(_json(selected), 'UTC')
    rows = tuple((*row, bases[row[:2]]) for row in catalog.rows)
    return _snapshot(rows, catalog.regional_codes, captured_at.astimezone(timezone.utc))


def load_link_publication(path=PUBLICATION_PATH):
    payload = _load(Path(path).read_bytes())
    if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 1:
        raise SnapshotError('Controle de links invalido.')
    return prepare_link_snapshot(payload.get('catalog'), _aware_time(payload.get('captured_at')))


def _merge_snapshots(current, incoming):
    merged = {row[:2]: row for row in current.rows}
    for row in incoming.rows:
        previous = merged.get(row[:2])
        if previous and previous[22] == row[22] and previous != row:
            raise SnapshotError('Observacoes conflitantes do mesmo link no mesmo instante.')
        if not previous or row[22] > previous[22]:
            merged[row[:2]] = row
    return _snapshot(merged.values(), set(current.regional_codes) | set(incoming.regional_codes),
                     max(current.published_at, incoming.published_at))


def save_link_publication(snapshot, path=PUBLICATION_PATH):
    """Retain newest confirmed observation per identity across partial saves."""
    path = Path(path)
    with _InterprocessFileLock(path.with_suffix('.lock'), timeout=0.25):
        if path.exists():
            snapshot = _merge_snapshots(load_link_publication(path), snapshot)
        descriptor, temporary = tempfile.mkstemp(prefix='.links-pg-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(snapshot.artifact)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return snapshot


def inspect_link_snapshot(connection, snapshot):
    processed = 0
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        for row in snapshot.rows:
            cursor.execute(MARKER_SQL, row[:2])
            marker = cursor.fetchone()
            processed += bool(marker and marker[1] == _row_digest(row))
        cursor.execute('''SELECT count(*),count(coletado_em) FROM operacional.links_internet
            WHERE presente_no_snapshot''')
        total, observed = cursor.fetchone()
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao',
            'banco_links_presentes': total, 'banco_links_com_coleta_explicita': observed,
            'links_processados_desta_publicacao': processed,
            'links_pendentes_desta_publicacao': len(snapshot.rows) - processed,
            'conteudo_ja_sincronizado': processed == len(snapshot.rows)}


def write_link_snapshot(connection, snapshot):
    changed = False
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='1s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute('''LOCK TABLE operacional.regionais,operacional.links_internet,
            operacional.sincronizacoes_links IN SHARE ROW EXCLUSIVE MODE''')
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)',
                       (list(snapshot.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(snapshot.regional_codes):
            raise SnapshotError('Catalogo regional ainda nao sincronizado.')
        for row in snapshot.rows:
            digest = _row_digest(row)
            cursor.execute(MARKER_SQL, row[:2])
            marker = cursor.fetchone()
            if marker and (marker[1] == digest or marker[0] > row[22]):
                continue
            if marker and marker[0] == row[22]:
                raise SnapshotError('Observacoes conflitantes do mesmo link no mesmo instante.')
            columns = (*COLUMNS, 'coleta_status_origem')
            updates = ','.join(f'{key}=EXCLUDED.{key}' for key in columns[2:])
            cursor.execute('INSERT INTO operacional.links_internet AS l (' + ','.join(columns) +
                           ',arquivo_origem_sha256,fuso_verificacao_legada,atualizado_no_banco_em) VALUES (' +
                           ','.join(['%s'] * len(columns)) + ",NULL,'UTC',CURRENT_TIMESTAMP) " +
                           'ON CONFLICT(codigo_regional,id_origem) DO UPDATE SET ' + updates +
                           ",arquivo_origem_sha256=NULL,fuso_verificacao_legada='UTC'," +
                           'presente_no_snapshot=true,atualizado_no_banco_em=CURRENT_TIMESTAMP ' +
                           'WHERE l.coletado_em IS NULL OR EXCLUDED.coletado_em >= l.coletado_em', row)
            cursor.execute('''SELECT count(*) FROM operacional.links_internet
                WHERE codigo_regional=%s AND id_origem=%s AND presente_no_snapshot''', row[:2])
            if cursor.fetchone() != (1,):
                raise SnapshotError('Link publicado nao confirmado no banco.')
            cursor.execute('''INSERT INTO operacional.sincronizacoes_links
                (codigo_regional,id_origem,coletado_em,conteudo_sha256) VALUES (%s,%s,%s,%s)
                ON CONFLICT(codigo_regional,id_origem) DO UPDATE SET coletado_em=EXCLUDED.coletado_em,
                conteudo_sha256=EXCLUDED.conteudo_sha256,sincronizado_em=CURRENT_TIMESTAMP''',
                           (*row[:2], row[22], digest))
            changed = True
    return 'sincronizado' if changed else 'sem_alteracoes'


class LinkShadowWorker(ShadowWorker):
    def submit(self, snapshot, logger):
        # Publication order alone cannot order observations of different regions.
        with self.lock:
            if not self.started:
                threading.Thread(target=self._run, name='sentinel-postgres-links', daemon=True).start()
                self.started = True
            try:
                pending, _ = self.pending.get_nowait()
                self.pending.task_done()
                snapshot = _merge_snapshots(pending, snapshot)
            except queue.Empty:
                pass
            self.pending.put_nowait((snapshot, logger))

    def _run(self):
        while True:
            snapshot, logger = self.pending.get()
            try:
                if shadow_enabled(CONFIG_PATH):
                    with connect_collector() as connection:
                        write_link_snapshot(connection, snapshot)
            except Exception as exc:
                _safe_warning(logger, 'falha_sincronizacao_links', exc)
            finally:
                self.pending.task_done()


_worker = LinkShadowWorker()


def publish_link_catalog(payload, source_path, logger):
    try:
        if Path(source_path).resolve() != CATALOG_PATH.resolve():
            return False
        snapshot = prepare_link_snapshot(payload, datetime.now(timezone.utc))
        snapshot = save_link_publication(snapshot)
        if shadow_enabled(CONFIG_PATH):
            _worker.submit(snapshot, logger)
        return True
    except Exception as exc:
        _safe_warning(logger, 'publicacao_links_nao_preparada', exc)
        return False
