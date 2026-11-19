"""Opt-in firmware inventory polling; never imports scheduler or queries equipment."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import threading

from core.secret_store import _InterprocessFileLock
from scripts.database.capture_switch_firmware_catalog import capture
from scripts.database.import_firewall_cache import ImportErrorSafe
from scripts.database.import_switch_firmware_catalog import build_catalog
from scripts.database.sync_switch_firmware_catalog import write_catalog
from services.operational_postgres import PROJECT_ROOT, _safe_warning, connect_collector, shadow_enabled

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-firmware-shadow.json'
DATABASE_PATH = PROJECT_ROOT / 'data/switch_updates/scheduled_updates.sqlite3'
CACHE_PATH = PROJECT_ROOT / 'output/switches_status_cache.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/firmware_postgres_sync_status.json'
LOCK_PATH = PROJECT_ROOT / 'instance/firmware-shadow.lock'
POLL_SECONDS = 300
_worker = None
_worker_lock = threading.Lock()


def automatic_enabled():
    return os.environ.get('COMPUTERNAME', '').upper() == 'RIGEL' and shadow_enabled(CONFIG_PATH)


def read_current_catalog(captured_at=None):
    now = captured_at or datetime.now(timezone.utc)
    payload = capture(DATABASE_PATH, CACHE_PATH, now=now)
    catalog = build_catalog(json.dumps(payload, ensure_ascii=True).encode())
    if any(row[8] > now for row in catalog.rows):
        raise ImportErrorSafe('Inventario com consulta declarada futura. Banco preservado.')
    return catalog


def save_status(catalog, mode, path=None):
    path = Path(path or PUBLICATION_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only hashes/counts and declared times: no raw inventory is published here.
    status = {**catalog.report, 'modo': mode, 'postgresql_acessado': True,
              'sincronizacao_automatica_firmware': True,
              'confirmado_em_utc': datetime.now(timezone.utc).isoformat()}
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.firmware-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(status, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def poll_firmware_catalog(logger):
    if not automatic_enabled():
        return False
    try:
        with _InterprocessFileLock(LOCK_PATH, timeout=0.25):
            if not automatic_enabled():
                return False
            catalog = read_current_catalog()
            if not automatic_enabled():
                return False
            with connect_collector() as connection:
                mode = write_catalog(connection, catalog)
                if not automatic_enabled():
                    raise ImportErrorSafe('Espelhamento desabilitado antes de confirmar transacao.')
            save_status(catalog, mode)
        return True
    except Exception as exc:
        _safe_warning(logger, 'falha_sincronizacao_firmware_switches', exc)
        return False


def start_firmware_sync_worker(logger=None):
    global _worker
    logger = logger or logging.getLogger(__name__)
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return _worker

        def run():
            while True:
                poll_firmware_catalog(logger)
                threading.Event().wait(POLL_SECONDS)

        _worker = threading.Thread(target=run, name='sentinel-firmware-shadow', daemon=True)
        _worker.start()
        return _worker
