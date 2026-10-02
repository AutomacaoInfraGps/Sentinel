from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .persistence import (
    CURRENT_SCHEMA_VERSION,
    CURRENT_SNAPSHOT_VERSION,
    _ensure_local_database_path,
)


@dataclass(frozen=True)
class SentinelAlert:
    """Projeção sanitizada de um alerta para consumidores somente leitura."""

    notification_id: str
    alert_id: str
    severity: str
    title: str
    message: str
    action: str
    group_name: str
    member_label: str
    actor_label: str
    source_computer: str
    event_id: int
    event_record_id: int
    occurred_at_utc: str
    received_at_utc: str


@dataclass(frozen=True)
class SentinelAlertStatus:
    schema_version: int
    database_mode: str
    events: int
    pending_deliveries: int
    failed_deliveries: int
    open_occurrences: int
    latest_checkpoint_at_utc: str | None


class SentinelAlertReader:
    """Acesso SQLite estritamente somente leitura para o front do Sentinel."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve(strict=False)
        _ensure_local_database_path(self.database_path)
        if not self.database_path.is_file():
            raise ValueError(f"Banco AlertAD não encontrado: {self.database_path}")
        try:
            links = int(self.database_path.stat().st_nlink)
        except OSError as exc:
            raise ValueError("Não foi possível validar o banco AlertAD") from exc
        if links != 1:
            raise ValueError("Banco AlertAD com identidade física ambígua")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{self.database_path.as_uri()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != CURRENT_SCHEMA_VERSION:
            connection.close()
            raise RuntimeError(
                f"Schema AlertAD incompatível: {version}; esperado: "
                f"{CURRENT_SCHEMA_VERSION}"
            )
        return connection

    @staticmethod
    def _member_label(row: sqlite3.Row) -> str:
        account = str(row["directory_account_name"] or "").strip()
        domain = str(row["directory_domain_name"] or "").strip()
        if account:
            return f"{domain}\\{account}" if domain else account
        member_name = str(row["member_name"] or "").strip()
        if member_name and member_name != "-":
            return member_name
        return str(row["member_sid"] or "").strip()

    @staticmethod
    def _actor_label(row: sqlite3.Row) -> str:
        name = str(row["subject_user_name"] or "").strip()
        domain = str(row["subject_domain_name"] or "").strip()
        if name:
            return f"{domain}\\{name}" if domain else name
        sid = str(row["subject_user_sid"] or "").strip()
        return sid or "Não informado"

    def list_recent(self, *, limit: int = 100) -> tuple[SentinelAlert, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit deve estar entre 1 e 500")

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT
                    event_key, event_id, action, event_record_id,
                    source_computer, time_created_utc, target_user_name,
                    member_sid, member_name, subject_user_sid,
                    subject_user_name, subject_domain_name, alert_message,
                    directory_account_name, directory_domain_name,
                    received_at_utc
                FROM events
                WHERE snapshot_version = ?
                  AND alert_message IS NOT NULL
                  AND trim(alert_message) <> ''
                ORDER BY time_created_utc DESC, event_key DESC
                LIMIT ?
                """,
                (CURRENT_SNAPSHOT_VERSION, limit),
            ).fetchall()
        finally:
            connection.close()

        alerts = []
        for row in rows:
            event_key = str(row["event_key"])
            action = str(row["action"] or "")
            if action not in {"add", "remove"}:
                raise RuntimeError("Snapshot AlertAD contém ação inválida")
            title = {
                "add": "Usuário adicionado a grupo crítico",
                "remove": "Usuário removido de grupo crítico",
            }[action]
            alerts.append(
                SentinelAlert(
                    notification_id=f"alertad:{event_key}",
                    alert_id=event_key[:12],
                    severity="critical",
                    title=title,
                    message=str(row["alert_message"]),
                    action=action,
                    group_name=str(row["target_user_name"]),
                    member_label=self._member_label(row),
                    actor_label=self._actor_label(row),
                    source_computer=str(row["source_computer"]),
                    event_id=int(row["event_id"]),
                    event_record_id=int(row["event_record_id"]),
                    occurred_at_utc=str(row["time_created_utc"]),
                    received_at_utc=str(row["received_at_utc"]),
                )
            )
        return tuple(alerts)

    def status(self) -> SentinelAlertStatus:
        connection = self._connect()
        try:
            mode_row = connection.execute(
                "SELECT value FROM runtime_metadata WHERE key = 'database_mode'"
            ).fetchone()
            if mode_row is None:
                raise RuntimeError("Modo do banco AlertAD não encontrado")
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM events) AS events,
                    (SELECT count(*) FROM deliveries WHERE status = 'pending')
                        AS pending_deliveries,
                    (SELECT count(*) FROM deliveries WHERE status = 'failed')
                        AS failed_deliveries,
                    (SELECT count(*) FROM operational_occurrences
                        WHERE resolved_at_utc IS NULL) AS open_occurrences,
                    (SELECT max(updated_at_utc) FROM collection_checkpoints)
                        AS latest_checkpoint_at_utc
                """
            ).fetchone()
        finally:
            connection.close()
        return SentinelAlertStatus(
            schema_version=CURRENT_SCHEMA_VERSION,
            database_mode=str(mode_row["value"]),
            events=int(counts["events"]),
            pending_deliveries=int(counts["pending_deliveries"]),
            failed_deliveries=int(counts["failed_deliveries"]),
            open_occurrences=int(counts["open_occurrences"]),
            latest_checkpoint_at_utc=(
                str(counts["latest_checkpoint_at_utc"])
                if counts["latest_checkpoint_at_utc"] is not None
                else None
            ),
        )
