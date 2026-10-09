"""Encrypted local secret storage for Sentinel credentials."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol

from filelock import FileLock


STORE_VERSION = 1
DEFAULT_STORE_PATH = Path(__file__).resolve().parents[1] / ".credentials" / "sentinel-secrets.json"
_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")


class SecretStoreError(RuntimeError):
    """Base error that never includes secret values."""


class SecretNotFoundError(SecretStoreError):
    """Raised when a credential reference does not exist."""


class SecretProtector(Protocol):
    name: str

    def protect(self, secret: str) -> bytes: ...

    def unprotect(self, protected: bytes) -> str: ...


class DpapiCurrentUserProtector:
    """Protect secrets with Windows DPAPI for the current Windows account."""

    name = "windows-dpapi-current-user"
    _ENTROPY = b"Sentinel/secret-store/v1"
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise SecretStoreError("DPAPI esta disponivel somente no Windows.")
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(self._DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(self._DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(self._DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(self._DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(self._DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(self._DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    @classmethod
    def _blob(cls, data: bytes):
        buffer = ctypes.create_string_buffer(data)
        blob = cls._DataBlob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        return blob, buffer

    @staticmethod
    def _raise_last_error(operation: str) -> None:
        error = ctypes.get_last_error()
        raise SecretStoreError(
            f"Falha do Windows ao {operation} uma credencial (erro {error})."
        )

    def protect(self, secret: str) -> bytes:
        if not isinstance(secret, str) or not secret:
            raise SecretStoreError("O segredo nao pode ficar vazio.")
        source, source_buffer = self._blob(secret.encode("utf-8"))
        entropy, entropy_buffer = self._blob(self._ENTROPY)
        output = self._DataBlob()
        _ = (source_buffer, entropy_buffer)
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source),
            "Credencial persistente do Sentinel",
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        ):
            self._raise_last_error("proteger")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def unprotect(self, protected: bytes) -> str:
        if not protected:
            raise SecretStoreError("A credencial protegida esta vazia.")
        source, source_buffer = self._blob(bytes(protected))
        entropy, entropy_buffer = self._blob(self._ENTROPY)
        output = self._DataBlob()
        _ = (source_buffer, entropy_buffer)
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        ):
            self._raise_last_error("recuperar")
        try:
            return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecretStoreError("A credencial protegida esta corrompida.") from exc
        finally:
            self._kernel32.LocalFree(output.pbData)


class JsonSecretStore:
    """Atomic encrypted store addressed by non-secret credential references."""

    def __init__(
        self,
        path: Path | str = DEFAULT_STORE_PATH,
        *,
        protector: SecretProtector | None = None,
    ) -> None:
        self.path = Path(path)
        self.protector = protector or DpapiCurrentUserProtector()
        self.lock_path = Path(f"{self.path}.lock")

    @staticmethod
    def _validate_reference(reference: str) -> str:
        normalized = str(reference or "").strip()
        if not _REFERENCE_PATTERN.fullmatch(normalized) or ".." in normalized:
            raise SecretStoreError("Referencia de credencial invalida.")
        return normalized

    def _empty_payload(self) -> dict:
        return {
            "version": STORE_VERSION,
            "protection": self.protector.name,
            "entries": {},
        }

    def _load_unlocked(self) -> dict:
        if not self.path.exists():
            return self._empty_payload()
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretStoreError("O cofre de credenciais nao pode ser lido.") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != STORE_VERSION
            or payload.get("protection") != self.protector.name
            or not isinstance(payload.get("entries"), dict)
        ):
            raise SecretStoreError("O formato do cofre de credenciais e invalido.")
        return payload

    def _save_unlocked(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".sentinel-secrets-",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def put(self, reference: str, secret: str) -> None:
        reference = self._validate_reference(reference)
        protected = self.protector.protect(secret)
        encoded = base64.b64encode(protected).decode("ascii")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.lock_path)):
            payload = self._load_unlocked()
            payload["entries"][reference] = {
                "ciphertext": encoded,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save_unlocked(payload)

    def get(self, reference: str) -> str:
        reference = self._validate_reference(reference)
        with FileLock(str(self.lock_path)):
            entry = self._load_unlocked()["entries"].get(reference)
        if not isinstance(entry, dict) or not isinstance(entry.get("ciphertext"), str):
            raise SecretNotFoundError("Credencial nao encontrada no cofre.")
        try:
            protected = base64.b64decode(entry["ciphertext"], validate=True)
        except (ValueError, TypeError) as exc:
            raise SecretStoreError("A credencial protegida esta corrompida.") from exc
        return self.protector.unprotect(protected)

    def contains(self, reference: str) -> bool:
        reference = self._validate_reference(reference)
        with FileLock(str(self.lock_path)):
            return reference in self._load_unlocked()["entries"]

    def delete(self, reference: str) -> bool:
        reference = self._validate_reference(reference)
        with FileLock(str(self.lock_path)):
            payload = self._load_unlocked()
            removed = payload["entries"].pop(reference, None) is not None
            if removed:
                self._save_unlocked(payload)
            return removed
