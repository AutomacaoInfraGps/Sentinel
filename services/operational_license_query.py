"""Read-only license projection; callers must supply a server-authenticated scope."""

from collections import Counter
from datetime import datetime, timezone

from regional_access import normalize_regional_code


class LicenseQueryError(RuntimeError):
    """Source failure, never an empty successful answer."""


STATUSES = {"valid", "unknown", "unavailable", "expired", "expiring"}
COLUMNS = (
    "regional", "firewall", "firewall_serial", "name", "source_status",
    "expires_at", "expires_on", "days_remaining", "collected_at",
    "unavailable", "expired", "expiring", "previous_data", "last_valid_at",
)


def _iso(value):
    return value.isoformat() if value is not None else None


def _project(row):
    item = dict(zip(COLUMNS, row))
    known = item["expires_at"] is not None or item["expires_on"] is not None
    unavailable = item.pop("unavailable") is True or str(item.pop("source_status") or "").lower() in {
        "unavailable", "indisponivel", "offline",
    }
    expired, expiring = item.pop("expired"), item.pop("expiring")
    item["status"] = ("unavailable" if unavailable else "expired" if expired
                      else "expiring" if expiring else "valid" if known else "unknown")
    if unavailable or not known:
        item["days_remaining"] = None
    for key in ("expires_at", "expires_on", "collected_at", "last_valid_at"):
        item[key] = _iso(item[key])
    return item


def query_postgres_licenses(connection, *, allowed_regionals, regional="",
                            expires_within_days=None, status="", limit=20, offset=0,
                            now=None):
    """Use a new caller-owned transaction. No credentials or user scope are inferred.

    SQL reads only authorized current rows. Filtering and complete summaries precede
    pagination. Nothing here grants authorization to the supplied list of codes.
    """
    if (not isinstance(allowed_regionals, (list, tuple, set, frozenset))
            or len(allowed_regionals) > 200
            or any(not isinstance(code, str) or not code.strip() or len(code) > 120
                   for code in allowed_regionals)):
        raise ValueError("Escopo regional invalido.")
    allowed = sorted({normalize_regional_code(code) for code in allowed_regionals})
    if not isinstance(regional, str) or len(regional) > 120:
        raise ValueError("Regional invalida.")
    selected = normalize_regional_code(regional) if regional else ""
    if selected and selected not in allowed and "REG_" + selected in allowed:
        selected = "REG_" + selected
    if selected and selected not in allowed:
        raise PermissionError("Regional nao encontrada no escopo autorizado.")
    if (type(limit) is not int or not 1 <= limit <= 50
            or type(offset) is not int or not 0 <= offset <= 10000):
        raise ValueError("Paginacao invalida.")
    if expires_within_days is not None and (
        type(expires_within_days) is not int or not 0 <= expires_within_days <= 3660
    ):
        raise ValueError("Prazo de vencimento invalido.")
    if not isinstance(status, str) or (status and status not in STATUSES):
        raise ValueError("Estado invalido.")
    scope = [selected] if selected else allowed
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("Horario de referencia exige fuso.")
    published, rows, missing_details = None, [], 0
    if scope:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute("SELECT current_database(), inet_server_port()")
                if cursor.fetchone() != ("sentinel", 5433):
                    raise LicenseQueryError("Instancia operacional divergente.")
                cursor.execute("SELECT coleta_publicada_em FROM operacional.sincronizacoes WHERE fonte = 'firewalls'")
                marker = cursor.fetchone()
                if not marker or marker[0] is None:
                    raise LicenseQueryError("Publicacao operacional indisponivel.")
                published = marker[0]
                cursor.execute("""
                    SELECT count(*) FROM operacional.firewalls f
                    WHERE f.codigo_regional = ANY(%s) AND f.presente_no_snapshot
                      AND (NOT f.licencas_informadas OR NOT EXISTS (
                          SELECT 1 FROM operacional.licencas_firewall l
                          WHERE l.firewall_id = f.id AND l.presente_no_snapshot))
                """, (scope,))
                missing_details = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT f.codigo_regional, f.nome, f.serial, l.nome, l.status,
                           l.expiracao_em, l.expiracao_data, l.dias_restantes_coletados,
                           l.coletado_em, l.status_indisponivel, l.notificacao_expirada,
                           l.notificacao_critica, l.dados_anteriores, l.ultima_coleta_valida
                    FROM operacional.licencas_firewall l
                    JOIN operacional.firewalls f ON f.id = l.firewall_id
                    WHERE f.codigo_regional = ANY(%s)
                      AND f.presente_no_snapshot AND l.presente_no_snapshot
                """, (scope,))
                rows = cursor.fetchall()
        except LicenseQueryError:
            raise
        except Exception:
            raise LicenseQueryError("Falha na leitura operacional PostgreSQL.") from None
    records = [_project(row) for row in rows]
    # Defensive check also rejects malformed/mock sources, never expands the SQL scope.
    if any(item["regional"] not in scope for item in records):
        raise LicenseQueryError("Escopo divergente na fonte operacional.")
    gaps = Counter()
    if missing_details:
        gaps["firewalls_without_license_details"] = missing_details
    for item in records:
        if item["days_remaining"] is None:
            gaps["days_remaining_unavailable"] += 1
        if item["previous_data"]:
            gaps["previous_data"] += 1
        if item["collected_at"] is None:
            gaps["collection_time_unavailable"] += 1
    records = [item for item in records
               if (not status or item["status"] == status)
               and (expires_within_days is None or (
                   item["days_remaining"] is not None
                   and 0 <= item["days_remaining"] <= expires_within_days))]
    records.sort(key=lambda item: (item["days_remaining"] is None,
                                  item["days_remaining"] or 0,
                                  item["regional"], item["firewall_serial"], item["name"]))
    age = (reference - published).total_seconds() if published else None
    visible = records[offset:offset + limit]
    return {
        "source": "sentinel_operational_postgres", "resource": "licenses",
        "updated_at": _iso(published), "age_seconds": age,
        "fresh": age is not None and 0 <= age <= 300 and not gaps,
        "summary": {"records": len(records),
                    "firewalls": len({item["firewall_serial"] for item in records}),
                    "regionals": len({item["regional"] for item in records}),
                    "by_status": dict(Counter(item["status"] for item in records))},
        "records": visible, "offset": offset, "limit": limit,
        "next_offset": offset + len(visible) if offset + len(visible) < len(records) else None,
        "data_gaps": dict(gaps),
    }
