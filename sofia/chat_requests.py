"""Short-lived, cross-process ownership registry for chat cancellation.

Stores identifiers and lifecycle metadata only; never prompts or credentials.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time
import uuid

from flask import current_app


TTL_SECONDS = 600
QUERY_CURSOR_TTL_SECONDS = 86400


def request_uuid(value):
    return str(uuid.UUID(str(value)))


@contextmanager
def _database():
    path = Path(current_app.config.get("SOFIA_REQUEST_DB") or
                Path(current_app.instance_path) / "sofia_chat_requests.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS chat_requests (
                request_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                started INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                cancelled INTEGER NOT NULL DEFAULT 0,
                execution_id TEXT, expires_at REAL NOT NULL
            )""")
            connection.execute("DELETE FROM chat_requests WHERE expires_at < ?", (time.time(),))
            connection.execute("""CREATE TABLE IF NOT EXISTS chat_query_cursors (
                owner TEXT NOT NULL, memory_session_id TEXT NOT NULL,
                query_started_at REAL NOT NULL, expires_at REAL NOT NULL,
                PRIMARY KEY(owner, memory_session_id)
            )""")
            connection.execute("DELETE FROM chat_query_cursors WHERE expires_at < ?", (time.time(),))
            yield connection
    finally:
        connection.close()


def begin(request_id, owner):
    """Reserve one invocation; an earlier stop wins even before chat arrives."""
    with _database() as db:
        db.execute("INSERT OR IGNORE INTO chat_requests(request_id, owner, expires_at) VALUES (?, ?, ?)",
                   (request_id, str(owner).casefold(), time.time() + TTL_SECONDS))
        changed = db.execute("""UPDATE chat_requests SET started = 1
            WHERE request_id = ? AND owner = ? AND started = 0""",
            (request_id, str(owner).casefold())).rowcount
        if not changed:
            raise ValueError("Identificador da consulta ja utilizado")
        return not bool(db.execute("SELECT cancel_requested FROM chat_requests WHERE request_id = ?",
                                   (request_id,)).fetchone()[0])


def cancel(request_id, owner):
    with _database() as db:
        # Tombstone handles clicking Stop before the original HTTP request arrives.
        db.execute("INSERT OR IGNORE INTO chat_requests(request_id, owner, expires_at) VALUES (?, ?, ?)",
                   (request_id, str(owner).casefold(), time.time() + TTL_SECONDS))
        changed = db.execute("""UPDATE chat_requests SET cancel_requested = 1
            WHERE request_id = ? AND owner = ?""", (request_id, str(owner).casefold())).rowcount
        if not changed:
            return None
        return dict(db.execute("SELECT * FROM chat_requests WHERE request_id = ?", (request_id,)).fetchone())


def get(request_id):
    with _database() as db:
        row = db.execute("SELECT * FROM chat_requests WHERE request_id = ?", (request_id,)).fetchone()
        return dict(row) if row else None


def register_execution(request_id, execution_id):
    with _database() as db:
        changed = db.execute("""UPDATE chat_requests SET execution_id = ?
            WHERE request_id = ? AND started = 1
            AND (execution_id IS NULL OR execution_id = ?)""",
            (execution_id, request_id, execution_id)).rowcount
        return bool(changed)


def confirm_cancelled(request_id):
    with _database() as db:
        db.execute("UPDATE chat_requests SET cancelled = 1 WHERE request_id = ?", (request_id,))


def query_time_context(owner, memory_session_id):
    """Trusted times of this message and the last answered message in this scope."""
    now = datetime.now(timezone.utc)
    with _database() as db:
        row = db.execute("""SELECT query_started_at FROM chat_query_cursors
            WHERE owner = ? AND memory_session_id = ?""",
            (str(owner).casefold(), memory_session_id)).fetchone()
    return {
        "query_started_at": now.isoformat(),
        "previous_answered_message_started_at": (
            datetime.fromtimestamp(row["query_started_at"], timezone.utc).isoformat() if row else None
        ),
    }


def record_answered_message(owner, memory_session_id, query_started_at):
    started = datetime.fromisoformat(query_started_at).timestamp()
    with _database() as db:
        db.execute("""INSERT INTO chat_query_cursors
            (owner, memory_session_id, query_started_at, expires_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(owner, memory_session_id) DO UPDATE SET
                query_started_at = excluded.query_started_at, expires_at = excluded.expires_at
            WHERE excluded.query_started_at > chat_query_cursors.query_started_at""",
            (str(owner).casefold(), memory_session_id, started, time.time() + QUERY_CURSOR_TTL_SECONDS))
