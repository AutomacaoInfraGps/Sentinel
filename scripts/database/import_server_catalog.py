"""Bootstrap server catalog only; no changes to collectors or firewall/license rows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import (
    DatabaseProgress, ImportErrorSafe, _database_error, _observation, _unique_keys,
)


@dataclass(frozen=True)
class ServerCatalog:
    digest: str
    source_timezone: str
    regionals: tuple = field(repr=False)
    servers: tuple = field(repr=False)

    def summary(self):
        return {"sha256_arquivo": self.digest, "fuso_origem": self.source_timezone,
                "regionais": len(self.regionals), "servidores": len(self.servers),
                "servidores_sem_data_de_observacao": sum(row[10] is None for row in self.servers),
                "sincronizacao_automatica_servidores": False}


def _text(value, length=240, *, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str) or "\x00" in value or len(value) > length:
        raise ImportErrorSafe("Campo textual invalido no cadastro.")
    value = value.strip()
    if required and not value:
        raise ImportErrorSafe("Identidade ou nome ausente no cadastro.")
    return value or None


def build_catalog(raw, source_timezone):
    try:
        zone = ZoneInfo(source_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ImportErrorSafe("Fuso IANA indisponivel. Confira tzdata.") from None
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError):
        raise ImportErrorSafe("JSON de cadastro invalido ou com chaves duplicadas.") from None
    entries = payload.get("regionais") if isinstance(payload, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise ImportErrorSafe("Cadastro regional ausente ou vazio.")
    regionals, servers, identities, codes = [], [], set(), set()
    for code, entry in sorted(entries.items()):
        canonical = _text(code, 120, required=True)
        if code != canonical or canonical != canonical.upper() or canonical in codes:
            raise ImportErrorSafe("Codigo regional invalido ou duplicado.")
        codes.add(canonical)
        if not isinstance(entry, dict) or not isinstance(entry.get("servidores"), list):
            raise ImportErrorSafe("Lista de servidores ausente ou invalida.")
        regionals.append((canonical, _text(entry.get("nome"))))
        for record in entry["servidores"]:
            if not isinstance(record, dict):
                raise ImportErrorSafe("Registro de servidor invalido.")
            source_id = _text(record.get("id"), required=True)
            key = (canonical, source_id.casefold())
            if key in identities:
                raise ImportErrorSafe("Identidade de servidor duplicada na regional.")
            identities.add(key)
            address = _text(record.get("ip"), 120)
            try:
                address = str(ipaddress.ip_address(address)) if address else None
            except ValueError:
                raise ImportErrorSafe("Endereco de servidor invalido.") from None
            active = record.get("ativo")
            if active is not None and type(active) is not bool:
                raise ImportErrorSafe("Indicador ativo invalido.")
            response = record.get("tempo_resposta")
            if response is not None and (type(response) not in (int, float)
                                         or not math.isfinite(response) or response < 0):
                raise ImportErrorSafe("Tempo de resposta invalido.")
            servers.append((canonical, source_id, _text(record.get("nome"), required=True),
                            _text(record.get("tipo"), 120), address,
                            _text(record.get("modelo")), _text(record.get("funcao")),
                            _text(record.get("sistema_operacional")), _text(record.get("status"), 120),
                            active, _observation(record.get("ultima_verificacao"), zone), response))
    if not servers:
        raise ImportErrorSafe("Cadastro sem servidores. Carga bloqueada.")
    return ServerCatalog(hashlib.sha256(raw).hexdigest(), source_timezone,
                         tuple(regionals), tuple(servers))


def _identity(cursor):
    cursor.execute("SELECT current_database(), current_user, inet_server_port()")
    if cursor.fetchone() != ("sentinel", "sentinel_collector", 5433):
        raise ImportErrorSafe("Instancia ou identidade SQL divergente.")


def inspect_catalog(connection):
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '5s'")
        _identity(cursor)
        cursor.execute("SELECT (SELECT count(*) FROM operacional.regionais), "
                       "(SELECT count(*) FROM operacional.servidores)")
        regionals, servers = cursor.fetchone()
        return {"regionais_existentes": regionals, "servidores_existentes": servers,
                "tabela_servidores_vazia": servers == 0}


def write_catalog(connection, catalog, *, progress=None):
    """Caller owns commit/rollback. Refuse a populated server table."""
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = "configuracao_transacao"
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '30s'")
        progress.phase = "validacao_destino"
        _identity(cursor)
        progress.phase = "bloqueio_tabelas"
        # All catalog importers serialize on regionais, where collector has UPDATE.
        # INSERT on servidores permits ROW EXCLUSIVE, not SHARE ROW EXCLUSIVE.
        cursor.execute("LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE")
        cursor.execute("LOCK TABLE operacional.servidores IN ROW EXCLUSIVE MODE")
        progress.phase = "contagem_inicial"
        cursor.execute("SELECT count(*) FROM operacional.servidores")
        if cursor.fetchone() != (0,):
            raise ImportErrorSafe("Servidores ja cadastrados. Nao repetir esta carga inicial.")
        for code, name in catalog.regionals:
            progress.phase = "insercao_regionais"
            cursor.execute("""INSERT INTO operacional.regionais(codigo,nome) VALUES (%s,%s)
                ON CONFLICT(codigo) DO UPDATE
                SET nome=COALESCE(operacional.regionais.nome, EXCLUDED.nome)""", (code, name))
        for server in catalog.servers:
            progress.phase = "insercao_servidores"
            cursor.execute("""INSERT INTO operacional.servidores
                (codigo_regional,id_origem,nome,tipo,ip,modelo,funcao,sistema_operacional,
                 status,ativo,ultima_verificacao,tempo_resposta,arquivo_origem_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (*server, catalog.digest))
        progress.phase = "contagem_final"
        cursor.execute("SELECT count(*) FROM operacional.servidores")
        if cursor.fetchone() != (len(catalog.servers),):
            raise ImportErrorSafe("Contagem de servidores divergente. Reverta a transacao.")
        cursor.execute("SELECT count(*) FROM operacional.regionais WHERE codigo = ANY(%s)",
                       ([row[0] for row in catalog.regionals],))
        if cursor.fetchone() != (len(catalog.regionals),):
            raise ImportErrorSafe("Contagem de regionais divergente. Reverta a transacao.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "estrutura_regionais.json")
    parser.add_argument("--source-timezone", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-database", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase="leitura_origem")
    try:
        catalog = build_catalog(args.source.read_bytes(), args.source_timezone)
        result = {"modo": "simulacao_sem_conexao_ao_banco", **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get("COMPUTERNAME", "").upper() != "RIGEL":
                raise ImportErrorSafe("Execute a operacao de banco somente no Rigel.")
            if args.apply and args.expected_sha256 != catalog.digest:
                raise ImportErrorSafe("Gravacao exige o hash exato da simulacao revisada.")
            from services.operational_postgres import connect_collector
            progress.phase = "conexao"
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_catalog(connection, catalog, progress=progress)
                    result["modo"] = "carga_inicial_servidores_confirmada"
                else:
                    progress.phase = "conferencia_somente_leitura"
                    result["banco"] = inspect_catalog(connection)
                    result["modo"] = "conferencia_somente_leitura"
                progress.phase = "finalizacao_transacao"
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(progress.phase, exc)), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
