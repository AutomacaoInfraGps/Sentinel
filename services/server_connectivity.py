"""Shared ICMP observations. Readers never contact equipment or load credentials."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from time import monotonic

from core.secret_store import _InterprocessFileLock


ROOT = Path(__file__).resolve().parents[1] / 'output' / 'server_connectivity'
POOL = ThreadPoolExecutor(max_workers=5, thread_name_prefix='server-ping')
REUSE_SECONDS = 30
FIELDS = ('status', 'tempo_resposta', 'erro', 'ultima_verificacao', 'coletado_em',
          'coleta_status_confirmada', 'coleta_status_origem', 'erro_coleta_codigo')


def _path(ip):
    address = str(ipaddress.ip_address(str(ip).strip()))
    return ROOT / (sha256(address.encode('ascii')).hexdigest() + '.json')


def _read(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return None
        stamp = datetime.fromisoformat(data['tentativa_em'])
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
            return None
        if type(data.get('coleta_status_confirmada')) is not bool:
            return None
        if data.get('coleta_status_origem') != 'icmp_ping':
            return None
        if 'status' in data and data['status'] not in ('online', 'offline'):
            return None
        for field in ('ultima_verificacao', 'coletado_em'):
            if data.get(field) is not None:
                checked = datetime.fromisoformat(data[field])
                if checked.tzinfo is None:
                    return None
        if data['coleta_status_confirmada'] and not data.get('coletado_em'):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.ping-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_observation(ip):
    try:
        return _read(_path(ip))
    except ValueError:
        return None


def _collect(ip):
    from vm_manager import verificar_vm_online

    path = _path(ip)
    # Recheck after locking: concurrent callers share even an unsuccessful attempt.
    with _InterprocessFileLock(path.with_suffix('.lock'), timeout=30):
        previous = _read(path)
        if previous:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous['tentativa_em'])).total_seconds()
            if age < REUSE_SECONDS:
                return previous
        evidence = {}
        started = monotonic()
        online = verificar_vm_online(str(ip).strip(), evidencia=evidence)
        observation = {
            'tentativa_em': datetime.now(timezone.utc).isoformat(),
            **evidence,
        }
        if evidence.get('coleta_status_confirmada') is True:
            observation.update(
                status='online' if online else 'offline',
                tempo_resposta=round(monotonic() - started, 2),
                erro=None if online else 'Timeout',
                ultima_verificacao=evidence['coletado_em'],
            )
        elif previous:
            # A failed probe must not erase the last confirmed observation.
            for field in ('status', 'tempo_resposta', 'erro', 'ultima_verificacao'):
                if field in previous:
                    observation[field] = previous[field]
        _write(path, observation)
        return observation


def submit(ip):
    return POOL.submit(_collect, ip)


def collect(ip):
    return submit(ip).result()


def project(server):
    """Overlay observations, preserving identity, maintenance and legacy fallback."""
    item = dict(server)
    observation = read_observation(item.get('ip'))
    if not observation:
        return item
    previous = item.get('ultima_verificacao')
    observed = observation.get('ultima_verificacao')
    if previous and observed:
        try:
            before = datetime.fromisoformat(str(previous))
            after = datetime.fromisoformat(observed)
            if before.tzinfo is None:
                before = before.astimezone()
            if before > after:
                return item
        except (TypeError, ValueError):
            return item
    protected = item.get('ativo') is False or item.get('em_manutencao') is True or str(item.get('status')).lower() in {
        'maintenance', 'inativo', 'inactive', 'disabled',
    }
    for field in FIELDS:
        if field in observation and not (protected and field == 'status'):
            item[field] = observation[field]
    if observation.get('coleta_status_confirmada') is not True:
        item.setdefault('tempo_resposta', None)
        item['erro'] = 'Coleta de conectividade nao confirmada'
    item['tentativa_conectividade_em'] = observation['tentativa_em']
    item['conectividade_desatualizada'] = (
        observation.get('coleta_status_confirmada') is not True or not observed or
        (datetime.now(timezone.utc) - datetime.fromisoformat(observed)).total_seconds() > 300
    )
    return item


def verificar_online(ip, evidencia=None):
    """Checklist adapter. Reuses only short-lived observations, never hardware."""
    observation = collect(ip)
    if evidencia is not None:
        evidencia.clear()
        evidencia.update({field: observation.get(field) for field in (
            'coleta_status_confirmada', 'coletado_em', 'coleta_status_origem', 'erro_coleta_codigo',
            'tempo_resposta', 'ultima_verificacao',
        )})
    return observation.get('coleta_status_confirmada') is True and observation.get('status') == 'online'
