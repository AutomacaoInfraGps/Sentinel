"""Load Sentinel environment configuration with optional secret references."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping, Protocol

from core.secret_store import JsonSecretStore, SecretStoreError


CREDENTIAL_REFERENCE_KEY = "credential_ref"
SECRET_FIELD_NAMES = {
    "api_key",
    "apikey",
    "client_secret",
    "community",
    "pass",
    "passwd",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "senha",
    "token",
}


class EnvironmentConfigError(RuntimeError):
    """Configuration error whose message never contains credential values."""


class SecretReader(Protocol):
    def get(self, reference: str) -> str: ...


def is_credential_reference(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {CREDENTIAL_REFERENCE_KEY}
        and isinstance(value.get(CREDENTIAL_REFERENCE_KEY), str)
        and bool(value[CREDENTIAL_REFERENCE_KEY].strip())
    )


def contains_credential_reference(value: object) -> bool:
    if is_credential_reference(value):
        return True
    if isinstance(value, dict):
        return any(contains_credential_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_credential_reference(child) for child in value)
    return False


def redact_environment_secrets(value: object) -> object:
    """Return a copy safe to render in configuration forms."""
    if isinstance(value, dict):
        return {
            key: "" if str(key).strip().lower() in SECRET_FIELD_NAMES else redact_environment_secrets(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_environment_secrets(child) for child in value]
    return deepcopy(value)


def resolve_credential_references(
    payload: object,
    *,
    secret_store: SecretReader,
    resolved_secrets: Mapping[str, str] | None = None,
) -> object:
    """Return a copy of a JSON value with credential references resolved in memory."""
    if is_credential_reference(payload):
        reference = payload[CREDENTIAL_REFERENCE_KEY].strip()
        try:
            if resolved_secrets is not None and reference in resolved_secrets:
                return resolved_secrets[reference]
            return secret_store.get(reference)
        except SecretStoreError as exc:
            raise EnvironmentConfigError(
                "Uma credencial referenciada pelo ambiente nao esta disponivel."
            ) from exc
    if isinstance(payload, dict):
        return {
            key: resolve_credential_references(
                value,
                secret_store=secret_store,
                resolved_secrets=resolved_secrets,
            )
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [
            resolve_credential_references(
                value,
                secret_store=secret_store,
                resolved_secrets=resolved_secrets,
            )
            for value in payload
        ]
    return deepcopy(payload)


def load_environment_file(
    path: str | Path,
    *,
    resolve_secrets: bool = True,
    secret_store: SecretReader | None = None,
) -> dict:
    """Load environment JSON while preserving compatibility with inline secrets."""
    source = Path(path)
    if not source.is_file():
        return {}
    try:
        with source.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise EnvironmentConfigError(
            "O arquivo environment.json nao pode ser carregado."
        ) from exc
    if not isinstance(payload, dict):
        raise EnvironmentConfigError(
            "O arquivo environment.json deve conter um objeto JSON."
        )
    if not resolve_secrets:
        return payload
    if not contains_credential_reference(payload):
        return payload
    store = secret_store or JsonSecretStore()
    resolved = resolve_credential_references(payload, secret_store=store)
    return resolved if isinstance(resolved, dict) else {}


def save_environment_file(path: str | Path, payload: dict) -> None:
    """Atomically persist a raw environment configuration."""
    if not isinstance(payload, dict):
        raise EnvironmentConfigError("A configuracao do ambiente deve ser um objeto JSON.")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".environment-",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    except OSError as exc:
        raise EnvironmentConfigError(
            "O arquivo environment.json nao pode ser salvo."
        ) from exc
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
