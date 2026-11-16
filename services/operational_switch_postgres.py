"""Bounded shadow persistence of explicitly published switch cache projections."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from core.secret_store import _InterprocessFileLock
from scripts.database.import_switch_catalog import SOURCE, _load, build_switch_catalog
from services.operational_postgres import (
    PROJECT_ROOT, SOURCE_TIMEZONE, ShadowWorker, SnapshotError, _identity,
    _safe_warning, connect_collector, shadow_enabled,
)


CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-switches-shadow.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/switches_postgres_publication.json'
CACHE_PATH = PROJECT_ROOT / 'output/switches_status_cache.json'
REGIONAL_PATH = PROJECT_ROOT / 'estrutura_regionais.json'
FIELDS = ('hostid', 'regional', 'ip', 'modelo', 'modelo_source', 'is_core', 'core_source',
          'local', 'local_only', 'zabbix_host', 'zabbix_name', 'status', 'ultima_verificacao',
          'em_manutencao', 'maintenance_status', 'maintenance_type', 'maintenanceid', 'maintenance_scope')
MARKER_SQL = """SELECT publicado_em,conteudo_sha256 FROM operacional.sincronizacoes_switches
    WHERE fonte='sentinel_zabbix_principal'"""
COUNTS_SQL = """SELECT count(*),count(*) FILTER (WHERE codigo_regional IS NULL)
    FROM operacional.switches WHERE fonte='sentinel_zabbix_principal' AND presente_no_snapshot"""


@dataclass(frozen=True, repr=False)
class SwitchSnapshot:
    published_at: datetime
    digest: str
    full_inventory: bool
    regional_codes: tuple = field(repr=False)
    rows: tuple = field(repr=False)
    artifact: bytes = field(repr=False)

    def summary(self):
        return {'publicado_em': self.published_at.isoformat(), 'sha256_normalizado': self.digest,
                'inventario_completo': self.full_inventory, 'switches_na_publicacao': len(self.rows),
                'vinculos_na_publicacao': dict(Counter(row[7] for row in self.rows)),
                'sem_data_de_observacao': sum(row[16] is None for row in self.rows)}


def prepare_switch_snapshot(cache, regions, published_at, full_inventory):
    if (not isinstance(published_at, datetime) or published_at.utcoffset() is None
            or type(full_inventory) is not bool):
        raise SnapshotError('Publicacao de switches exige horario com fuso e tipo explicito.')
    if not isinstance(cache, dict) or not isinstance(regions, dict) or not isinstance(regions.get('regionais'), dict):
        raise SnapshotError('Origem de switches invalida.')
    safe_cache, safe_regions = {}, {'regionais': {}}
    for code, entry in regions['regionais'].items():
        if not isinstance(entry, dict):
            raise SnapshotError('Regional invalida na publicacao.')
        safe_regions['regionais'][code] = {'nome': entry.get('nome')}
    for name, record in cache.items():
        if not isinstance(record, dict):
            raise SnapshotError('Switch invalido na publicacao.')
        safe = {key: record.get(key) for key in FIELDS}
        warnings = record.get('warning_problemas')
        if warnings is not None and not isinstance(warnings, list):
            raise SnapshotError('Lista de alertas invalida.')
        # Counts only: neither diagnostic text nor arbitrary nested source data.
        safe['warning_problemas'] = [None] * len(warnings) if warnings is not None else None
        safe_cache[name] = safe
    cache_bytes = json.dumps(safe_cache, sort_keys=True, ensure_ascii=True).encode()
    region_bytes = json.dumps(safe_regions, sort_keys=True, ensure_ascii=True).encode()
    catalog = build_switch_catalog(cache_bytes, region_bytes, SOURCE_TIMEZONE)
    published_at = published_at.astimezone(timezone.utc)
    artifact = json.dumps({'version': 1, 'published_at': published_at.isoformat(),
                           'full_inventory': full_inventory, 'cache': safe_cache, 'regionals': safe_regions},
                          sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()
    return SwitchSnapshot(published_at, hashlib.sha256(artifact).hexdigest(), full_inventory,
                          catalog.regional_codes, catalog.rows, artifact)


def load_switch_publication(path=PUBLICATION_PATH):
    payload = _load(Path(path).read_bytes())
    if (not isinstance(payload, dict) or type(payload.get('version')) is not int
            or payload.get('version') != 1):
        raise SnapshotError('Controle de publicacao de switches invalido.')
    try:
        published = datetime.fromisoformat(payload['published_at'])
    except (KeyError, TypeError, ValueError):
        raise SnapshotError('Horario da publicacao invalido.') from None
    return prepare_switch_snapshot(payload.get('cache'), payload.get('regionals'), published,
                                   payload.get('full_inventory'))


def save_switch_publication(snapshot, path=PUBLICATION_PATH):
    """Serialize checkpoints across processes, without touching the legacy cache."""
    path = Path(path)
    with _InterprocessFileLock(path.with_suffix('.lock'), timeout=0.25):
        if path.exists():
            current = load_switch_publication(path)
            if current.published_at > snapshot.published_at:
                return False
            if current.published_at == snapshot.published_at and current.digest != snapshot.digest:
                raise SnapshotError('Publicacoes conflitantes no mesmo horario.')
        descriptor, temporary = tempfile.mkstemp(prefix='.switch-pg-', suffix='.tmp', dir=path.parent)
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


def inspect_switch_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute(MARKER_SQL)
        current = cursor.fetchone()
        cursor.execute(COUNTS_SQL)
        counts = cursor.fetchone()
    return {**snapshot.summary(), 'modo': 'conferencia_sem_gravacao',
            'banco_switches_presentes': counts[0], 'banco_switches_sem_vinculo': counts[1],
            'ultima_publicacao_sincronizada': current[0].isoformat() if current else None,
            'conteudo_ja_sincronizado': bool(current and current[1] == snapshot.digest),
            'publicacao_mais_antiga': bool(current and snapshot.published_at < current[0])}


def write_switch_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='1s'")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        _identity(cursor)
        cursor.execute('''LOCK TABLE operacional.regionais,operacional.switches,
            operacional.sincronizacoes_switches IN SHARE ROW EXCLUSIVE MODE''')
        cursor.execute(MARKER_SQL)
        current = cursor.fetchone()
        if current and current[1] == snapshot.digest:
            return 'sem_alteracoes'
        if current and current[0] > snapshot.published_at:
            return 'publicacao_antiga_ignorada'
        if current and current[0] == snapshot.published_at:
            raise SnapshotError('Publicacoes conflitantes no mesmo horario.')
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)',
                       (list(snapshot.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(snapshot.regional_codes):
            raise SnapshotError('Catalogo regional ainda nao sincronizado. Publicacao cancelada.')
        if snapshot.full_inventory:
            cursor.execute("UPDATE operacional.switches SET presente_no_snapshot=false WHERE fonte=%s AND presente_no_snapshot", (SOURCE,))
        for row in snapshot.rows:
            # Maintenance and alert counts follow the same observation as status.
            newer = '(s.ultima_verificacao IS NULL OR EXCLUDED.ultima_verificacao >= s.ultima_verificacao)'
            observations = ('status', 'ultima_verificacao', 'em_manutencao', 'maintenance_status',
                            'maintenance_type', 'maintenance_id', 'maintenance_scope', 'alertas_ativos')
            observation_updates = ','.join(f'{key}=CASE WHEN {newer} THEN EXCLUDED.{key} ELSE s.{key} END'
                                           for key in observations)
            cursor.execute('''INSERT INTO operacional.switches AS s
                (fonte,tipo_origem,id_origem,nome,zabbix_host,zabbix_nome,codigo_regional,
                 regional_origem,vinculo_regional,endereco,ip,modelo,modelo_origem,localizacao,
                 is_core,core_origem,status,ultima_verificacao,em_manutencao,maintenance_status,
                 maintenance_type,maintenance_id,maintenance_scope,alertas_ativos,
                 arquivo_origem_sha256,catalogo_regionais_sha256,presente_no_snapshot,atualizado_no_banco_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,true,CURRENT_TIMESTAMP)
                ON CONFLICT(fonte,tipo_origem,id_origem) DO UPDATE SET
                 nome=EXCLUDED.nome,zabbix_host=EXCLUDED.zabbix_host,zabbix_nome=EXCLUDED.zabbix_nome,
                 codigo_regional=EXCLUDED.codigo_regional,regional_origem=EXCLUDED.regional_origem,
                 vinculo_regional=EXCLUDED.vinculo_regional,endereco=EXCLUDED.endereco,ip=EXCLUDED.ip,
                 modelo=EXCLUDED.modelo,modelo_origem=EXCLUDED.modelo_origem,localizacao=EXCLUDED.localizacao,
                 is_core=EXCLUDED.is_core,core_origem=EXCLUDED.core_origem,presente_no_snapshot=true,
                 arquivo_origem_sha256=NULL,catalogo_regionais_sha256=NULL,
                 atualizado_no_banco_em=CURRENT_TIMESTAMP,''' + observation_updates, (SOURCE, *row))
        cursor.execute('''SELECT count(*) FROM operacional.switches WHERE fonte=%s AND presente_no_snapshot
            AND (tipo_origem,id_origem) IN (SELECT * FROM unnest(%s::text[],%s::text[]))''',
            (SOURCE, [row[0] for row in snapshot.rows], [row[1] for row in snapshot.rows]))
        if cursor.fetchone() != (len(snapshot.rows),):
            raise SnapshotError('Contagem dos switches publicados divergente.')
        if snapshot.full_inventory:
            cursor.execute(COUNTS_SQL)
            if cursor.fetchone()[0] != len(snapshot.rows):
                raise SnapshotError('Contagem do inventario completo divergente.')
        cursor.execute('''INSERT INTO operacional.sincronizacoes_switches
            (fonte,publicado_em,conteudo_sha256,inventario_completo) VALUES (%s,%s,%s,%s)
            ON CONFLICT(fonte) DO UPDATE SET publicado_em=EXCLUDED.publicado_em,
            conteudo_sha256=EXCLUDED.conteudo_sha256,inventario_completo=EXCLUDED.inventario_completo,
            sincronizado_em=CURRENT_TIMESTAMP''', (SOURCE, snapshot.published_at, snapshot.digest, snapshot.full_inventory))
    return 'sincronizado'


class SwitchShadowWorker(ShadowWorker):
    def _run(self):
        while True:
            snapshot, logger = self.pending.get()
            try:
                if shadow_enabled(CONFIG_PATH):
                    with connect_collector() as connection:
                        write_switch_snapshot(connection, snapshot)
            except Exception as exc:
                _safe_warning(logger, 'falha_sincronizacao_switches', exc)
            finally:
                self.pending.task_done()


_worker = SwitchShadowWorker()


def publish_switch_cache(cache, source_path, published_at, full_inventory, logger):
    """Checkpoint on real saves; SQL remains disabled unless its own flag is true."""
    try:
        if Path(source_path).resolve() != CACHE_PATH.resolve():
            return False
        regions = _load(REGIONAL_PATH.read_bytes())
        snapshot = prepare_switch_snapshot(cache, regions, published_at, full_inventory)
        if not save_switch_publication(snapshot):
            return False
        if shadow_enabled(CONFIG_PATH):
            _worker.submit(snapshot, logger)
        return True
    except Exception as exc:
        _safe_warning(logger, 'publicacao_switches_nao_preparada', exc)
        return False
