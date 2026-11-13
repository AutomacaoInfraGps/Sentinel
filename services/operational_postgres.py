"""Opt-in shadow persistence of the global firewall cache, not an end-user API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import queue
import re
import threading
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "instance" / "operational-postgres-shadow.json"
SECRET_REFERENCE = "sentinel/postgresql/collector/password"
SOURCE_TIMEZONE = "America/Sao_Paulo"
MISSING = {"", "n/a", "unknown", "-", "none", "null"}


class SnapshotError(ValueError):
    """Fixed diagnostic, never containing source values or credentials."""


@dataclass(frozen=True, repr=False)
class FirewallSnapshot:
    published_at: datetime
    digest: str
    regionals: tuple
    firewalls: tuple
    license_count: int

    def summary(self):
        return {
            "coleta_publicada_em": self.published_at.isoformat(),
            "sha256_normalizado": self.digest,
            "regionais": len(self.regionals), "firewalls": len(self.firewalls),
            "licencas": self.license_count,
        }


def _text(value, maximum, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise SnapshotError("Campo textual invalido.")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise SnapshotError("Campo textual fora do formato permitido.")
    return value or None


def _flag(record, key, *, default=None):
    value = record.get(key, default)
    if value is not None and not isinstance(value, bool):
        raise SnapshotError("Indicador booleano invalido.")
    return value


def _moment(value, zone, *, required=False):
    if value is None or (isinstance(value, str) and value.strip().lower() in MISSING):
        if required:
            raise SnapshotError("Data de publicacao ausente.")
        return None
    if not isinstance(value, str) or len(value.strip()) <= 10:
        raise SnapshotError("Data de coleta invalida.")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if moment.tzinfo is None:
            first = moment.replace(tzinfo=zone, fold=0)
            second = moment.replace(tzinfo=zone, fold=1)
            if first.utcoffset() != second.utcoffset():
                raise ValueError
            moment = first
        return moment.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise SnapshotError("Data invalida ou horario local ambiguo.") from None


def _expiry(value, zone):
    if value is None or (isinstance(value, str) and value.strip().lower() in MISSING):
        return None, None
    if isinstance(value, bool):
        raise SnapshotError("Vencimento invalido.")
    try:
        if isinstance(value, (int, float)) or (
            isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value.strip())
        ):
            stamp = float(value)
            if not math.isfinite(stamp) or stamp < 0:
                raise ValueError
            return (datetime.fromtimestamp(stamp, timezone.utc), None) if stamp else (None, None)
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            return None, date.fromisoformat(value.strip())
        if isinstance(value, str) and re.fullmatch(r"\d{2}/\d{2}/\d{4}", value.strip()):
            return None, datetime.strptime(value.strip(), "%d/%m/%Y").date()
        return _moment(value, zone, required=True), None
    except (ValueError, OverflowError, OSError):
        raise SnapshotError("Vencimento invalido.") from None


def prepare_snapshot(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SnapshotError("Snapshot sem confirmacao de sucesso.")
    regionals = payload.get("firewalls_por_regional")
    if not isinstance(regionals, dict) or not regionals:
        raise SnapshotError("Snapshot regional ausente.")
    if any(not isinstance(code, str) or code != code.strip() for code in regionals):
        raise SnapshotError("Codigo regional invalido.")
    zone = ZoneInfo(SOURCE_TIMEZONE)
    published = _moment(payload.get("atualizado_em"), zone, required=True)
    rows, codes, serials = [], [], set()
    license_count = 0
    for code, records in sorted(regionals.items()):
        code = _text(code, 120, required=True)
        codes.append(code)
        if not isinstance(records, list):
            raise SnapshotError("Lista de firewalls invalida.")
        for record in records:
            if not isinstance(record, dict):
                raise SnapshotError("Firewall invalido.")
            serial = _text(record.get("serial"), 120, required=True).upper()
            if serial.casefold() in MISSING or serial in serials:
                raise SnapshotError("Serial ausente ou duplicado.")
            serials.add(serial)
            observed = _moment(record.get("ultima_verificacao") or record.get("atualizado_em"), zone)
            address = _text(record.get("ip"), 240)
            try:
                address = str(ipaddress.ip_address(address)) if address else None
            except ValueError:
                raise SnapshotError("Endereco de firewall invalido.") from None
            licenses = record.get("licencas")
            if licenses is not None and not isinstance(licenses, list):
                raise SnapshotError("Lista de licencas invalida.")
            license_rows, keys = [], set()
            for item in licenses or []:
                if not isinstance(item, dict):
                    raise SnapshotError("Licenca invalida.")
                name = _text(item.get("nome") or item.get("tipo"), 240, required=True)
                kind = _text(item.get("tipo"), 240)
                key = (name.casefold(), (kind or "").casefold())
                if key in keys:
                    raise SnapshotError("Identidade de licenca duplicada no mesmo firewall.")
                keys.add(key)
                expires_at, expires_on = _expiry(item.get("expiracao"), zone)
                days = item.get("dias_restantes")
                if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not -(2**31) <= days < 2**31):
                    raise SnapshotError("Dias restantes invalidos.")
                previous = _flag(item, "dados_anteriores", default=False)
                previous = previous is True
                last_valid = _moment(item.get("ultima_coleta_valida"), zone)
                license_rows.append((
                    name, kind, _text(item.get("status"), 120), _text(item.get("origem"), 120),
                    expires_at, expires_on, days, last_valid if previous else observed,
                    _flag(item, "notificacao_critica"), _flag(item, "notificacao_expirada"),
                    _flag(item, "status_indisponivel"), previous, last_valid,
                    _text(item.get("status_ultima_coleta_valida"), 120),
                ))
            license_rows.sort(key=lambda row: (row[0], row[1] or ""))
            license_count += len(license_rows)
            rows.append((
                code, serial, _text(record.get("nome") or record.get("hostname"), 240, required=True),
                _text(record.get("hostname"), 240), address,
                _text(record.get("model") or record.get("modelo"), 240),
                _text(record.get("firmware"), 240), observed,
                _text(record.get("status"), 120), _text(record.get("status_disponibilidade"), 120),
                bool(license_rows), tuple(license_rows),
            ))
    if not rows:
        raise SnapshotError("Snapshot vazio nao pode substituir o estado conhecido.")
    rows.sort(key=lambda row: (row[0], row[1]))
    canonical = json.dumps((published, codes, rows), default=lambda value: value.isoformat(), ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return FirewallSnapshot(published, digest, tuple(codes), tuple(rows), license_count)


def connect_collector(*, read_only=False):
    import psycopg
    from core.secret_store import JsonSecretStore

    password = JsonSecretStore().get(SECRET_REFERENCE)
    try:
        return psycopg.connect(
            host="127.0.0.1", port=5433, dbname="sentinel", user="sentinel_collector",
            password=password, connect_timeout=3, application_name="sentinel_firewall_shadow",
            options="-c search_path=pg_catalog" + (" -c default_transaction_read_only=on" if read_only else ""),
        )
    finally:
        password = None


def _identity(cursor):
    cursor.execute("SELECT current_database(), current_user, inet_server_port()")
    if cursor.fetchone() != ("sentinel", "sentinel_collector", 5433):
        raise SnapshotError("Destino SQL divergente.")


def inspect_snapshot(connection, snapshot):
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '10s'")
        _identity(cursor)
        cursor.execute("""SELECT coleta_publicada_em, conteudo_sha256
            FROM operacional.sincronizacoes WHERE fonte = 'firewalls'""")
        current = cursor.fetchone()
        cursor.execute("""SELECT
            (SELECT count(*) FROM operacional.firewalls WHERE presente_no_snapshot),
            (SELECT count(*) FROM operacional.licencas_firewall WHERE presente_no_snapshot)""")
        counts = cursor.fetchone()
        return {
            **snapshot.summary(), "modo": "conferencia_sem_gravacao",
            "banco_firewalls_presentes": counts[0], "banco_licencas_presentes": counts[1],
            "ultima_publicacao_sincronizada": current[0].isoformat() if current else None,
            "conteudo_ja_sincronizado": bool(current and current[1] == snapshot.digest),
            "publicacao_mais_antiga": bool(current and snapshot.published_at < current[0]),
        }


def write_snapshot(connection, snapshot):
    """One transaction owned by the caller, including presence flags and metadata."""
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute("SET LOCAL lock_timeout = '1s'")
        cursor.execute("SET LOCAL statement_timeout = '10s'")
        _identity(cursor)
        cursor.execute("""LOCK TABLE operacional.regionais, operacional.firewalls,
            operacional.licencas_firewall, operacional.sincronizacoes
            IN SHARE ROW EXCLUSIVE MODE""")
        cursor.execute("""SELECT coleta_publicada_em, conteudo_sha256
            FROM operacional.sincronizacoes WHERE fonte = 'firewalls'""")
        current = cursor.fetchone()
        if current and current[1] == snapshot.digest:
            return "sem_alteracoes"
        if current and snapshot.published_at < current[0]:
            return "publicacao_antiga_ignorada"
        for code in snapshot.regionals:
            cursor.execute("""INSERT INTO operacional.regionais (codigo) VALUES (%s)
                ON CONFLICT (codigo) DO NOTHING""", (code,))
        cursor.execute("UPDATE operacional.firewalls SET presente_no_snapshot = false WHERE presente_no_snapshot")
        cursor.execute("UPDATE operacional.licencas_firewall SET presente_no_snapshot = false WHERE presente_no_snapshot")
        for row in snapshot.firewalls:
            cursor.execute("""INSERT INTO operacional.firewalls
                (codigo_regional, serial, nome, hostname, ip, modelo, firmware,
                 ultima_verificacao, status, status_disponibilidade, licencas_informadas, presente_no_snapshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
                ON CONFLICT (serial) DO UPDATE SET
                 codigo_regional=EXCLUDED.codigo_regional, nome=EXCLUDED.nome,
                 hostname=EXCLUDED.hostname, ip=EXCLUDED.ip, modelo=EXCLUDED.modelo,
                 firmware=EXCLUDED.firmware, ultima_verificacao=EXCLUDED.ultima_verificacao,
                 status=EXCLUDED.status, status_disponibilidade=EXCLUDED.status_disponibilidade,
                 licencas_informadas=EXCLUDED.licencas_informadas, presente_no_snapshot=true
                RETURNING id""", row[:11])
            firewall_id = cursor.fetchone()[0]
            for license_row in row[11]:
                cursor.execute("""INSERT INTO operacional.licencas_firewall
                    (firewall_id,nome,tipo,status,origem,expiracao_em,expiracao_data,
                     dias_restantes_coletados,coletado_em,notificacao_critica,notificacao_expirada,
                     status_indisponivel,dados_anteriores,ultima_coleta_valida,status_ultima_coleta_valida,
                     presente_no_snapshot)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
                    ON CONFLICT (firewall_id,nome,tipo) DO UPDATE SET
                     status=EXCLUDED.status, origem=EXCLUDED.origem, expiracao_em=EXCLUDED.expiracao_em,
                     expiracao_data=EXCLUDED.expiracao_data, dias_restantes_coletados=EXCLUDED.dias_restantes_coletados,
                     coletado_em=EXCLUDED.coletado_em, notificacao_critica=EXCLUDED.notificacao_critica,
                     notificacao_expirada=EXCLUDED.notificacao_expirada, status_indisponivel=EXCLUDED.status_indisponivel,
                     dados_anteriores=EXCLUDED.dados_anteriores, ultima_coleta_valida=EXCLUDED.ultima_coleta_valida,
                     status_ultima_coleta_valida=EXCLUDED.status_ultima_coleta_valida, presente_no_snapshot=true""",
                    (firewall_id, *license_row))
        cursor.execute("""SELECT
            (SELECT count(*) FROM operacional.firewalls WHERE presente_no_snapshot),
            (SELECT count(*) FROM operacional.licencas_firewall WHERE presente_no_snapshot)""")
        if cursor.fetchone() != (len(snapshot.firewalls), snapshot.license_count):
            raise SnapshotError("Contagens divergentes. Publicacao cancelada.")
        cursor.execute("""INSERT INTO operacional.sincronizacoes
            (fonte,coleta_publicada_em,conteudo_sha256) VALUES ('firewalls',%s,%s)
            ON CONFLICT (fonte) DO UPDATE SET coleta_publicada_em=EXCLUDED.coleta_publicada_em,
             conteudo_sha256=EXCLUDED.conteudo_sha256, sincronizado_em=CURRENT_TIMESTAMP""",
            (snapshot.published_at, snapshot.digest))
    return "sincronizado"


def _safe_warning(logger, code, error):
    state = getattr(error, "sqlstate", None)
    state = state if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state) else "indisponivel"
    try:
        logger.warning("PostgreSQL paralelo: %s; SQLSTATE=%s. Cache original preservado.", code, state)
    except Exception:
        pass


def shadow_enabled(path=None):
    try:
        with Path(path or CONFIG_PATH).open(encoding="utf-8-sig") as stream:
            config = json.load(stream)
        return isinstance(config, dict) and config.get("enabled") is True
    except (OSError, ValueError, UnicodeError):
        return False


class ShadowWorker:
    def __init__(self):
        self.pending = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.started = False

    def submit(self, snapshot, logger):
        with self.lock:
            if not self.started:
                threading.Thread(target=self._run, name="sentinel-postgres-shadow", daemon=True).start()
                self.started = True
            candidate = (snapshot, logger)
            try:
                pending = self.pending.get_nowait()
                self.pending.task_done()
                if pending[0].published_at > snapshot.published_at:
                    candidate = pending
            except queue.Empty:
                pass
            self.pending.put_nowait(candidate)

    def _run(self):
        while True:
            snapshot, logger = self.pending.get()
            try:
                if shadow_enabled():
                    with connect_collector() as connection:
                        write_snapshot(connection, snapshot)
            except Exception as exc:
                _safe_warning(logger, "falha_sincronizacao", exc)
            finally:
                self.pending.task_done()


_worker = ShadowWorker()


def enqueue_firewall_snapshot(payload, logger):
    if not shadow_enabled():
        return False
    try:
        _worker.submit(prepare_snapshot(payload), logger)
        return True
    except Exception as exc:
        _safe_warning(logger, "snapshot_nao_enfileirado", exc)
        return False
