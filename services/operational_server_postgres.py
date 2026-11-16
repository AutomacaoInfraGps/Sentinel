"""Opt-in persistence after the authoritative regional catalog is saved."""

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.database.import_server_catalog import build_catalog
from scripts.database.import_firewall_cache import _observation
from services.operational_postgres import (
    PROJECT_ROOT, SOURCE_TIMEZONE, ShadowWorker, SnapshotError, _identity,
    _safe_warning, connect_collector, shadow_enabled,
)


CONFIG_PATH = PROJECT_ROOT / "instance" / "operational-postgres-servers-shadow.json"
SERVER_FIELDS = ("id", "nome", "tipo", "ip", "modelo", "funcao", "sistema_operacional",
                 "status", "ativo", "ultima_verificacao", "tempo_resposta")


@dataclass(frozen=True, repr=False)
class ServerSnapshot:
    published_at: datetime
    digest: str
    regionals: tuple = field(repr=False)
    servers: tuple = field(repr=False)

    def summary(self):
        return {"cadastro_publicado_em": self.published_at.isoformat(),
                "sha256_normalizado": self.digest, "regionais": len(self.regionals),
                "servidores": len(self.servers),
                "servidores_sem_data_de_observacao": sum(row[10] is None for row in self.servers)}


def prepare_server_snapshot(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("regionais"), dict):
        raise SnapshotError("Cadastro regional invalido.")
    config = payload.get("configuracao")
    published = _observation(config.get("ultima_atualizacao") if isinstance(config, dict) else None,
                            ZoneInfo(SOURCE_TIMEZONE))
    if published is None:
        raise SnapshotError("Publicacao do cadastro sem horario.")
    safe = {"regionais": {}}
    for code, entry in payload["regionais"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("servidores"), list):
            raise SnapshotError("Lista de servidores invalida.")
        servers = []
        for record in entry["servidores"]:
            if not isinstance(record, dict):
                raise SnapshotError("Servidor invalido.")
            servers.append({key: record.get(key) for key in SERVER_FIELDS})
        safe["regionais"][code] = {"nome": entry.get("nome"), "servidores": servers}
    catalog = build_catalog(json.dumps(safe, ensure_ascii=True).encode(), SOURCE_TIMEZONE,
                            allow_empty_servers=True)
    rows = tuple(sorted(catalog.servers, key=lambda row: row[:2]))
    canonical = json.dumps((published, catalog.regionals, rows),
                           default=lambda value: value.isoformat(), ensure_ascii=True, separators=(",", ":"))
    return ServerSnapshot(published, hashlib.sha256(canonical.encode()).hexdigest(), catalog.regionals, rows)


MARKER_SQL = """SELECT cadastro_publicado_em, conteudo_sha256
    FROM operacional.sincronizacoes_servidores WHERE fonte = 'estrutura_regionais'"""
COUNTS_SQL = """SELECT
    (SELECT count(*) FROM operacional.regionais WHERE presente_no_cadastro),
    (SELECT count(*) FROM operacional.servidores WHERE presente_no_snapshot)"""


def inspect_server_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '10s'")
        _identity(cursor)
        cursor.execute(MARKER_SQL)
        current = cursor.fetchone()
        cursor.execute(COUNTS_SQL)
        counts = cursor.fetchone()
    return {**snapshot.summary(), "modo": "conferencia_sem_gravacao",
            "banco_regionais_no_cadastro": counts[0], "banco_servidores_presentes": counts[1],
            "ultima_publicacao_sincronizada": current[0].isoformat() if current else None,
            "conteudo_ja_sincronizado": bool(current and current[1] == snapshot.digest),
            "publicacao_mais_antiga": bool(current and snapshot.published_at < current[0])}


def write_server_snapshot(connection, snapshot):
    """Caller owns transaction; regionais lock serializes with initial loads/firewalls."""
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute("SET LOCAL lock_timeout = '1s'")
        cursor.execute("SET LOCAL statement_timeout = '10s'")
        _identity(cursor)
        cursor.execute("""LOCK TABLE operacional.regionais, operacional.servidores,
            operacional.sincronizacoes_servidores IN SHARE ROW EXCLUSIVE MODE""")
        cursor.execute(MARKER_SQL)
        current = cursor.fetchone()
        if current and current[1] == snapshot.digest:
            return "sem_alteracoes"
        if current and snapshot.published_at < current[0]:
            return "publicacao_antiga_ignorada"
        if current and snapshot.published_at == current[0]:
            raise SnapshotError("Publicacoes distintas com mesmo horario. Revise a origem.")
        cursor.execute("UPDATE operacional.regionais SET presente_no_cadastro=false WHERE presente_no_cadastro")
        cursor.execute("UPDATE operacional.servidores SET presente_no_snapshot=false WHERE presente_no_snapshot")
        for code, name in snapshot.regionals:
            cursor.execute("""INSERT INTO operacional.regionais(codigo,nome,presente_no_cadastro)
                VALUES (%s,%s,true) ON CONFLICT(codigo) DO UPDATE SET
                nome=COALESCE(EXCLUDED.nome,operacional.regionais.nome), presente_no_cadastro=true""", (code, name))
        for row in snapshot.servers:
            cursor.execute("""INSERT INTO operacional.servidores AS s
                (codigo_regional,id_origem,nome,tipo,ip,modelo,funcao,sistema_operacional,
                 status,ativo,ultima_verificacao,tempo_resposta,arquivo_origem_sha256,
                 presente_no_snapshot,atualizado_no_banco_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,true,CURRENT_TIMESTAMP)
                ON CONFLICT(codigo_regional,id_origem) DO UPDATE SET
                 nome=EXCLUDED.nome,tipo=EXCLUDED.tipo,ip=EXCLUDED.ip,modelo=EXCLUDED.modelo,
                 funcao=EXCLUDED.funcao,sistema_operacional=EXCLUDED.sistema_operacional,
                 ativo=EXCLUDED.ativo, presente_no_snapshot=true,
                 arquivo_origem_sha256=NULL, atualizado_no_banco_em=CURRENT_TIMESTAMP,
                 status=CASE WHEN s.ultima_verificacao IS NULL OR
                     EXCLUDED.ultima_verificacao >= s.ultima_verificacao
                     THEN EXCLUDED.status ELSE s.status END,
                 tempo_resposta=CASE WHEN s.ultima_verificacao IS NULL OR
                     EXCLUDED.ultima_verificacao >= s.ultima_verificacao
                     THEN EXCLUDED.tempo_resposta ELSE s.tempo_resposta END,
                 ultima_verificacao=CASE WHEN s.ultima_verificacao IS NULL OR
                     EXCLUDED.ultima_verificacao >= s.ultima_verificacao
                     THEN EXCLUDED.ultima_verificacao ELSE s.ultima_verificacao END""", row)
        cursor.execute(COUNTS_SQL)
        if cursor.fetchone() != (len(snapshot.regionals), len(snapshot.servers)):
            raise SnapshotError("Contagens divergentes. Publicacao cancelada.")
        cursor.execute("""INSERT INTO operacional.sincronizacoes_servidores
            (fonte,cadastro_publicado_em,conteudo_sha256) VALUES ('estrutura_regionais',%s,%s)
            ON CONFLICT(fonte) DO UPDATE SET cadastro_publicado_em=EXCLUDED.cadastro_publicado_em,
            conteudo_sha256=EXCLUDED.conteudo_sha256,sincronizado_em=CURRENT_TIMESTAMP""",
            (snapshot.published_at, snapshot.digest))
    return "sincronizado"


class ServerShadowWorker(ShadowWorker):
    def _run(self):
        while True:
            snapshot, logger = self.pending.get()
            try:
                if shadow_enabled(CONFIG_PATH):
                    with connect_collector() as connection:
                        write_server_snapshot(connection, snapshot)
            except Exception as exc:
                _safe_warning(logger, "falha_sincronizacao_servidores", exc)
            finally:
                self.pending.task_done()


_worker = ServerShadowWorker()


def enqueue_server_snapshot(payload, source_path, logger):
    if not shadow_enabled(CONFIG_PATH):
        return False
    try:
        if Path(source_path).resolve() != (PROJECT_ROOT / "estrutura_regionais.json").resolve():
            return False
        _worker.submit(prepare_server_snapshot(payload), logger)
        return True
    except Exception as exc:
        _safe_warning(logger, "cadastro_nao_enfileirado", exc)
        return False
