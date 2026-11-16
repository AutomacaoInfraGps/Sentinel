"""Parallel upserts of verified VPN observations after native cache publication."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from core.secret_store import _InterprocessFileLock
from scripts.database.import_switch_catalog import _load
from scripts.database.import_vpn_catalog import build_vpn_catalog
from services.operational_postgres import (
    PROJECT_ROOT, ShadowWorker, SnapshotError, _identity, _safe_warning,
    connect_collector, shadow_enabled,
)

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-vpns-shadow.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/vpns_postgres_publication.json'
STATE_PATH = PROJECT_ROOT / 'output/sentinel_operational_state.json'
REGIONAL_PATH = PROJECT_ROOT / 'estrutura_regionais.json'
FIELDS = ('firewall_serial', 'vdom', 'tunel', 'device', 'device_namespace',
          'regional', 'status', 'coletado_em', 'vpn_source', 'vdom_origem',
          'interface', 'ultima_verificacao')
MARKER_SQL = '''SELECT coletado_em,conteudo_sha256 FROM operacional.sincronizacoes_vpns
    WHERE firewall_serial=%s AND vdom=%s'''
COUNTS_SQL = '''SELECT count(*),count(*) FILTER (WHERE codigo_regional IS NULL)
    FROM operacional.vpns WHERE firewall_serial=%s AND vdom=%s AND presente_no_snapshot'''


@dataclass(frozen=True, repr=False)
class VPNSnapshot:
    published_at: datetime
    digest: str
    regional_codes: tuple = field(repr=False)
    rows: tuple = field(repr=False)
    artifact: bytes = field(repr=False)

    @property
    def scope(self):
        return self.rows[0][:2]

    def summary(self):
        return {'coletado_em': self.published_at.isoformat(), 'sha256_normalizado': self.digest,
                'vpns_na_publicacao': len(self.rows), 'contextos_dispositivo_vdom': 1,
                'por_status': dict(Counter(row[8] for row in self.rows)),
                'vinculos_na_publicacao': dict(Counter(row[7] for row in self.rows)),
                'por_origem_vdom': dict(Counter(row[11] for row in self.rows))}


def prepare_vpn_snapshot(records, regions):
    if not isinstance(records, list) or not records:
        raise SnapshotError('Publicacao VPN ausente ou vazia; banco preservado.')
    entries = regions.get('regionais') if isinstance(regions, dict) else None
    if not isinstance(entries, dict):
        raise SnapshotError('Catalogo regional invalido.')
    # Only operational columns and regional codes reach the checkpoint/queue.
    safe_records = []
    for record in records:
        if not isinstance(record, dict):
            raise SnapshotError('Registro VPN invalido.')
        safe_records.append({key: record.get(key) for key in FIELDS})
    safe_regions = {'regionais': {code: {} for code in entries}}
    raw = json.dumps({'groups': {'vpns': {'source': 'vpn_manual', 'records': safe_records}}},
                     sort_keys=True, ensure_ascii=True).encode()
    catalog = build_vpn_catalog(raw, json.dumps(safe_regions, sort_keys=True).encode())
    if len({row[:2] for row in catalog.rows}) != 1 or len({row[9] for row in catalog.rows}) != 1:
        raise SnapshotError('Publicacao exige uma coleta e um contexto de hub/VDOM unicos.')
    ordered = [dict(zip(FIELDS, (row[0], row[1], row[2], row[3], row[4], row[6],
                                 row[8], row[9].isoformat(), row[10], row[11], row[12], row[13])))
               for row in catalog.rows]
    artifact = json.dumps({'version': 1, 'records': ordered, 'regionals': safe_regions},
                          sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()
    return VPNSnapshot(catalog.rows[0][9].astimezone(timezone.utc),
                       hashlib.sha256(artifact).hexdigest(), catalog.regional_codes,
                       catalog.rows, artifact)


def load_vpn_publication(path=PUBLICATION_PATH):
    payload = _load(Path(path).read_bytes())
    if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 1:
        raise SnapshotError('Controle de publicacao VPN invalido.')
    return prepare_vpn_snapshot(payload.get('records'), payload.get('regionals'))


def save_vpn_publication(snapshot, path=PUBLICATION_PATH):
    path = Path(path)
    with _InterprocessFileLock(path.with_suffix('.lock'), timeout=0.25):
        if path.exists():
            current = load_vpn_publication(path)
            if current.scope != snapshot.scope:
                raise SnapshotError('Hub/VDOM mudou. Homologar novo contexto antes de sincronizar.')
            if current.published_at > snapshot.published_at:
                return False
            if current.published_at == snapshot.published_at and current.digest != snapshot.digest:
                raise SnapshotError('Conteudos VPN conflitantes na mesma coleta.')
        descriptor, temporary = tempfile.mkstemp(prefix='.vpn-pg-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(snapshot.artifact)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return True


def inspect_vpn_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute(MARKER_SQL, snapshot.scope)
        current = cursor.fetchone()
        cursor.execute(COUNTS_SQL, snapshot.scope)
        counts = cursor.fetchone()
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao',
            'banco_vpns_presentes_no_contexto': counts[0], 'banco_vpns_sem_vinculo': counts[1],
            'ultima_coleta_sincronizada': current[0].isoformat() if current else None,
            'conteudo_ja_sincronizado': bool(current and current[1] == snapshot.digest),
            'coleta_mais_antiga': bool(current and snapshot.published_at < current[0])}


def write_vpn_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='1s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute('''LOCK TABLE operacional.regionais,operacional.vpns,
            operacional.sincronizacoes_vpns IN SHARE ROW EXCLUSIVE MODE''')
        cursor.execute(MARKER_SQL, snapshot.scope)
        current = cursor.fetchone()
        if current and current[1] == snapshot.digest:
            return 'sem_alteracoes'
        if current and current[0] > snapshot.published_at:
            return 'coleta_antiga_ignorada'
        if current and current[0] == snapshot.published_at:
            raise SnapshotError('Conteudos VPN conflitantes na mesma coleta.')
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)',
                       (list(snapshot.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(snapshot.regional_codes):
            raise SnapshotError('Catalogo regional ainda nao sincronizado.')
        # Do not silently switch to another hub or merge a future fallback by name.
        cursor.execute('SELECT DISTINCT firewall_serial,vdom FROM operacional.vpns')
        if set(cursor.fetchall()) != {snapshot.scope}:
            raise SnapshotError('Contexto SQL difere da carga inicial homologada.')
        for row in snapshot.rows:
            cursor.execute('''INSERT INTO operacional.vpns AS v
                (firewall_serial,vdom,tunel,dispositivo_nome,dispositivo_namespace,
                 codigo_regional,regional_origem,vinculo_regional,status,coletado_em,
                 via_coleta,vdom_origem,interface,hora_verificacao_legada,
                 arquivo_origem_sha256,catalogo_regionais_sha256,atualizado_no_banco_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,CURRENT_TIMESTAMP)
                ON CONFLICT(firewall_serial,vdom,tunel) DO UPDATE SET
                 dispositivo_nome=EXCLUDED.dispositivo_nome,dispositivo_namespace=EXCLUDED.dispositivo_namespace,
                 codigo_regional=EXCLUDED.codigo_regional,regional_origem=EXCLUDED.regional_origem,
                 vinculo_regional=EXCLUDED.vinculo_regional,status=EXCLUDED.status,
                 coletado_em=EXCLUDED.coletado_em,via_coleta=EXCLUDED.via_coleta,
                 vdom_origem=EXCLUDED.vdom_origem,interface=EXCLUDED.interface,
                 hora_verificacao_legada=EXCLUDED.hora_verificacao_legada,
                 arquivo_origem_sha256=NULL,catalogo_regionais_sha256=NULL,
                 presente_no_snapshot=true,atualizado_no_banco_em=CURRENT_TIMESTAMP
                WHERE EXCLUDED.coletado_em >= v.coletado_em''', row)
        cursor.execute('''SELECT count(*) FROM operacional.vpns
            WHERE firewall_serial=%s AND vdom=%s AND presente_no_snapshot AND tunel=ANY(%s)''',
                       (*snapshot.scope, [row[2] for row in snapshot.rows]))
        if cursor.fetchone() != (len(snapshot.rows),):
            raise SnapshotError('Contagem das VPNs publicadas divergente.')
        cursor.execute('''INSERT INTO operacional.sincronizacoes_vpns
            (firewall_serial,vdom,coletado_em,conteudo_sha256,registros_publicados) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(firewall_serial,vdom) DO UPDATE SET coletado_em=EXCLUDED.coletado_em,
            conteudo_sha256=EXCLUDED.conteudo_sha256,registros_publicados=EXCLUDED.registros_publicados,
            sincronizado_em=CURRENT_TIMESTAMP''',
                       (*snapshot.scope, snapshot.published_at, snapshot.digest, len(snapshot.rows)))
    return 'sincronizado'


class VPNShadowWorker(ShadowWorker):
    def _run(self):
        while True:
            snapshot, logger = self.pending.get()
            try:
                if shadow_enabled(CONFIG_PATH):
                    with connect_collector() as connection:
                        write_vpn_snapshot(connection, snapshot)
            except Exception as exc:
                _safe_warning(logger, 'falha_sincronizacao_vpns', exc)
            finally:
                self.pending.task_done()


_worker = VPNShadowWorker()


def publish_vpn_records(records, source_path, logger):
    try:
        if Path(source_path).resolve() != STATE_PATH.resolve():
            return False
        snapshot = prepare_vpn_snapshot(records, _load(REGIONAL_PATH.read_bytes()))
        if not save_vpn_publication(snapshot):
            return False
        if shadow_enabled(CONFIG_PATH):
            _worker.submit(snapshot, logger)
        return True
    except Exception as exc:
        _safe_warning(logger, 'publicacao_vpns_nao_preparada', exc)
        return False
