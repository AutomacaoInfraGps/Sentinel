from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .contracts import (
    DirectoryObject,
    DirectoryResolution,
    DirectoryResolutionStatus,
)


class DirectoryTemporaryError(RuntimeError):
    """Falha transitória do diretório, sem detalhes potencialmente sensíveis."""


class DirectoryPermanentError(RuntimeError):
    """Falha permanente de configuração ou resposta do diretório."""


@dataclass(frozen=True)
class DirectoryRecord:
    sid: str
    account_name: str | None
    domain_name: str | None
    display_name: str | None
    object_classes: tuple[str, ...]


class DirectoryLookupClient(Protocol):
    def lookup_sid(self, sid: str, sid_bytes: bytes) -> tuple[DirectoryRecord, ...]: ...


def sid_to_bytes(sid: str) -> bytes:
    """Converte a representação SDDL de um SID para o valor binário do AD."""
    if not isinstance(sid, str):
        raise ValueError("SID deve ser texto")
    parts = sid.strip().split("-")
    if len(parts) < 4 or parts[0].casefold() != "s":
        raise ValueError("SID inválido")
    try:
        revision = int(parts[1], 10)
        authority = int(parts[2], 0)
        subauthorities = [int(value, 0) for value in parts[3:]]
    except ValueError as exc:
        raise ValueError("SID inválido") from exc
    if not 0 <= revision <= 0xFF:
        raise ValueError("Revisão do SID inválida")
    if not 0 <= authority <= 0xFFFFFFFFFFFF:
        raise ValueError("Autoridade do SID inválida")
    if not 1 <= len(subauthorities) <= 15:
        raise ValueError("Quantidade de subautoridades do SID inválida")
    if any(not 0 <= value <= 0xFFFFFFFF for value in subauthorities):
        raise ValueError("Subautoridade do SID inválida")
    return (
        bytes((revision, len(subauthorities)))
        + authority.to_bytes(6, byteorder="big")
        + b"".join(struct.pack("<I", value) for value in subauthorities)
    )


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    resolution: DirectoryResolution


class CachingDirectoryResolver:
    """Resolve SIDs com cache TTL sobre um cliente de diretório substituível."""

    def __init__(
        self,
        client: DirectoryLookupClient,
        *,
        cache_ttl_seconds: float = 300,
        cache_max_entries: int = 2048,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds deve ser maior que zero")
        if cache_max_entries < 1:
            raise ValueError("cache_max_entries deve ser maior que zero")
        self.client = client
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.cache_max_entries = cache_max_entries
        self.clock = clock
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()

    def resolve_sid(self, sid: str) -> DirectoryResolution:
        normalized_sid = sid.strip().upper() if isinstance(sid, str) else ""
        try:
            binary_sid = sid_to_bytes(normalized_sid)
        except ValueError:
            return DirectoryResolution(
                DirectoryResolutionStatus.PERMANENT_FAILURE,
                error_code="invalid_sid",
            )

        now = self.clock()
        cached = self._cache.get(normalized_sid)
        if cached is not None:
            if cached.expires_at > now:
                self._cache.move_to_end(normalized_sid)
                return cached.resolution
            del self._cache[normalized_sid]

        try:
            records = self.client.lookup_sid(normalized_sid, binary_sid)
        except DirectoryTemporaryError:
            return DirectoryResolution(
                DirectoryResolutionStatus.TEMPORARY_FAILURE,
                error_code="directory_unavailable",
            )
        except DirectoryPermanentError:
            return DirectoryResolution(
                DirectoryResolutionStatus.PERMANENT_FAILURE,
                error_code="directory_configuration_or_query_error",
            )

        if not records:
            resolution = DirectoryResolution(
                DirectoryResolutionStatus.NOT_FOUND,
                error_code="sid_not_found",
            )
        elif len(records) != 1:
            resolution = DirectoryResolution(
                DirectoryResolutionStatus.PERMANENT_FAILURE,
                error_code="ambiguous_sid",
            )
        else:
            record = records[0]
            classes = {value.casefold() for value in record.object_classes}
            if "user" not in classes or "computer" in classes:
                resolution = DirectoryResolution(
                    DirectoryResolutionStatus.PERMANENT_FAILURE,
                    error_code="object_not_user",
                )
            elif not record.account_name or not record.account_name.strip():
                resolution = DirectoryResolution(
                    DirectoryResolutionStatus.PERMANENT_FAILURE,
                    error_code="account_name_missing",
                )
            else:
                resolution = DirectoryResolution(
                    DirectoryResolutionStatus.RESOLVED,
                    DirectoryObject(
                        sid=normalized_sid,
                        account_name=record.account_name.strip(),
                        object_type="user",
                        domain_name=(
                            record.domain_name.strip() if record.domain_name else None
                        ),
                        display_name=(
                            record.display_name.strip() if record.display_name else None
                        ),
                    ),
                )

        # Falhas temporárias nunca entram no cache. Resultados determinísticos
        # reduzem consultas repetidas sem tornar indisponibilidade transitória durável.
        self._cache[normalized_sid] = _CacheEntry(
            now + self.cache_ttl_seconds,
            resolution,
        )
        self._cache.move_to_end(normalized_sid)
        while len(self._cache) > self.cache_max_entries:
            self._cache.popitem(last=False)
        return resolution


_ADWS_LOOKUP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$credential = $null

function Write-Result([hashtable]$Payload) {
    $Payload | ConvertTo-Json -Compress -Depth 3
}

try {
    Import-Module ActiveDirectory -ErrorAction Stop
    $sid = [string]$env:ALERTAD_ADWS_LOOKUP_SID
    if ([string]::IsNullOrWhiteSpace($sid)) {
        Write-Result @{ status = 'permanent_failure'; error_code = 'invalid_sid' }
        exit 0
    }

    $arguments = @{
        Identity = $sid
        Properties = @('DisplayName', 'UserPrincipalName', 'msDS-PrincipalName')
        ErrorAction = 'Stop'
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ALERTAD_ADWS_SERVER)) {
        $arguments.Server = $env:ALERTAD_ADWS_SERVER
    }
    if ($env:ALERTAD_ADWS_INTERACTIVE -eq '1') {
        $credential = Get-Credential -Message 'Credencial temporaria para consulta somente leitura ao AD'
        if ($null -eq $credential) {
            Write-Result @{ status = 'permanent_failure'; error_code = 'credential_cancelled' }
            exit 0
        }
        $arguments.Credential = $credential
    }

    $user = Get-ADUser @arguments
    $principal = [string]$user.'msDS-PrincipalName'
    $domain = $null
    if ($principal.Contains('\')) {
        $domain = $principal.Split('\', 2)[0]
    } elseif ([string]$user.UserPrincipalName -match '@') {
        $domain = ([string]$user.UserPrincipalName).Split('@', 2)[1]
    }
    Write-Result @{
        status = 'resolved'
        account_name = [string]$user.SamAccountName
        display_name = [string]$user.DisplayName
        domain_name = $domain
    }
} catch {
    $exceptionName = $_.Exception.GetType().FullName
    if ($exceptionName -match 'ADIdentityNotFound') {
        Write-Result @{ status = 'not_found'; error_code = 'sid_not_found' }
    } elseif ($exceptionName -match 'ServerDown|Timeout|Socket|Communication|Unavailable|Busy') {
        Write-Result @{ status = 'temporary_failure'; error_code = 'directory_unavailable' }
    } else {
        Write-Result @{ status = 'permanent_failure'; error_code = 'directory_query_failed' }
    }
} finally {
    if ($null -ne $credential) {
        $credential = $null
    }
}
"""


class PowerShellADWSLookupClient:
    """Consulta Get-ADUser localmente usando ADWS e a identidade do processo."""

    def __init__(
        self,
        *,
        server: str | None = None,
        timeout_seconds: float = 30,
        interactive_credentials: bool = False,
        process_runner: Callable[..., object] | None = None,
        powershell_executable: str | Path | None = None,
    ) -> None:
        if server is not None:
            if not isinstance(server, str) or not server.strip():
                raise ValueError("Servidor ADWS deve ser texto não vazio ou null")
            server = server.strip()
            if "://" in server or any(character.isspace() for character in server):
                raise ValueError("Servidor ADWS deve conter somente o hostname")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ) or not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("Timeout ADWS deve ser finito e maior que zero")
        if not isinstance(interactive_credentials, bool):
            raise ValueError("interactive_credentials deve ser booleano")
        self.server = server
        self.timeout_seconds = float(timeout_seconds)
        self.interactive_credentials = interactive_credentials
        self.process_runner = process_runner or subprocess.run
        if powershell_executable is None:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            powershell_executable = (
                Path(system_root)
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
        self.powershell_executable = str(powershell_executable)

    @staticmethod
    def _optional_text(payload: dict[str, object], name: str) -> str | None:
        value = payload.get(name)
        text = str(value).strip() if value is not None else ""
        return text or None

    def lookup_sid(self, sid: str, sid_bytes: bytes) -> tuple[DirectoryRecord, ...]:
        del sid_bytes  # A validação binária ocorre no resolvedor antes da consulta.
        environment = os.environ.copy()
        environment["ALERTAD_ADWS_LOOKUP_SID"] = sid
        environment["ALERTAD_ADWS_INTERACTIVE"] = (
            "1" if self.interactive_credentials else "0"
        )
        if self.server:
            environment["ALERTAD_ADWS_SERVER"] = self.server
        else:
            environment.pop("ALERTAD_ADWS_SERVER", None)
        command = [
            self.powershell_executable,
            "-NoLogo",
            "-NoProfile",
        ]
        if not self.interactive_credentials:
            command.append("-NonInteractive")
        command.extend(("-Command", _ADWS_LOOKUP_SCRIPT))
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if not self.interactive_credentials
            else 0
        )
        try:
            completed = self.process_runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                env=environment,
                creationflags=creationflags,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DirectoryTemporaryError("adws_timeout") from exc
        except OSError as exc:
            raise DirectoryPermanentError("powershell_unavailable") from exc

        if getattr(completed, "returncode", 1) != 0:
            raise DirectoryPermanentError("adws_process_failed")
        stdout = str(getattr(completed, "stdout", "")).lstrip("\ufeff").strip()
        try:
            payload = json.loads(stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise DirectoryPermanentError("adws_invalid_response") from exc
        if not isinstance(payload, dict):
            raise DirectoryPermanentError("adws_invalid_response")

        status = payload.get("status")
        if status == "not_found":
            return ()
        if status == "temporary_failure":
            raise DirectoryTemporaryError("adws_unavailable")
        if status == "permanent_failure":
            raise DirectoryPermanentError("adws_query_failed")
        if status != "resolved":
            raise DirectoryPermanentError("adws_invalid_response")

        account_name = self._optional_text(payload, "account_name")
        if account_name is None:
            raise DirectoryPermanentError("adws_account_name_missing")
        return (
            DirectoryRecord(
                sid=sid,
                account_name=account_name,
                domain_name=self._optional_text(payload, "domain_name"),
                display_name=self._optional_text(payload, "display_name"),
                object_classes=("user",),
            ),
        )
