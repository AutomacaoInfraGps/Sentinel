"""Estado duravel dos jobs e eventos sanitizados da Revisao de Acessos."""
import json
from pathlib import Path
import sqlite3
import time
from queue import Full
from contextlib import contextmanager
from .settings import DATA_ROOT, ConfigurationError, load_settings


class JobStore:
    def __init__(self, root=DATA_ROOT):
        self.path = Path(root) / 'queue.sqlite3'

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL)')
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, job):
        try:
            settings = load_settings(self.path.parent)
            retention_days, max_events = settings['retention_days'], settings['max_events']
        except ConfigurationError:
            retention_days, max_events = 180, 1000
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload=excluded.payload',
                       (job['id'], job['created_at'], job['status'], json.dumps(job, ensure_ascii=False)))
            db.execute("DELETE FROM jobs WHERE state IN ('completed','failed') AND created < ?", (time.time() - retention_days * 86400,))
            db.execute("DELETE FROM jobs WHERE state IN ('completed','failed') AND id NOT IN (SELECT id FROM jobs WHERE state IN ('completed','failed') ORDER BY created DESC LIMIT ?)", (max_events,))

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def next_pending(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM jobs WHERE state='queued' ORDER BY created,rowid LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def pending_count(self):
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0]

    def enqueue(self, job, limit=100):
        """Conta e insere sob o mesmo lock SQLite, inclusive entre processos."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0]
            if count >= limit:
                raise Full()
            db.execute('INSERT INTO jobs VALUES (?,?,?,?)',
                       (job['id'], job['created_at'], 'queued', json.dumps(job, ensure_ascii=False)))
            return count + 1

    def interrupt_running(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM jobs WHERE state='running'").fetchall()
        for row in rows:
            job = json.loads(row[0])
            job.update(status='failed', message='Execucao interrompida pela parada do Sentinel.',
                       detail='Confira a sessao de captura antes de solicitar uma nova execucao.', updated_at=time.time())
            self.save(job)
