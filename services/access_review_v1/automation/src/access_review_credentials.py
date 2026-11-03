"""Resolve referencias no mesmo cofre DPAPI utilizado pelo Sentinel."""
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.secret_store import JsonSecretStore, SecretStoreError


def load_credentials(path, required, *, store=None):
    try:
        manifest = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(manifest, dict):
            raise ValueError()
        refs = {}
        for name in required:
            entry = manifest.get(name)
            if not isinstance(entry, dict) or set(entry) != {'credential_ref'} or not isinstance(entry['credential_ref'], str):
                raise ValueError()
            refs[name] = entry['credential_ref']
        vault = store or JsonSecretStore()
        values = vault.get_many(list(refs.values()))
        return {name: values[ref] for name, ref in refs.items()}
    except (OSError, ValueError, KeyError, SecretStoreError) as exc:
        raise ValueError('Credenciais da area indisponiveis no cofre do Sentinel.') from None
