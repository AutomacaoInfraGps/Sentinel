"""Bootstrap an EMPTY Sentinel operational database; simulation is the default."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import warnings
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.audit_firewall_cache import (  # noqa: E402
    AuditError, MISSING, _expiry_kind, audit_payload,
)


class ImportErrorSafe(ValueError):
    """Fixed diagnostic without source data, SQL parameters or passwords."""


@dataclass
class DatabaseProgress:
    phase: str = "conexao"


def _connection_error_hint(error, state):
    # libpq connection failures often lack SQLSTATE. Classify in memory only:
    # its free-form message may contain connection details and is never printed.
    message = str(error).casefold()
    if state == "28P01" or any(text in message for text in (
        "password authentication failed", "autenticacao por senha falhou",
        "autentica\u00e7\u00e3o por senha falhou",
    )):
        return "AUTENTICACAO_POR_SENHA_RECUSADA"
    patterns = (
        ("SENHA_NAO_FORNECIDA", ("no password supplied", "nenhuma senha foi fornecida")),
        ("REGRA_HBA_RECUSOU_CONEXAO", ("no pg_hba.conf entry", "nenhuma entrada no pg_hba.conf")),
        ("CONEXAO_RECUSADA", ("connection refused", "actively refused", "recusou ativamente", "conex\u00e3o recusada")),
        ("TEMPO_LIMITE_DE_CONEXAO", ("timeout expired", "connection timed out", "tempo limite")),
        ("OPCAO_DE_CONEXAO_OU_SERVIDOR_INVALIDA", (
            "unrecognized configuration parameter", "invalid command-line argument",
            "invalid value for parameter", "invalid connection option",
            "par\u00e2metro de configura\u00e7\u00e3o desconhecido",
        )),
        ("FALHA_TLS_OU_CERTIFICADO", ("certificate verify failed", "ssl error", "sslmode")),
        ("FALHA_AUTENTICACAO_INTEGRADA", ("gssapi", "sspi", "gss encryption")),
        ("BIBLIOTECA_OU_PROTOCOLO_INCOMPATIVEL", (
            "authentication method", "requires libpq", "unsupported protocol",
        )),
    )
    for hint, fragments in patterns:
        if any(fragment in message for fragment in fragments):
            return hint
    return "CAUSA_AINDA_NAO_CLASSIFICADA"


def _database_error(phase, error):
    allowed_types = {
        "OperationalError", "InterfaceError", "ProgrammingError", "IntegrityError",
        "DataError", "InternalError", "NotSupportedError", "DatabaseError",
        "InvalidPassword", "InsufficientPrivilege", "UndefinedTable", "UndefinedColumn",
        "LockNotAvailable", "InvalidTextRepresentation", "UniqueViolation",
        "ForeignKeyViolation", "CheckViolation", "NotNullViolation",
        "TypeError", "ValueError", "RuntimeError", "AttributeError",
    }
    category = type(error).__name__
    if category not in allowed_types:
        category = "ErroDeBancoOuDriver"
    state = getattr(error, "sqlstate", None)
    if not isinstance(state, str) or not re.fullmatch(r"[0-9A-Z]{5}", state):
        state = "indisponivel"
    hint = f" Indicio: {_connection_error_hint(error, state)}." if phase == "conexao" else ""
    return ImportErrorSafe(
        f"Falha na etapa {phase}. Tipo: {category}. SQLSTATE: {state}.{hint} "
        "Confira as contagens antes de repetir uma gravacao. Mensagem e valores foram omitidos."
    )


@dataclass(frozen=True)
class ImportPlan:
    sha256: str
    source_timezone: str
    summary: dict
    regionals: tuple = field(repr=False)
    firewalls: tuple = field(repr=False)


def _optional_text(value):
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ImportErrorSafe("Campo textual nao pode ser convertido com seguranca.")
    return value.strip() or None


def _localize(moment, source_zone):
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc)
    # Reject historical DST gaps/folds instead of silently choosing an instant.
    first = moment.replace(tzinfo=source_zone, fold=0)
    second = moment.replace(tzinfo=source_zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ImportErrorSafe("Horario local ambiguo ou inexistente. Revise o cache antes de importar.")
    utc = first.astimezone(timezone.utc)
    if utc.astimezone(source_zone).replace(tzinfo=None) != moment:
        raise ImportErrorSafe("Horario local inexistente. Revise o cache antes de importar.")
    return utc


def _observation(value, source_zone):
    if value is None or (isinstance(value, str) and value.strip().lower() in MISSING):
        return None
    if not isinstance(value, str) or len(value.strip()) <= 10:
        raise ImportErrorSafe("Data de coleta nao pode ser convertida com seguranca.")
    try:
        return _localize(datetime.fromisoformat(value.strip().replace("Z", "+00:00")), source_zone)
    except (ValueError, OverflowError):
        raise ImportErrorSafe("Data de coleta nao pode ser convertida com seguranca.") from None


def _expiry(value, source_zone):
    kind = _expiry_kind(value)
    if kind == "missing":
        return None, None
    if kind == "invalid":
        raise ImportErrorSafe("Vencimento invalido. Importacao bloqueada.")
    if kind == "date":
        text = value.strip()
        return None, date.fromisoformat(text) if "-" in text else datetime.strptime(text, "%d/%m/%Y").date()
    try:
        if isinstance(value, (int, float)) or str(value).strip().replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(value), timezone.utc), None
        return _localize(datetime.fromisoformat(value.strip().replace("Z", "+00:00")), source_zone), None
    except (ValueError, OverflowError, OSError):
        raise ImportErrorSafe("Vencimento nao pode ser convertido com seguranca.") from None


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ImportErrorSafe("JSON com chaves duplicadas. Importacao bloqueada.")
        result[key] = value
    return result


def build_plan(raw, source_timezone):
    try:
        source_zone = ZoneInfo(source_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ImportErrorSafe("Fuso IANA indisponivel. Confira o nome e a instalacao de tzdata.") from None
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except (UnicodeError, json.JSONDecodeError):
        raise ImportErrorSafe("Nao foi possivel ler o cache JSON.") from None
    try:
        audit = audit_payload(payload)
    except AuditError:
        raise ImportErrorSafe("Formato do cache invalido. Execute o diagnostico primeiro.") from None
    if not audit["estrutura_valida"]:
        raise ImportErrorSafe("Cache com erros estruturais. Execute o diagnostico primeiro.")
    regionals, firewalls = [], []
    for code, records in sorted(payload["firewalls_por_regional"].items()):
        regionals.append(_optional_text(code))
        for record in records:
            collected = _observation(record.get("ultima_verificacao") or record.get("atualizado_em"), source_zone)
            address = record.get("ip")
            licenses = []
            for license_record in record.get("licencas") or []:
                expires_at, expires_on = _expiry(license_record.get("expiracao"), source_zone)
                licenses.append((
                    _optional_text(license_record.get("nome") or license_record.get("tipo")),
                    _optional_text(license_record.get("tipo")),
                    _optional_text(license_record.get("status")),
                    _optional_text(license_record.get("origem")),
                    expires_at, expires_on,
                    license_record.get("dias_restantes"), collected,
                    license_record.get("notificacao_critica"),
                    license_record.get("notificacao_expirada"),
                    license_record.get("status_indisponivel"),
                ))
            firewalls.append((
                code, _optional_text(record["serial"]).upper(),
                _optional_text(record.get("nome") or record.get("hostname")),
                _optional_text(record.get("hostname")),
                str(ipaddress.ip_address(address.strip())) if address else None,
                _optional_text(record.get("model") or record.get("modelo")),
                _optional_text(record.get("firmware")), tuple(licenses),
            ))
    digest = hashlib.sha256(raw).hexdigest()
    summary = {
        "modo": "simulacao_sem_conexao_ao_banco",
        "sha256_cache": digest,
        "fuso_origem": source_timezone,
        "datas_com_horario_convertidas_para": "UTC",
        "regionais": len(regionals),
        "firewalls": len(firewalls),
        "licencas": audit["licencas"],
        "licencas_sem_vencimento": audit["vencimentos_ausentes"],
        "coletas_sem_data": audit["coletas_ausentes"],
        "avisos": audit["avisos"],
    }
    return ImportPlan(digest, source_timezone, summary, tuple(regionals), tuple(firewalls))


COUNTS_SQL = """SELECT
    (SELECT count(*) FROM operacional.regionais),
    (SELECT count(*) FROM operacional.firewalls),
    (SELECT count(*) FROM operacional.licencas_firewall)"""


def write_empty_database(connection, plan, *, progress=None):
    """Caller owns the commit/rollback context; reject any preexisting records."""
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = "configuracao_transacao"
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '60s'")
        progress.phase = "validacao_destino"
        cursor.execute("SELECT current_database(), current_user, inet_server_port()")
        if cursor.fetchone() != ("sentinel", "sentinel_collector", 5433):
            raise ImportErrorSafe("Identidade ou instancia PostgreSQL divergente. Importacao bloqueada.")
        progress.phase = "bloqueio_tabelas"
        cursor.execute("""LOCK TABLE operacional.regionais, operacional.firewalls,
            operacional.licencas_firewall IN SHARE ROW EXCLUSIVE MODE""")
        progress.phase = "contagem_inicial"
        cursor.execute(COUNTS_SQL)
        if cursor.fetchone() != (0, 0, 0):
            raise ImportErrorSafe("As tabelas ja contem dados. Este importador so aceita a carga inicial vazia.")
        for code in plan.regionals:
            progress.phase = "insercao_regionais"
            cursor.execute("INSERT INTO operacional.regionais (codigo) VALUES (%s)", (code,))
        for firewall in plan.firewalls:
            progress.phase = "insercao_firewalls"
            cursor.execute("""INSERT INTO operacional.firewalls
                (codigo_regional, serial, nome, hostname, ip, modelo, firmware)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""", firewall[:7])
            firewall_id = cursor.fetchone()[0]
            for license_values in firewall[7]:
                progress.phase = "insercao_licencas"
                cursor.execute("""INSERT INTO operacional.licencas_firewall
                    (firewall_id, nome, tipo, status, origem, expiracao_em, expiracao_data,
                     dias_restantes_coletados, coletado_em, notificacao_critica,
                     notificacao_expirada, status_indisponivel)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (firewall_id, *license_values))
        progress.phase = "contagem_final"
        cursor.execute(COUNTS_SQL)
        expected = (len(plan.regionals), len(plan.firewalls), plan.summary["licencas"])
        if cursor.fetchone() != expected:
            raise ImportErrorSafe("Contagens divergentes. A transacao deve ser revertida.")


def inspect_database(connection, progress):
    """Read-only diagnostics: no inserts, DDL or explicit table locks."""
    with connection.cursor() as cursor:
        progress.phase = "conferencia_somente_leitura"
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '15s'")
        cursor.execute("SELECT current_database(), current_user, inet_server_port()")
        if cursor.fetchone() != ("sentinel", "sentinel_collector", 5433):
            raise ImportErrorSafe("Identidade ou instancia PostgreSQL divergente. Conferencia bloqueada.")
        progress.phase = "conferencia_contagens"
        cursor.execute(COUNTS_SQL)
        counts = cursor.fetchone()
        progress.phase = "conferencia_permissoes"
        cursor.execute("""SELECT
            (SELECT bool_and(has_table_privilege(current_user, 'operacional.regionais', p))
                FROM unnest(ARRAY['SELECT','INSERT','UPDATE']) AS privileges(p)),
            (SELECT bool_and(has_table_privilege(current_user, 'operacional.firewalls', p))
                FROM unnest(ARRAY['SELECT','INSERT','UPDATE']) AS privileges(p)),
            (SELECT bool_and(has_table_privilege(current_user, 'operacional.licencas_firewall', p))
                FROM unnest(ARRAY['SELECT','INSERT','UPDATE']) AS privileges(p)),
            has_sequence_privilege(current_user, 'operacional.firewalls_id_seq', 'USAGE'),
            has_sequence_privilege(current_user, 'operacional.licencas_firewall_id_seq', 'USAGE')""")
        permissions = cursor.fetchone()
        return {
            "regionais": counts[0], "firewalls": counts[1], "licencas": counts[2],
            "tabelas_vazias": counts == (0, 0, 0),
            "permissoes": dict(zip((
                "regionais_select_insert_update", "firewalls_select_insert_update",
                "licencas_select_insert_update", "sequencia_firewalls_usage",
                "sequencia_licencas_usage",
            ), permissions)),
        }


def _read_password(*, from_stdin=False):
    if from_stdin:
        # Explicit diagnostic input from a parent process, never from argv/env.
        raw = sys.stdin.buffer.read(65537)
        try:
            if len(raw) > 65536:
                raise ValueError
            password = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(password, str) or not password or "\x00" in password:
                raise ValueError
            return password
        except (ValueError, UnicodeError):
            raise ImportErrorSafe("Entrada segura invalida. Nao houve conexao ao banco.") from None
    # Never fall back to echoing a password on terminals without hidden input.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Senha SQL de sentinel_collector: ")
    if not password:
        raise ImportErrorSafe("Senha vazia. Nao houve conexao ao banco.")
    return password


def apply_plan(plan, *, check_only=False, password_from_stdin=False):
    progress = DatabaseProgress()
    try:
        import psycopg
    except ImportError:
        raise ImportErrorSafe("Driver psycopg ausente. Nao houve conexao ao banco.") from None
    password = _read_password(from_stdin=password_from_stdin)
    try:
        with psycopg.connect(
            host="127.0.0.1", port=5433, dbname="sentinel",
            user="sentinel_collector", password=password, connect_timeout=10,
            application_name="sentinel_initial_firewall_import",
            options="-c search_path=pg_catalog" + (" -c default_transaction_read_only=on" if check_only else ""),
        ) as connection:
            if check_only:
                result = inspect_database(connection, progress)
            else:
                write_empty_database(connection, plan, progress=progress)
                result = None
            progress.phase = "encerramento_leitura" if check_only else "commit"
        return result
    except ImportErrorSafe:
        raise
    except Exception as exc:
        raise _database_error(progress.phase, exc) from None
    finally:
        password = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=PROJECT_ROOT / "output" / "dashboard_firewalls_cache.json")
    parser.add_argument("--source-timezone", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Grava somente em tabelas vazias.")
    mode.add_argument("--check-database", action="store_true", help="Confere conexao, contagens e permissoes sem gravar.")
    parser.add_argument("--password-stdin", action="store_true", help="Com --check-database ou --apply: recebe senha JSON UTF-8 por pipe.")
    parser.add_argument("--expected-sha256", help="Hash exato exibido pela simulacao revisada.")
    args = parser.parse_args(argv)
    try:
        if args.password_stdin and not (args.check_database or args.apply):
            raise ImportErrorSafe("--password-stdin exige --check-database ou --apply.")
        if args.apply and not args.expected_sha256:
            raise ImportErrorSafe("A gravacao exige --expected-sha256 da simulacao revisada.")
        plan = build_plan(args.cache.read_bytes(), args.source_timezone)
        if args.expected_sha256 and args.expected_sha256.lower() != plan.sha256:
            raise ImportErrorSafe("O cache mudou desde a simulacao. Refaca a conferencia antes de gravar.")
        if args.apply or args.check_database:
            if os.environ.get("COMPUTERNAME", "").upper() != "RIGEL":
                raise ImportErrorSafe("A carga inicial deve ser executada somente no Rigel.")
            if args.check_database:
                if args.password_stdin:
                    database_check = apply_plan(plan, check_only=True, password_from_stdin=True)
                else:
                    database_check = apply_plan(plan, check_only=True)
            elif args.password_stdin:
                apply_plan(plan, password_from_stdin=True)
            else:
                apply_plan(plan)
        result = dict(plan.summary)
        if args.apply:
            result["modo"] = "carga_inicial_confirmada"
        elif args.check_database:
            result["modo"] = "conferencia_banco_somente_leitura"
            result["banco"] = database_check
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except OSError:
        print("Falha ao ler o cache ou acessar o recurso solicitado.", file=sys.stderr)
    except (getpass.GetPassWarning, EOFError):
        print("Terminal sem entrada segura para senha. Operacao cancelada.", file=sys.stderr)
    except KeyboardInterrupt:
        print("Operacao interrompida. Confira o banco antes de repetir uma gravacao.", file=sys.stderr)
    except Exception:
        # Database diagnostics can contain bound values; do not print them.
        print("Falha na operacao. Se iniciou gravacao, confira o banco antes de repetir. Dados de erro foram omitidos por seguranca.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
