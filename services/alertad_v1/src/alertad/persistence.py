from __future__ import annotations

import ctypes
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .contracts import (
    CheckpointAdvance,
    DirectoryResolution,
    EventCheckpoint,
    OperationalOccurrence,
)
from .formatting import event_attentions, format_alert
from .models import ADGroupEvent, Action, GroupScope


CURRENT_SCHEMA_VERSION = 5
CURRENT_SNAPSHOT_VERSION = 1
MAX_DELIVERY_QUERY_LIMIT = 500
DATABASE_MODES = frozenset({"production", "dry_run"})


class CheckpointConflictError(RuntimeError):
    """O progresso persistido mudou desde a leitura feita pelo coletor."""


class DeliveryConflictError(RuntimeError):
    """A entrega foi reservada ou concluída por outro executor."""


class EventIdentityConflictError(RuntimeError):
    """Uma identidade legada é ambígua ou contradiz o snapshot persistido."""


@dataclass(frozen=True)
class Delivery:
    event_key: str
    channel: str
    status: str
    attempts: int
    last_error: str | None
    next_attempt_at_utc: datetime | None = None
    failure_kind: str | None = None
    alert_message: str | None = None
    snapshot_version: int = 0
    claim_token: str | None = None


@dataclass(frozen=True)
class AlertSnapshot:
    event_key: str
    message: str | None
    snapshot_version: int
    event_key_version: int
    event_id: int
    action: str | None
    group_scope: str | None
    event_record_id: int
    source_computer: str
    channel: str
    time_created_utc: datetime
    time_created_raw: str | None
    target_user_name: str
    target_domain_name: str | None
    target_sid: str | None
    member_sid: str
    member_name: str | None
    subject_user_sid: str | None
    subject_user_name: str | None
    subject_domain_name: str | None
    subject_logon_id: str | None
    directory_resolution_status: str | None
    directory_account_name: str | None
    directory_domain_name: str | None
    directory_display_name: str | None
    directory_object_type: str | None

    @property
    def complete(self) -> bool:
        return (
            self.snapshot_version == CURRENT_SNAPSHOT_VERSION
            and self.message is not None
            and bool(self.message.strip())
        )

    def to_event(self) -> ADGroupEvent:
        if self.action is None or self.group_scope is None:
            raise RuntimeError("Snapshot legado não permite reconstruir o evento")
        return ADGroupEvent(
            event_id=self.event_id,
            action=Action(self.action),
            group_scope=GroupScope(self.group_scope),
            time_created_utc=self.time_created_utc,
            event_record_id=self.event_record_id,
            channel=self.channel,
            source_computer=self.source_computer,
            member_name=self.member_name,
            member_sid=self.member_sid,
            target_user_name=self.target_user_name,
            target_domain_name=self.target_domain_name,
            target_sid=self.target_sid,
            subject_user_sid=self.subject_user_sid,
            subject_user_name=self.subject_user_name,
            subject_domain_name=self.subject_domain_name,
            subject_logon_id=self.subject_logon_id,
            raw_xml="",
            time_created_raw=self.time_created_raw,
        )


@dataclass(frozen=True)
class StoredOccurrence:
    occurrence_id: int
    category: str
    component: str
    reason_code: str
    fingerprint: str
    occurred_at_utc: datetime
    source: str | None
    resolved_at_utc: datetime | None


@dataclass(frozen=True)
class PurgeResult:
    events: int = 0
    occurrences: int = 0


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Data persistida deve possuir fuso horário")
    return value.astimezone(timezone.utc).isoformat()


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value)).astimezone(timezone.utc)


def _ensure_local_database_path(path: Path) -> None:
    raw_path = os.fspath(path)
    if raw_path.startswith(("\\\\", "//")):
        raise ValueError("O banco SQLite deve usar um caminho local, não um compartilhamento de rede")

    if os.name != "nt":
        return

    resolved = path.resolve(strict=False)
    root = resolved.anchor
    if not root:
        return
    # GetDriveTypeW apenas classifica a unidade local; não abre arquivos nem acessa servidores.
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(root)  # type: ignore[attr-defined]
    if drive_type in {0, 1}:  # DRIVE_UNKNOWN / DRIVE_NO_ROOT_DIR
        raise ValueError("Não foi possível confirmar que o banco SQLite usa armazenamento local")
    if drive_type == 4:  # DRIVE_REMOTE
        raise ValueError("O banco SQLite não pode ficar em uma unidade de rede mapeada")


class EventStore:
    def __init__(
        self,
        database_path: str | Path,
        *,
        max_delivery_attempts: int = 6,
        database_mode: str = "production",
    ) -> None:
        if isinstance(max_delivery_attempts, bool) or not isinstance(max_delivery_attempts, int):
            raise ValueError("max_delivery_attempts deve ser um número inteiro")
        if max_delivery_attempts != 6:
            raise ValueError(
                "max_delivery_attempts deve ser 6: envio inicial e cinco retentativas"
            )
        normalized_mode = database_mode.strip().casefold()
        if normalized_mode not in DATABASE_MODES:
            raise ValueError("database_mode deve ser production ou dry_run")
        self.database_path = Path(database_path).resolve(strict=False)
        self.max_delivery_attempts = max_delivery_attempts
        self.database_mode = normalized_mode
        _ensure_local_database_path(self.database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._reject_hard_linked_database()

    def _reject_hard_linked_database(self) -> None:
        try:
            links = int(self.database_path.stat().st_nlink)
        except OSError as exc:
            raise ValueError("Não foi possível validar a identidade física do banco") from exc
        if links != 1:
            raise ValueError(
                "O banco SQLite não pode possuir hard links; use um único caminho físico"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _connection(self, *, immediate: bool = False):
        connection = self._connect()
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > CURRENT_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Banco usa esquema {version}, superior ao suportado "
                    f"({CURRENT_SCHEMA_VERSION})"
                )
            created_schema = False
            if version < 1:
                user_tables = {
                    str(row["name"])
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                        """
                    )
                }
                if user_tables:
                    if not {"events", "deliveries"}.issubset(user_tables):
                        raise RuntimeError(
                            "Banco sem versão contém esquema legado incompleto; "
                            "events e deliveries são obrigatórias"
                        )
                else:
                    self._migrate_to_v1(connection)
                    created_schema = True
                self._validate_v1_schema(connection)
                connection.execute("PRAGMA user_version = 1")
                version = 1
            if version < 2:
                self._validate_v1_schema(connection)
                self._migrate_to_v2(connection)
                connection.execute("PRAGMA user_version = 2")
                version = 2
            if version < 3:
                self._validate_v2_schema(connection)
                self._migrate_to_v3(connection)
                connection.execute("PRAGMA user_version = 3")
                version = 3
            if version < 4:
                self._migrate_to_v4(
                    connection,
                    self.database_mode if created_schema else "production",
                )
                connection.execute("PRAGMA user_version = 4")
                version = 4
            if version < 5:
                self._migrate_to_v5(connection)
                connection.execute("PRAGMA user_version = 5")
            self._validate_schema(connection)
            persisted_mode = connection.execute(
                "SELECT value FROM runtime_metadata WHERE key = 'database_mode'"
            ).fetchone()
            if persisted_mode is None or str(persisted_mode["value"]) != self.database_mode:
                raise RuntimeError(
                    "Modo do banco incompatível: não reutilize banco de produção em "
                    "dry-run nem banco de dry-run em produção"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _migrate_to_v1(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_key TEXT PRIMARY KEY,
                event_id INTEGER NOT NULL,
                event_record_id INTEGER NOT NULL,
                source_computer TEXT NOT NULL,
                channel TEXT NOT NULL,
                time_created_utc TEXT NOT NULL,
                target_user_name TEXT NOT NULL,
                member_sid TEXT NOT NULL,
                attentions_json TEXT NOT NULL,
                received_at_utc TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS deliveries (
                event_key TEXT NOT NULL,
                channel TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'sent', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at_utc TEXT NOT NULL,
                PRIMARY KEY (event_key, channel),
                FOREIGN KEY (event_key) REFERENCES events(event_key)
            )
            """
        )

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _table_info(
        connection: sqlite3.Connection,
        table: str,
    ) -> dict[str, sqlite3.Row]:
        return {
            str(row["name"]): row
            for row in connection.execute(f"PRAGMA table_info({table})")
        }

    @classmethod
    def _require_columns(
        cls,
        connection: sqlite3.Connection,
        table: str,
        expected: dict[str, tuple[str, bool]],
    ) -> None:
        info = cls._table_info(connection, table)
        missing = set(expected) - set(info)
        if missing:
            raise RuntimeError(
                f"Esquema SQLite inválido em {table}; colunas ausentes: "
                + ", ".join(sorted(missing))
            )
        for name, (declared_type, required) in expected.items():
            row = info[name]
            if str(row["type"]).casefold() != declared_type.casefold():
                raise RuntimeError(
                    f"Esquema SQLite inválido em {table}.{name}; tipo incompatível"
                )
            if required and not bool(row["notnull"]) and not bool(row["pk"]):
                raise RuntimeError(
                    f"Esquema SQLite inválido em {table}.{name}; NOT NULL ausente"
                )

    @classmethod
    def _require_primary_key(
        cls,
        connection: sqlite3.Connection,
        table: str,
        expected: tuple[str, ...],
    ) -> None:
        actual = tuple(
            name
            for _, name in sorted(
                (
                    (int(row["pk"]), str(row["name"]))
                    for row in cls._table_info(connection, table).values()
                    if int(row["pk"]) > 0
                )
            )
        )
        if actual != expected:
            raise RuntimeError(
                f"Esquema SQLite inválido em {table}; chave primária esperada: "
                + ", ".join(expected)
            )

    @staticmethod
    def _require_foreign_key(
        connection: sqlite3.Connection,
        table: str,
        *,
        from_column: str,
        target_table: str,
        target_column: str,
    ) -> None:
        found = any(
            str(row["from"]) == from_column
            and str(row["table"]) == target_table
            and str(row["to"]) == target_column
            for row in connection.execute(f"PRAGMA foreign_key_list({table})")
        )
        if not found:
            raise RuntimeError(
                f"Esquema SQLite inválido em {table}; foreign key obrigatória ausente"
            )

    @staticmethod
    def _require_unique_columns(
        connection: sqlite3.Connection,
        table: str,
        expected: tuple[str, ...],
    ) -> None:
        for index in connection.execute(f"PRAGMA index_list({table})"):
            if not bool(index["unique"]):
                continue
            columns = tuple(
                str(row["name"])
                for row in connection.execute(
                    f"PRAGMA index_info({str(index['name'])})"
                )
            )
            if columns == expected:
                return
        raise RuntimeError(
            f"Esquema SQLite inválido em {table}; unicidade obrigatória ausente"
        )

    @staticmethod
    def _require_delivery_status_check(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'deliveries'"
        ).fetchone()
        normalized = "".join(str(row["sql"] if row else "").casefold().split())
        if "check(statusin('pending','sent','failed'))" not in normalized:
            raise RuntimeError(
                "Esquema SQLite inválido em deliveries; constraint de status ausente"
            )

    @staticmethod
    def _require_index(
        connection: sqlite3.Connection,
        name: str,
        table: str,
        expected_columns: tuple[str, ...],
    ) -> None:
        row = connection.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        if row is None or str(row["tbl_name"]) != table:
            raise RuntimeError(f"Esquema SQLite inválido; índice ausente: {name}")
        columns = tuple(
            str(item["name"])
            for item in connection.execute(f"PRAGMA index_info({name})")
        )
        if columns != expected_columns:
            raise RuntimeError(f"Esquema SQLite inválido; índice incompatível: {name}")

    @classmethod
    def _validate_v1_schema(cls, connection: sqlite3.Connection) -> None:
        cls._require_columns(
            connection,
            "events",
            {
                "event_key": ("TEXT", False),
                "event_id": ("INTEGER", True),
                "event_record_id": ("INTEGER", True),
                "source_computer": ("TEXT", True),
                "channel": ("TEXT", True),
                "time_created_utc": ("TEXT", True),
                "target_user_name": ("TEXT", True),
                "member_sid": ("TEXT", True),
                "attentions_json": ("TEXT", True),
                "received_at_utc": ("TEXT", True),
            },
        )
        cls._require_columns(
            connection,
            "deliveries",
            {
                "event_key": ("TEXT", True),
                "channel": ("TEXT", True),
                "status": ("TEXT", True),
                "attempts": ("INTEGER", True),
                "last_error": ("TEXT", False),
                "updated_at_utc": ("TEXT", True),
            },
        )
        cls._require_primary_key(connection, "events", ("event_key",))
        cls._require_primary_key(
            connection,
            "deliveries",
            ("event_key", "channel"),
        )
        cls._require_foreign_key(
            connection,
            "deliveries",
            from_column="event_key",
            target_table="events",
            target_column="event_key",
        )
        cls._require_delivery_status_check(connection)

    @classmethod
    def _add_column(
        cls,
        connection: sqlite3.Connection,
        table: str,
        name: str,
        definition: str,
    ) -> None:
        if name not in cls._column_names(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @classmethod
    def _migrate_to_v2(cls, connection: sqlite3.Connection) -> None:
        event_columns = {
            "action": "TEXT",
            "group_scope": "TEXT",
            "member_name": "TEXT",
            "target_domain_name": "TEXT",
            "target_sid": "TEXT",
            "subject_user_sid": "TEXT",
            "subject_user_name": "TEXT",
            "subject_domain_name": "TEXT",
            "subject_logon_id": "TEXT",
            "alert_message": "TEXT",
            # Zero identifica linhas legadas cujos dados ausentes não podem ser inventados.
            "snapshot_version": "INTEGER NOT NULL DEFAULT 0",
            "directory_resolution_status": "TEXT",
            "directory_account_name": "TEXT",
            "directory_domain_name": "TEXT",
            "directory_display_name": "TEXT",
            "directory_object_type": "TEXT",
            "directory_error_code": "TEXT",
            "collection_source": "TEXT",
            "collection_checkpoint": "TEXT",
        }
        for name, definition in event_columns.items():
            cls._add_column(connection, "events", name, definition)

        cls._add_column(connection, "deliveries", "next_attempt_at_utc", "TEXT")
        cls._add_column(connection, "deliveries", "failure_kind", "TEXT")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_checkpoints (
                source TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_occurrences (
                occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                component TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                occurred_at_utc TEXT NOT NULL,
                source TEXT,
                resolved_at_utc TEXT,
                created_at_utc TEXT NOT NULL,
                UNIQUE (category, fingerprint)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_deliveries_pending
            ON deliveries(status, next_attempt_at_utc, updated_at_utc)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_events_received
            ON events(received_at_utc)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_occurrences_open
            ON operational_occurrences(category, resolved_at_utc, occurred_at_utc)
            """
        )

    @classmethod
    def _migrate_to_v3(cls, connection: sqlite3.Connection) -> None:
        cls._add_column(
            connection,
            "events",
            "event_key_version",
            "INTEGER NOT NULL DEFAULT 1",
        )
        cls._add_column(connection, "events", "time_created_raw", "TEXT")
        cls._add_column(connection, "events", "collection_generation", "TEXT")
        cls._add_column(connection, "events", "collection_sequence", "INTEGER")
        cls._add_column(
            connection,
            "collection_checkpoints",
            "generation",
            "TEXT NOT NULL DEFAULT 'legacy'",
        )
        cls._add_column(
            connection,
            "collection_checkpoints",
            "sequence",
            "INTEGER NOT NULL DEFAULT 0",
        )

        checkpoint_rows = connection.execute(
            "SELECT source FROM collection_checkpoints"
        ).fetchall()
        canonical_sources: dict[str, str] = {}
        for row in checkpoint_rows:
            original = str(row["source"])
            canonical = original.strip().casefold()
            if not canonical:
                raise RuntimeError("Checkpoint legado possui source vazia")
            previous = canonical_sources.get(canonical)
            if previous is not None and previous != original:
                raise RuntimeError(
                    "Checkpoints legados possuem fontes equivalentes com valores distintos"
                )
            canonical_sources[canonical] = original
        for canonical, original in canonical_sources.items():
            if canonical != original:
                connection.execute(
                    "UPDATE collection_checkpoints SET source = ? WHERE source = ?",
                    (canonical, original),
                )
        event_sources = connection.execute(
            """
            SELECT event_key, collection_source
            FROM events
            WHERE collection_source IS NOT NULL
            """
        ).fetchall()
        for row in event_sources:
            canonical = str(row["collection_source"]).strip().casefold()
            if not canonical:
                raise RuntimeError("Evento legado possui collection_source vazia")
            connection.execute(
                "UPDATE events SET collection_source = ? WHERE event_key = ?",
                (canonical, str(row["event_key"])),
            )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS event_identity_aliases (
                alias_key TEXT PRIMARY KEY,
                event_key TEXT NOT NULL,
                key_version INTEGER NOT NULL CHECK(key_version IN (1, 2)),
                FOREIGN KEY (event_key) REFERENCES events(event_key)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO event_identity_aliases (alias_key, event_key, key_version)
            SELECT event_key, event_key, event_key_version
            FROM events
            WHERE true
            ON CONFLICT(alias_key) DO NOTHING
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_alias_target
            ON event_identity_aliases(event_key)
            """
        )

    @staticmethod
    def _migrate_to_v4(connection: sqlite3.Connection, database_mode: str) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO runtime_metadata (key, value)
            VALUES ('database_mode', ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (database_mode,),
        )

    @classmethod
    def _migrate_to_v5(cls, connection: sqlite3.Connection) -> None:
        # O token diferencia uma chamada externa ainda ativa de uma tentativa
        # incerta deixada por um processo que terminou. Claims v4 não possuíam
        # proprietário persistido e chegam como livres nesta migração.
        cls._add_column(connection, "deliveries", "claim_token", "TEXT")

    @classmethod
    def _validate_v2_schema(cls, connection: sqlite3.Connection) -> None:
        cls._validate_v1_schema(connection)
        cls._require_columns(
            connection,
            "events",
            {
                "action": ("TEXT", False),
                "group_scope": ("TEXT", False),
                "member_name": ("TEXT", False),
                "target_domain_name": ("TEXT", False),
                "target_sid": ("TEXT", False),
                "subject_user_sid": ("TEXT", False),
                "subject_user_name": ("TEXT", False),
                "subject_domain_name": ("TEXT", False),
                "subject_logon_id": ("TEXT", False),
                "alert_message": ("TEXT", False),
                "snapshot_version": ("INTEGER", True),
                "directory_resolution_status": ("TEXT", False),
                "directory_account_name": ("TEXT", False),
                "directory_domain_name": ("TEXT", False),
                "directory_display_name": ("TEXT", False),
                "directory_object_type": ("TEXT", False),
                "directory_error_code": ("TEXT", False),
                "collection_source": ("TEXT", False),
                "collection_checkpoint": ("TEXT", False),
            },
        )
        cls._require_columns(
            connection,
            "deliveries",
            {
                "next_attempt_at_utc": ("TEXT", False),
                "failure_kind": ("TEXT", False),
            },
        )
        cls._require_columns(
            connection,
            "collection_checkpoints",
            {
                "source": ("TEXT", False),
                "value": ("TEXT", True),
                "updated_at_utc": ("TEXT", True),
            },
        )
        cls._require_primary_key(connection, "collection_checkpoints", ("source",))
        cls._require_columns(
            connection,
            "operational_occurrences",
            {
                "occurrence_id": ("INTEGER", False),
                "category": ("TEXT", True),
                "component": ("TEXT", True),
                "reason_code": ("TEXT", True),
                "fingerprint": ("TEXT", True),
                "occurred_at_utc": ("TEXT", True),
                "source": ("TEXT", False),
                "resolved_at_utc": ("TEXT", False),
                "created_at_utc": ("TEXT", True),
            },
        )
        cls._require_primary_key(
            connection,
            "operational_occurrences",
            ("occurrence_id",),
        )
        cls._require_unique_columns(
            connection,
            "operational_occurrences",
            ("category", "fingerprint"),
        )
        cls._require_index(
            connection,
            "idx_deliveries_pending",
            "deliveries",
            ("status", "next_attempt_at_utc", "updated_at_utc"),
        )
        cls._require_index(
            connection,
            "idx_events_received",
            "events",
            ("received_at_utc",),
        )
        cls._require_index(
            connection,
            "idx_occurrences_open",
            "operational_occurrences",
            ("category", "resolved_at_utc", "occurred_at_utc"),
        )

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Versão do esquema SQLite inválida: {version}; "
                f"esperada: {CURRENT_SCHEMA_VERSION}"
            )
        cls._validate_v2_schema(connection)
        cls._require_columns(
            connection,
            "events",
            {
                "event_key_version": ("INTEGER", True),
                "time_created_raw": ("TEXT", False),
                "collection_generation": ("TEXT", False),
                "collection_sequence": ("INTEGER", False),
            },
        )
        cls._require_columns(
            connection,
            "collection_checkpoints",
            {
                "generation": ("TEXT", True),
                "sequence": ("INTEGER", True),
            },
        )
        cls._require_columns(
            connection,
            "event_identity_aliases",
            {
                "alias_key": ("TEXT", False),
                "event_key": ("TEXT", True),
                "key_version": ("INTEGER", True),
            },
        )
        cls._require_primary_key(
            connection,
            "event_identity_aliases",
            ("alias_key",),
        )
        cls._require_foreign_key(
            connection,
            "event_identity_aliases",
            from_column="event_key",
            target_table="events",
            target_column="event_key",
        )
        cls._require_index(
            connection,
            "idx_event_alias_target",
            "event_identity_aliases",
            ("event_key",),
        )
        cls._require_columns(
            connection,
            "runtime_metadata",
            {
                "key": ("TEXT", False),
                "value": ("TEXT", True),
            },
        )
        cls._require_primary_key(connection, "runtime_metadata", ("key",))
        cls._require_columns(
            connection,
            "deliveries",
            {"claim_token": ("TEXT", False)},
        )
        mode = connection.execute(
            "SELECT value FROM runtime_metadata WHERE key = 'database_mode'"
        ).fetchone()
        if mode is None or str(mode["value"]) not in DATABASE_MODES:
            raise RuntimeError("Banco SQLite não possui modo de execução válido")

        invalid_version = connection.execute(
            """
            SELECT 1 FROM events
            WHERE snapshot_version NOT IN (0, ?)
               OR event_key_version NOT IN (1, 2)
            LIMIT 1
            """,
            (CURRENT_SNAPSHOT_VERSION,),
        ).fetchone()
        if invalid_version is not None:
            raise RuntimeError("Banco SQLite possui versão lógica de evento inválida")
        invalid_checkpoint = connection.execute(
            """
            SELECT 1 FROM collection_checkpoints
            WHERE sequence < 0 OR trim(source) = '' OR trim(generation) = ''
            LIMIT 1
            """
        ).fetchone()
        if invalid_checkpoint is not None:
            raise RuntimeError("Banco SQLite possui checkpoint logicamente inválido")
        for row in connection.execute("SELECT source FROM collection_checkpoints"):
            source = str(row["source"])
            if source != source.strip().casefold():
                raise RuntimeError("Banco SQLite possui source de checkpoint não canônica")
        missing_alias = connection.execute(
            """
            SELECT 1
            FROM events AS e
            LEFT JOIN event_identity_aliases AS a
              ON a.alias_key = e.event_key AND a.event_key = e.event_key
            WHERE a.alias_key IS NULL
            LIMIT 1
            """
        ).fetchone()
        if missing_alias is not None:
            raise RuntimeError("Banco SQLite possui evento sem alias de identidade")

        foreign_key_error = connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_error is not None:
            raise RuntimeError("Banco SQLite possui violação de integridade referencial")
        integrity = connection.execute("PRAGMA quick_check(1)").fetchone()
        if integrity is None or str(integrity[0]).casefold() != "ok":
            raise RuntimeError("Falha na verificação de integridade do banco SQLite")

    def schema_version(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _resolution_values(
        resolution: DirectoryResolution | None,
    ) -> dict[str, str | None]:
        if resolution is None:
            return {
                "directory_resolution_status": None,
                "directory_account_name": None,
                "directory_domain_name": None,
                "directory_display_name": None,
                "directory_object_type": None,
                "directory_error_code": None,
            }
        directory_object = resolution.directory_object
        return {
            "directory_resolution_status": resolution.status.value,
            "directory_account_name": (
                directory_object.account_name if directory_object is not None else None
            ),
            "directory_domain_name": (
                directory_object.domain_name if directory_object is not None else None
            ),
            "directory_display_name": (
                directory_object.display_name if directory_object is not None else None
            ),
            "directory_object_type": (
                directory_object.object_type if directory_object is not None else None
            ),
            "directory_error_code": resolution.error_code,
        }

    @staticmethod
    def _persisted_event_matches(
        row: sqlite3.Row,
        event: ADGroupEvent,
        *,
        require_precise_time: bool,
    ) -> bool:
        """Compara apenas dados imutáveis disponíveis no registro persistido."""
        raw_time = row["time_created_raw"]
        if require_precise_time and (
            raw_time is None
            or event.time_created_raw is None
            or str(raw_time) != event.time_created_raw
        ):
            return False
        required = (
            int(row["event_id"]) == event.event_id,
            int(row["event_record_id"]) == event.event_record_id,
            str(row["source_computer"]).casefold() == event.source_computer.casefold(),
            str(row["channel"]).casefold() == event.channel.casefold(),
            str(row["target_user_name"]) == event.target_user_name,
            str(row["member_sid"]).casefold() == event.member_sid.casefold(),
        )
        if not all(required):
            return False
        optional = (
            ("member_name", event.member_name),
            ("target_domain_name", event.target_domain_name),
            ("target_sid", event.target_sid),
            ("subject_user_sid", event.subject_user_sid),
            ("subject_user_name", event.subject_user_name),
            ("subject_domain_name", event.subject_domain_name),
            ("subject_logon_id", event.subject_logon_id),
        )
        return all(
            row[name] is None or str(row[name]) == incoming
            for name, incoming in optional
        )

    @classmethod
    def _resolve_event_identity(
        cls,
        connection: sqlite3.Connection,
        event: ADGroupEvent,
    ) -> tuple[str, bool]:
        rows = connection.execute(
            """
            SELECT a.alias_key, a.event_key, a.key_version, e.*
            FROM event_identity_aliases AS a
            JOIN events AS e ON e.event_key = a.event_key
            WHERE a.alias_key IN (?, ?)
            """,
            (event.event_key, event.legacy_event_key),
        ).fetchall()
        by_alias = {str(row["alias_key"]): row for row in rows}
        exact = by_alias.get(event.event_key)
        legacy = by_alias.get(event.legacy_event_key)
        targets = {str(row["event_key"]) for row in rows}
        if len(targets) > 1:
            raise EventIdentityConflictError(
                "Aliases de identidade apontam para eventos distintos"
            )
        if exact is not None:
            if not cls._persisted_event_matches(
                exact,
                event,
                require_precise_time=True,
            ):
                raise EventIdentityConflictError(
                    "A identidade atual contradiz o snapshot persistido"
                )
            return str(exact["event_key"]), True
        if legacy is not None:
            if not cls._persisted_event_matches(
                legacy,
                event,
                require_precise_time=True,
            ):
                raise EventIdentityConflictError(
                    "Alias legado ambíguo; equivalência precisa não pôde ser comprovada"
                )
            stored_event_key = str(legacy["event_key"])
            connection.execute(
                """
                INSERT INTO event_identity_aliases (alias_key, event_key, key_version)
                VALUES (?, ?, 2)
                """,
                (event.event_key, stored_event_key),
            )
            return stored_event_key, True
        return event.event_key, False

    @staticmethod
    def _advance_checkpoint(
        connection: sqlite3.Connection,
        advance: CheckpointAdvance,
        now: str,
    ) -> None:
        next_checkpoint = advance.next
        if advance.expected is None:
            cursor = connection.execute(
                """
                INSERT INTO collection_checkpoints (
                    source, value, updated_at_utc, generation, sequence
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO NOTHING
                """,
                (
                    next_checkpoint.source,
                    next_checkpoint.value,
                    now,
                    next_checkpoint.generation,
                    next_checkpoint.sequence,
                ),
            )
        else:
            expected = advance.expected
            cursor = connection.execute(
                """
                UPDATE collection_checkpoints
                SET value = ?, updated_at_utc = ?, generation = ?, sequence = ?
                WHERE source = ? AND value = ? AND generation = ? AND sequence = ?
                """,
                (
                    next_checkpoint.value,
                    now,
                    next_checkpoint.generation,
                    next_checkpoint.sequence,
                    expected.source,
                    expected.value,
                    expected.generation,
                    expected.sequence,
                ),
            )
        if cursor.rowcount != 1:
            raise CheckpointConflictError(
                "Checkpoint foi alterado ou já existe; releia a posição persistida"
            )

    def add_event(
        self,
        event: ADGroupEvent,
        channels: Iterable[str] = ("teams", "email"),
        *,
        message: str | None = None,
        checkpoint_advance: CheckpointAdvance | None = None,
        directory_resolution: DirectoryResolution | None = None,
        enqueue_deliveries: bool = True,
    ) -> bool:
        # O snapshot é preparado antes da transação: uma falha de formatação não
        # pode deixar evento/entregas irrecuperáveis no banco.
        alert_message = (
            message
            if message is not None
            else format_alert(event, directory_resolution)
        )
        if not alert_message.strip():
            raise ValueError("A mensagem persistida não pode ser vazia")

        normalized_channels = tuple(
            dict.fromkeys(channel.strip().casefold() for channel in channels)
        )
        if enqueue_deliveries and (
            not normalized_channels or any(not channel for channel in normalized_channels)
        ):
            raise ValueError("Informe ao menos um canal válido")
        if not enqueue_deliveries and self.database_mode != "dry_run":
            raise ValueError("Somente banco dry_run pode persistir sem entregas")

        now = datetime.now(timezone.utc).isoformat()
        next_checkpoint = (
            checkpoint_advance.next if checkpoint_advance is not None else None
        )
        values: dict[str, object] = {
            "event_key": event.event_key,
            "event_key_version": 2,
            "event_id": event.event_id,
            "action": event.action.value,
            "group_scope": event.group_scope.value,
            "event_record_id": event.event_record_id,
            "source_computer": event.source_computer,
            "channel": event.channel,
            "time_created_utc": _utc_iso(event.time_created_utc),
            "time_created_raw": event.time_created_raw,
            "target_user_name": event.target_user_name,
            "target_domain_name": event.target_domain_name,
            "target_sid": event.target_sid,
            "member_sid": event.member_sid,
            "member_name": event.member_name,
            "subject_user_sid": event.subject_user_sid,
            "subject_user_name": event.subject_user_name,
            "subject_domain_name": event.subject_domain_name,
            "subject_logon_id": event.subject_logon_id,
            "attentions_json": json.dumps(
                event_attentions(event, directory_resolution),
                ensure_ascii=False,
            ),
            "alert_message": alert_message,
            "snapshot_version": CURRENT_SNAPSHOT_VERSION,
            "collection_source": (
                next_checkpoint.source if next_checkpoint is not None else None
            ),
            "collection_checkpoint": (
                next_checkpoint.value if next_checkpoint is not None else None
            ),
            "collection_generation": (
                next_checkpoint.generation if next_checkpoint is not None else None
            ),
            "collection_sequence": (
                next_checkpoint.sequence if next_checkpoint is not None else None
            ),
            "received_at_utc": now,
        }
        values.update(self._resolution_values(directory_resolution))

        with self._connection(immediate=True) as connection:
            stored_event_key, identity_exists = self._resolve_event_identity(
                connection,
                event,
            )
            values["event_key"] = stored_event_key

            if identity_exists:
                inserted = False
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO events (
                        event_key, event_key_version, event_id, action, group_scope,
                        event_record_id, source_computer, channel, time_created_utc,
                        time_created_raw, target_user_name, target_domain_name,
                        target_sid, member_sid, member_name, subject_user_sid,
                        subject_user_name, subject_domain_name, subject_logon_id,
                        attentions_json, alert_message, snapshot_version,
                        directory_resolution_status, directory_account_name,
                        directory_domain_name, directory_display_name,
                        directory_object_type, directory_error_code,
                        collection_source, collection_checkpoint,
                        collection_generation, collection_sequence, received_at_utc
                    ) VALUES (
                        :event_key, :event_key_version, :event_id, :action, :group_scope,
                        :event_record_id, :source_computer, :channel, :time_created_utc,
                        :time_created_raw, :target_user_name, :target_domain_name,
                        :target_sid, :member_sid, :member_name, :subject_user_sid,
                        :subject_user_name, :subject_domain_name, :subject_logon_id,
                        :attentions_json, :alert_message, :snapshot_version,
                        :directory_resolution_status, :directory_account_name,
                        :directory_domain_name, :directory_display_name,
                        :directory_object_type, :directory_error_code,
                        :collection_source, :collection_checkpoint,
                        :collection_generation, :collection_sequence, :received_at_utc
                    )
                    """,
                    values,
                )
                inserted = cursor.rowcount == 1

            connection.execute(
                """
                INSERT INTO event_identity_aliases (alias_key, event_key, key_version)
                VALUES (?, ?, 2)
                ON CONFLICT(alias_key) DO NOTHING
                """,
                (event.event_key, stored_event_key),
            )
            if self.database_mode == "dry_run":
                enqueue_deliveries = False
            if inserted and enqueue_deliveries:
                connection.executemany(
                    """
                    INSERT INTO deliveries (
                        event_key, channel, status, attempts, updated_at_utc
                    ) VALUES (?, ?, 'pending', 0, ?)
                    """,
                    ((stored_event_key, channel, now) for channel in normalized_channels),
                )
            else:
                # Um banco legado não possui dados suficientes para reconstruir a
                # mensagem. Se o mesmo XML reaparecer, preenchemos o snapshot sem
                # duplicar o evento ou suas entregas.
                connection.execute(
                    """
                    UPDATE events
                    SET action = :action,
                        group_scope = :group_scope,
                        member_name = :member_name,
                        target_domain_name = :target_domain_name,
                        target_sid = :target_sid,
                        subject_user_sid = :subject_user_sid,
                        subject_user_name = :subject_user_name,
                        subject_domain_name = :subject_domain_name,
                        subject_logon_id = :subject_logon_id,
                        attentions_json = :attentions_json,
                        alert_message = :alert_message,
                        snapshot_version = :snapshot_version,
                        directory_resolution_status = :directory_resolution_status,
                        directory_account_name = :directory_account_name,
                        directory_domain_name = :directory_domain_name,
                        directory_display_name = :directory_display_name,
                        directory_object_type = :directory_object_type,
                        directory_error_code = :directory_error_code
                    WHERE event_key = :event_key AND snapshot_version = 0
                    """,
                    values,
                )

            if checkpoint_advance is not None:
                self._advance_checkpoint(connection, checkpoint_advance, now)
            return inserted

    def get_checkpoint(self, source: str) -> EventCheckpoint | None:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source do checkpoint não pode ser vazio")
        normalized_source = source.strip().casefold()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT source, value, generation, sequence
                FROM collection_checkpoints WHERE source = ?
                """,
                (normalized_source,),
            ).fetchone()
        if row is None:
            return None
        return EventCheckpoint(
            str(row["source"]),
            str(row["value"]),
            str(row["generation"]),
            int(row["sequence"]),
        )

    def advance_checkpoint(self, advance: CheckpointAdvance) -> None:
        """Persiste progresso de um item seguro que não gera evento armazenado."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connection(immediate=True) as connection:
            self._advance_checkpoint(connection, advance, now)

    def record_occurrence(
        self,
        occurrence: OperationalOccurrence,
        *,
        checkpoint_advance: CheckpointAdvance | None = None,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection(immediate=True) as connection:
            inserted = self._insert_occurrence(connection, occurrence, now)
            if checkpoint_advance is not None:
                self._advance_checkpoint(connection, checkpoint_advance, now)
            return inserted

    @staticmethod
    def _insert_occurrence(
        connection: sqlite3.Connection,
        occurrence: OperationalOccurrence,
        created_at: str,
    ) -> bool:
        cursor = connection.execute(
            """
            INSERT INTO operational_occurrences (
                category, component, reason_code, fingerprint,
                occurred_at_utc, source, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(category, fingerprint) DO NOTHING
            """,
            (
                occurrence.category.value,
                occurrence.component,
                occurrence.reason_code,
                occurrence.fingerprint,
                _utc_iso(occurrence.occurred_at_utc),
                occurrence.source,
                created_at,
            ),
        )
        return cursor.rowcount == 1

    def occurrence_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM operational_occurrences"
            ).fetchone()
        return int(row["total"] if row else 0)

    def list_occurrences(
        self,
        *,
        open_only: bool = True,
        limit: int = 100,
    ) -> list[StoredOccurrence]:
        self._validate_delivery_query_limit(limit)
        condition = "WHERE resolved_at_utc IS NULL" if open_only else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT occurrence_id, category, component, reason_code,
                       fingerprint, occurred_at_utc, source, resolved_at_utc
                FROM operational_occurrences
                {condition}
                ORDER BY occurred_at_utc, occurrence_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            StoredOccurrence(
                occurrence_id=int(row["occurrence_id"]),
                category=str(row["category"]),
                component=str(row["component"]),
                reason_code=str(row["reason_code"]),
                fingerprint=str(row["fingerprint"]),
                occurred_at_utc=datetime.fromisoformat(
                    str(row["occurred_at_utc"])
                ).astimezone(timezone.utc),
                source=row["source"],
                resolved_at_utc=_optional_datetime(row["resolved_at_utc"]),
            )
            for row in rows
        ]

    def resolve_occurrence(
        self,
        occurrence_id: int,
        *,
        resolved_at_utc: datetime | None = None,
    ) -> bool:
        if isinstance(occurrence_id, bool) or not isinstance(occurrence_id, int):
            raise ValueError("occurrence_id deve ser inteiro")
        if occurrence_id < 1:
            raise ValueError("occurrence_id deve ser positivo")
        resolved_at = _utc_iso(resolved_at_utc or datetime.now(timezone.utc))
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE operational_occurrences
                SET resolved_at_utc = ?
                WHERE occurrence_id = ? AND resolved_at_utc IS NULL
                """,
                (resolved_at, occurrence_id),
            )
        return cursor.rowcount == 1

    def status_counts(self) -> dict[str, int]:
        with self._connection() as connection:
            event_total = int(
                connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            )
            open_occurrences = int(
                connection.execute(
                    "SELECT COUNT(*) FROM operational_occurrences WHERE resolved_at_utc IS NULL"
                ).fetchone()[0]
            )
            delivery_rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM deliveries GROUP BY status"
            ).fetchall()
            active_claims = int(
                connection.execute(
                    "SELECT COUNT(*) FROM deliveries WHERE claim_token IS NOT NULL"
                ).fetchone()[0]
            )
        result = {
            "events": event_total,
            "open_occurrences": open_occurrences,
            "pending": 0,
            "sent": 0,
            "failed": 0,
            "active_claims": active_claims,
        }
        for row in delivery_rows:
            result[str(row["status"])] = int(row["total"])
        return result

    def operational_status(self) -> dict[str, object]:
        """Estado sanitizado: não expõe bookmark nem conteúdo de eventos."""
        with self._connection() as connection:
            checkpoints = connection.execute(
                """
                SELECT source, generation, sequence, updated_at_utc
                FROM collection_checkpoints ORDER BY source
                """
            ).fetchall()
        return {
            **self.status_counts(),
            "database_mode": self.database_mode,
            "schema_version": self.schema_version(),
            "checkpoints": [
                {
                    "source": str(row["source"]),
                    "generation_id": str(row["generation"])[:16],
                    "logical_sequence": int(row["sequence"]),
                    "updated_at_utc": str(row["updated_at_utc"]),
                }
                for row in checkpoints
            ],
        }

    def purge_completed(
        self,
        *,
        events_before_utc: datetime,
        resolved_occurrences_before_utc: datetime,
        batch_size: int = 500,
    ) -> PurgeResult:
        """Expurgo bloqueado até que a janela real de replay seja comprovada."""
        del events_before_utc, resolved_occurrences_before_utc, batch_size
        raise RuntimeError(
            "Expurgo desabilitado: a janela segura de replay ainda não foi validada"
        )

    def get_event_snapshot(self, event_key: str) -> AlertSnapshot | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT e.*
                FROM events AS e
                LEFT JOIN event_identity_aliases AS a ON a.event_key = e.event_key
                WHERE e.event_key = ? OR a.alias_key = ?
                LIMIT 1
                """,
                (event_key, event_key),
            ).fetchone()
        if row is None:
            return None
        timestamp = _optional_datetime(row["time_created_utc"])
        if timestamp is None:  # pragma: no cover - coluna obrigatória no esquema
            raise RuntimeError("Evento persistido sem time_created_utc")
        return AlertSnapshot(
            event_key=str(row["event_key"]),
            message=row["alert_message"],
            snapshot_version=int(row["snapshot_version"]),
            event_key_version=int(row["event_key_version"]),
            event_id=int(row["event_id"]),
            action=row["action"],
            group_scope=row["group_scope"],
            event_record_id=int(row["event_record_id"]),
            source_computer=str(row["source_computer"]),
            channel=str(row["channel"]),
            time_created_utc=timestamp,
            time_created_raw=row["time_created_raw"],
            target_user_name=str(row["target_user_name"]),
            target_domain_name=row["target_domain_name"],
            target_sid=row["target_sid"],
            member_sid=str(row["member_sid"]),
            member_name=row["member_name"],
            subject_user_sid=row["subject_user_sid"],
            subject_user_name=row["subject_user_name"],
            subject_domain_name=row["subject_domain_name"],
            subject_logon_id=row["subject_logon_id"],
            directory_resolution_status=row["directory_resolution_status"],
            directory_account_name=row["directory_account_name"],
            directory_domain_name=row["directory_domain_name"],
            directory_display_name=row["directory_display_name"],
            directory_object_type=row["directory_object_type"],
        )

    def claim_delivery_attempt(
        self,
        delivery: Delivery,
        *,
        started_at_utc: datetime,
        uncertainty_retry_at_utc: datetime,
    ) -> Delivery | None:
        """Reserva por CAS antes da rede; apenas o vencedor pode enviar."""
        if delivery.attempts >= self.max_delivery_attempts:
            return None
        started_at = _utc_iso(started_at_utc)
        retry_at = _utc_iso(uncertainty_retry_at_utc)
        claim_token = uuid.uuid4().hex
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE deliveries
                SET attempts = attempts + 1,
                    last_error = 'Resultado externo ainda não confirmado',
                    next_attempt_at_utc = ?,
                    failure_kind = 'uncertain',
                    claim_token = ?,
                    updated_at_utc = ?
                WHERE event_key = ? AND channel = ?
                  AND status = 'pending' AND attempts = ?
                  AND claim_token IS NULL
                  AND (
                      next_attempt_at_utc IS NULL
                      OR next_attempt_at_utc <= ?
                  )
                """,
                (
                    retry_at,
                    claim_token,
                    started_at,
                    delivery.event_key,
                    delivery.channel,
                    delivery.attempts,
                    started_at,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM deliveries WHERE event_key = ? AND channel = ?",
                (delivery.event_key, delivery.channel),
            ).fetchone()
            if row is None:  # pragma: no cover - protegido pela transação
                raise RuntimeError("Entrega desapareceu durante a reserva")
            return self._to_delivery(row)

    def complete_delivery_attempt(
        self,
        event_key: str,
        channel: str,
        *,
        attempt_number: int,
        success: bool,
        retryable: bool = False,
        error: str | None = None,
        next_attempt_at_utc: datetime | None = None,
        failure_kind: str | None = None,
        claim_token: str | None = None,
        terminal_occurrence: OperationalOccurrence | None = None,
    ) -> Delivery:
        if attempt_number < 1:
            raise ValueError("attempt_number deve ser positivo")
        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("Conclusão de tentativa exige claim_token")
        if retryable and not success and attempt_number < self.max_delivery_attempts:
            next_status = "pending"
            if next_attempt_at_utc is None:
                raise ValueError("Falha temporária deve informar next_attempt_at_utc")
        elif success:
            next_status = "sent"
        else:
            next_status = "failed"
        next_attempt = (
            _utc_iso(next_attempt_at_utc)
            if next_status == "pending" and next_attempt_at_utc is not None
            else None
        )
        if success:
            normalized_error = None
            normalized_failure = None
        else:
            normalized_error = (error or "Falha sem detalhe").replace("\r", " ").replace("\n", " ")[:512]
            normalized_failure = failure_kind or (
                "temporary" if next_status == "pending" else "permanent"
            )
            if attempt_number >= self.max_delivery_attempts and retryable:
                normalized_failure = "exhausted"
        now = datetime.now(timezone.utc).isoformat()
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE deliveries
                SET status = ?, last_error = ?, next_attempt_at_utc = ?,
                    failure_kind = ?, claim_token = NULL, updated_at_utc = ?
                WHERE event_key = ? AND channel = ?
                  AND status = 'pending' AND attempts = ? AND claim_token = ?
                """,
                (
                    next_status,
                    normalized_error,
                    next_attempt,
                    normalized_failure,
                    now,
                    event_key,
                    channel.strip().casefold(),
                    attempt_number,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise DeliveryConflictError(
                    "Entrega mudou durante a tentativa; resultado não sobrescrito"
                )
            if next_status == "failed":
                if terminal_occurrence is None:
                    raise ValueError(
                        "Entrega terminal exige ocorrência operacional atômica"
                    )
                self._insert_occurrence(connection, terminal_occurrence, now)
            row = connection.execute(
                "SELECT * FROM deliveries WHERE event_key = ? AND channel = ?",
                (event_key, channel.strip().casefold()),
            ).fetchone()
            if row is None:  # pragma: no cover - protegido pela transação
                raise RuntimeError("Entrega desapareceu durante a conclusão")
            return self._to_delivery(row)

    def abandon_delivery_claim(self, delivery: Delivery) -> bool:
        """Libera somente o claim indicado; o prazo incerto permanece durável."""
        if not delivery.claim_token:
            return False
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE deliveries SET claim_token = NULL
                WHERE event_key = ? AND channel = ? AND status = 'pending'
                  AND attempts = ? AND claim_token = ?
                """,
                (
                    delivery.event_key,
                    delivery.channel,
                    delivery.attempts,
                    delivery.claim_token,
                ),
            )
        return cursor.rowcount == 1

    def recover_abandoned_claims(self) -> int:
        """Executar somente depois de adquirir o lock exclusivo do worker."""
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE deliveries SET claim_token = NULL
                WHERE status = 'pending' AND claim_token IS NOT NULL
                """
            )
        return cursor.rowcount

    def finalize_exhausted_uncertain(
        self,
        delivery: Delivery,
        occurrence: OperationalOccurrence,
    ) -> Delivery:
        """Finaliza atomicamente uma última tentativa incerta já recuperada."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE deliveries
                SET status = 'failed',
                    last_error = 'Resultado da última tentativa não foi confirmado',
                    next_attempt_at_utc = NULL,
                    failure_kind = 'uncertain',
                    updated_at_utc = ?
                WHERE event_key = ? AND channel = ? AND status = 'pending'
                  AND attempts = ? AND claim_token IS NULL
                """,
                (now, delivery.event_key, delivery.channel, delivery.attempts),
            )
            if cursor.rowcount != 1:
                raise DeliveryConflictError(
                    "Entrega incerta mudou antes da finalização"
                )
            self._insert_occurrence(connection, occurrence, now)
            row = connection.execute(
                "SELECT * FROM deliveries WHERE event_key = ? AND channel = ?",
                (delivery.event_key, delivery.channel),
            ).fetchone()
            if row is None:  # pragma: no cover
                raise RuntimeError("Entrega desapareceu durante a finalização")
            return self._to_delivery(row)

    def record_delivery_attempt(
        self,
        event_key: str,
        channel: str,
        *,
        success: bool,
        error: str | None = None,
        next_attempt_at_utc: datetime | None = None,
        failure_kind: str | None = None,
    ) -> Delivery:
        normalized_channel = channel.strip().casefold()
        next_attempt = (
            _utc_iso(next_attempt_at_utc) if next_attempt_at_utc is not None else None
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._connection(immediate=True) as connection:
            identity = connection.execute(
                """
                SELECT e.event_key
                FROM events AS e
                LEFT JOIN event_identity_aliases AS a ON a.event_key = e.event_key
                WHERE e.event_key = ? OR a.alias_key = ?
                LIMIT 1
                """,
                (event_key, event_key),
            ).fetchone()
            stored_event_key = (
                str(identity["event_key"]) if identity is not None else event_key
            )
            row = connection.execute(
                "SELECT * FROM deliveries WHERE event_key = ? AND channel = ?",
                (stored_event_key, normalized_channel),
            ).fetchone()
            if row is None:
                raise KeyError(f"Entrega inexistente: {event_key}/{normalized_channel}")
            if row["status"] in {"sent", "failed"}:
                return self._to_delivery(row)

            next_status = (
                "sent"
                if success
                else (
                    "failed"
                    if int(row["attempts"]) + 1 >= self.max_delivery_attempts
                    else "pending"
                )
            )
            last_error = None if success else (error or "Falha sem detalhe")
            connection.execute(
                """
                UPDATE deliveries
                SET status = ?, attempts = attempts + 1, last_error = ?,
                    next_attempt_at_utc = ?, failure_kind = ?, updated_at_utc = ?
                WHERE event_key = ? AND channel = ? AND status = 'pending'
                """,
                (
                    next_status,
                    last_error,
                    None if success else next_attempt,
                    None if success else failure_kind,
                    now,
                    stored_event_key,
                    normalized_channel,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM deliveries WHERE event_key = ? AND channel = ?",
                (stored_event_key, normalized_channel),
            ).fetchone()
            if updated is None:  # pragma: no cover - protegido pela transação
                raise RuntimeError("Entrega desapareceu durante a atualização")
            return self._to_delivery(updated)

    @staticmethod
    def _validate_delivery_query_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit deve ser um número inteiro")
        if not 1 <= limit <= MAX_DELIVERY_QUERY_LIMIT:
            raise ValueError(
                f"limit deve estar entre 1 e {MAX_DELIVERY_QUERY_LIMIT}"
            )

    def pending_deliveries(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[Delivery]:
        self._validate_delivery_query_limit(limit)
        due_at = _utc_iso(now or datetime.now(timezone.utc))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT d.*, e.alert_message, e.snapshot_version
                FROM deliveries AS d
                JOIN events AS e ON e.event_key = d.event_key
                WHERE d.status = 'pending'
                  AND d.claim_token IS NULL
                  AND e.snapshot_version = ?
                  AND e.alert_message IS NOT NULL
                  AND trim(e.alert_message) <> ''
                  AND (
                      d.next_attempt_at_utc IS NULL
                      OR d.next_attempt_at_utc <= ?
                  )
                ORDER BY COALESCE(d.next_attempt_at_utc, d.updated_at_utc),
                         d.event_key, d.channel
                LIMIT ?
                """,
                (CURRENT_SNAPSHOT_VERSION, due_at, limit),
            ).fetchall()
        return [self._to_delivery(row) for row in rows]

    def blocked_deliveries(self, *, limit: int = 100) -> list[Delivery]:
        """Lista entregas pendentes sem snapshot válido para diagnóstico."""
        self._validate_delivery_query_limit(limit)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT d.*, e.alert_message, e.snapshot_version
                FROM deliveries AS d
                JOIN events AS e ON e.event_key = d.event_key
                WHERE d.status = 'pending'
                  AND (
                      e.snapshot_version <> ?
                      OR e.alert_message IS NULL
                      OR trim(e.alert_message) = ''
                  )
                ORDER BY d.updated_at_utc, d.event_key, d.channel
                LIMIT ?
                """,
                (CURRENT_SNAPSHOT_VERSION, limit),
            ).fetchall()
        return [self._to_delivery(row) for row in rows]

    def event_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM events").fetchone()
        return int(row["total"] if row else 0)

    def attention_report_rows(self) -> list[dict[str, str]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_key, event_id, event_record_id, source_computer,
                       time_created_utc, target_user_name, member_sid, attentions_json
                FROM events
                WHERE attentions_json <> '[]'
                ORDER BY time_created_utc
                """
            ).fetchall()

        report: list[dict[str, str]] = []
        for row in rows:
            attentions = json.loads(str(row["attentions_json"]))
            report.append(
                {
                    "alert_id": str(row["event_key"])[:12],
                    "event_id": str(row["event_id"]),
                    "event_record_id": str(row["event_record_id"]),
                    "source_computer": str(row["source_computer"]),
                    "time_created_utc": str(row["time_created_utc"]),
                    "target_user_name": str(row["target_user_name"]),
                    "member_sid": str(row["member_sid"]),
                    "attentions": " | ".join(str(item) for item in attentions),
                }
            )
        return report

    @staticmethod
    def _to_delivery(row: sqlite3.Row) -> Delivery:
        keys = set(row.keys())
        return Delivery(
            event_key=str(row["event_key"]),
            channel=str(row["channel"]),
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            last_error=row["last_error"],
            next_attempt_at_utc=_optional_datetime(row["next_attempt_at_utc"]),
            failure_kind=row["failure_kind"],
            alert_message=row["alert_message"] if "alert_message" in keys else None,
            snapshot_version=(
                int(row["snapshot_version"]) if "snapshot_version" in keys else 0
            ),
            claim_token=row["claim_token"] if "claim_token" in keys else None,
        )
