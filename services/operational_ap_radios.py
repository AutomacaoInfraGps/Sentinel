"""Opt-in native RF polling of the local UniFi publication; no equipment queries."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import threading

from core.secret_store import _InterprocessFileLock
from scripts.database.capture_ap_radio_catalog import capture_payload, summary, _encode
from scripts.database.import_ap_radio_catalog import build_catalog
from scripts.database.import_firewall_cache import ImportErrorSafe
from scripts.database.sync_ap_radio_catalog import write_catalog
from services.operational_postgres import PROJECT_ROOT, _safe_warning, connect_collector, shadow_enabled

CONFIG_PATH = PROJECT_ROOT / 'instance/operational-postgres-ap-radios-shadow.json'
SOURCE_PATH = PROJECT_ROOT / 'data/unifi.json'
PUBLICATION_PATH = PROJECT_ROOT / 'output/ap_radios_postgres_sync_status.json'
LOCK_PATH = PROJECT_ROOT / 'instance/ap-radios-shadow.lock'
POLL_SECONDS = 300
_worker = None
_worker_lock = threading.Lock()


def automatic_enabled():
    return os.environ.get('COMPUTERNAME', '').upper() == 'RIGEL' and shadow_enabled(CONFIG_PATH)


def read_current_catalog(captured_at=None):
    raw = SOURCE_PATH.read_bytes()
    payload = capture_payload(raw, captured_at or datetime.now(timezone.utc))
    catalog = build_catalog(_encode(payload))
    if SOURCE_PATH.read_bytes() != raw:
        raise ImportErrorSafe('Fonte RF mudou durante a leitura. Banco preservado.')
    return catalog


def save_status(catalog, mode, path=None):
    path = Path(path or PUBLICATION_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only the validated summary is public: no AP identities or native response.
    status = {**summary(catalog.payload), 'modo': mode, 'postgresql_acessado': True,
              'vinculos_sql_conferidos': True, 'sincronizacao_automatica_radios': True,
              'confirmado_em_utc': datetime.now(timezone.utc).isoformat()}
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.ap-radios-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(status, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def poll_ap_radios(logger):
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
                    raise ImportErrorSafe('Espelhamento RF desabilitado antes de confirmar transacao.')
            save_status(catalog, mode)
        return True
    except Exception as exc:
        _safe_warning(logger, 'falha_sincronizacao_radios_unifi', exc)
        return False


def start_ap_radio_sync_worker(logger=None):
    global _worker
    logger = logger or logging.getLogger(__name__)
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return _worker

        def run():
            while True:
                poll_ap_radios(logger)
                threading.Event().wait(POLL_SECONDS)

        _worker = threading.Thread(target=run, name='sentinel-ap-radios-shadow', daemon=True)
        _worker.start()
        return _worker
