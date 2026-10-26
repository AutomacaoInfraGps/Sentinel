"""Fila FIFO persistente com consumidor unico entre processos do Sentinel."""
from queue import Full
from threading import Event, RLock, Thread
import time
import sqlite3
from filelock import FileLock, Timeout
from .persistence import JobStore
from .settings import DATA_ROOT


class AccessReviewStorageError(RuntimeError):
    pass


class AccessReviewQueue:
    def __init__(self, root=DATA_ROOT):
        self.root = root
        self.store = JobStore(root)
        self._lock = RLock()
        self._worker = None
        self._stop = Event()

    def enqueue(self, job_id, mode, areas, handler, job=None, restore=None):
        with self._lock:
            now = time.time()
            job = job or {'id': job_id, 'kind': 'revisao_acessos', 'status': 'queued', 'created_at': now,
                          'updated_at': now, 'meta': {'mode': mode, 'audits': list(areas), 'events': []}}
            try:
                position = self.store.enqueue(job)
            except (OSError, sqlite3.Error) as exc:
                raise AccessReviewStorageError('Fila da Revisao de Acessos indisponivel.') from None
            self.start(handler, restore)
            return position

    def start(self, handler, restore=None):
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = Thread(target=self._consume, args=(handler, restore), name='revisao-acessos-fila', daemon=True)
                self._worker.start()

    def _consume(self, handler, restore):
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        leader = FileLock(str(self.store.path.with_suffix('.worker.lock')))
        try:
            with leader.acquire(timeout=0):
                self.store.interrupt_running()
                while not self._stop.is_set():
                    job = self.store.next_pending()
                    if job is None:
                        self._stop.wait(1)
                        continue
                    job.update(status='running', updated_at=time.time())
                    self.store.save(job)
                    if restore:
                        restore(job)
                    try:
                        handler(job['id'], job['meta']['mode'], job['meta']['audits'])
                        latest = self.store.get(job['id'])
                        if latest['status'] == 'running':
                            latest.update(status='completed', updated_at=time.time())
                            self.store.save(latest)
                    except Exception:
                        job.update(status='failed', message='Falha interna ao executar a revisao.', updated_at=time.time())
                        self.store.save(job)
        except Timeout:
            return

    def close(self):
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=5)


access_review_queue = AccessReviewQueue()
