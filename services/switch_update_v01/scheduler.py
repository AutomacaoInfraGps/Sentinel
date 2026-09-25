"""Agendador persistente e seguro para atualizacoes de switches.

Projetado para executar no servidor Windows que hospeda o Sentinel.
Metadados ficam em SQLite; a senha fica cifrada pelo DPAPI da maquina Windows e e
apagada do banco assim que o job termina, falha ou e cancelado.
"""

from __future__ import annotations

import argparse
import calendar
from contextlib import closing
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from getpass import getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
from threading import Event, Lock, Thread
import time
from typing import Callable, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # pacote copiado para services/switch_update_v01 no Sentinel
    from .main import (
        ArubaWebUpdater,
        ProgressReporter,
        UpdateAssessment,
        UpdateError,
        UpdateNeedsReview,
        assess_update,
        build_parser,
        concise_exception_message,
        final_version_matches,
        fetch_web_identity,
        release_version,
        run,
    )
except ImportError:  # execucao direta neste repositorio
    from main import (
        ArubaWebUpdater,
        ProgressReporter,
        UpdateAssessment,
        UpdateError,
        UpdateNeedsReview,
        assess_update,
        build_parser,
        concise_exception_message,
        final_version_matches,
        fetch_web_identity,
        release_version,
        run,
    )


LOGGER = logging.getLogger("att-switches.scheduler")
try:
    BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
    TZDATA_AVAILABLE = True
except ZoneInfoNotFoundError:  # Windows sem o pacote tzdata
    BRASILIA_TZ = timezone(timedelta(hours=-3), name="America/Sao_Paulo")
    TZDATA_AVAILABLE = False
UTC = timezone.utc
FINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "reviewed"})
VALID_DECISIONS = frozenset({"update", "same_version", "downgrade"})
MIN_UPDATE_ATTEMPTS = 1
MAX_UPDATE_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 5 * 60
RETRYABLE_RESULT_CODES = frozenset({"SWU200", "SWU220", "SWU300", "SWU310", "SWU320"})
MONTH_FOLDERS = (
    "",
    "Jan",
    "Fev",
    "Mar",
    "Abr",
    "Mai",
    "Jun",
    "Jul",
    "Ago",
    "Set",
    "Out",
    "Nov",
    "Dez",
)
LATE_SUCCESS_MESSAGE = (
    "Update realizado porém o retorno foi após o tempo esperado, "
    "consulte a integridade do switch"
)
FRIENDLY_STAGE_MESSAGES = {
    "starting": "Preparando a atualização.",
    "identity": "Conferindo o equipamento e as versões.",
    "authentication": "Entrando na página de administração do switch.",
    "upload_setup": "Preparando o envio do arquivo de atualização.",
    "transfer": "Enviando o arquivo de atualização para o switch.",
    "restart": "Arquivo enviado. O switch está sendo reiniciado.",
    "waiting_ping": "Aguardando o switch voltar a responder.",
    "verifying_web": "Confirmando a versão instalada.",
    "saving": "Salvando a configuração do switch.",
    "complete": "Atualização confirmada.",
}
FRIENDLY_FAILURE_MESSAGES = {
    "starting": "Não foi possível preparar a atualização.",
    "identity": "Não foi possível confirmar o equipamento ou a versão instalada.",
    "authentication": "Não foi possível entrar na página de administração do switch.",
    "upload_setup": "Não foi possível preparar o envio do arquivo ao switch.",
    "transfer": "O envio do arquivo de atualização não foi concluído.",
    "restart": "Não foi possível confirmar o comando de reinicialização.",
    "waiting_ping": "O switch não voltou a responder dentro do tempo esperado.",
    "verifying_web": "O switch respondeu, mas a versão instalada não pôde ser confirmada.",
    "saving": "A versão foi confirmada, mas não foi possível confirmar o salvamento final.",
}
RESULT_CODES = {
    "SWU000": "Atualização concluída e versão confirmada",
    "SWU090": "Agendamento cancelado antes da execução",
    "SWU110": "Equipamento, modelo ou versão incompatível",
    "SWU120": "Arquivo reservado ausente ou alterado",
    "SWU200": "Switch inacessível antes da transferência",
    "SWU210": "Falha na autenticação do switch",
    "SWU220": "Sessão do switch expirada",
    "SWU300": "Falha ao navegar pela página de atualização",
    "SWU310": "Falha ao anexar o arquivo de atualização",
    "SWU320": "Falha ou timeout na transferência do arquivo",
    "SWU400": "Falha ao solicitar a reinicialização",
    "SWU410": "Retorno não confirmado em até sete minutos",
    "SWU411": "Atualização confirmada após retorno tardio",
    "SWU420": "Página do switch indisponível após o retorno do ping",
    "SWU430": "Versão final diferente da esperada",
    "SWU440": "Falha ao confirmar o salvamento da configuração",
    "SWU500": "Falha interna ou de preparação do processo",
    "SWU510": "Serviço interrompido durante a atualização",
    "SWU520": "Credencial protegida indisponível ou inválida",
}


class ScheduleError(RuntimeError):
    """Erro seguro do agendador que pode ser apresentado ao operador."""


class ScheduleConflictError(ScheduleError):
    """A operacao e valida, mas conflita com o estado atual da fila/switch."""


class CredentialProtector(Protocol):
    def protect(self, secret: str) -> bytes: ...

    def unprotect(self, protected: bytes) -> str: ...


class DpapiCredentialProtector:
    """Protege segredos com DPAPI, vinculados ao servidor Windows."""

    _ENTROPY = b"ATT-Switches/scheduler/v0.1"
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _CRYPTPROTECT_LOCAL_MACHINE = 0x4

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    def __init__(self) -> None:
        if os.name != "nt":
            raise ScheduleError("DPAPI exige Windows; execute o agendador no servidor do Sentinel.")
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

    def _raise_last_error(self, operation: str) -> None:
        error = ctypes.get_last_error()
        raise ScheduleError(f"Falha do Windows ao {operation} a credencial (erro {error}).")

    def protect(self, secret: str) -> bytes:
        if not secret:
            raise ScheduleError("A senha do switch nao pode ficar vazia.")
        source, source_buffer = self._blob(secret.encode("utf-8"))
        entropy, entropy_buffer = self._blob(self._ENTROPY)
        output = self._DataBlob()
        # Os buffers precisam permanecer referenciados durante a chamada nativa.
        _ = (source_buffer, entropy_buffer)
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source),
            "Credencial temporaria do atualizador de switches",
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN | self._CRYPTPROTECT_LOCAL_MACHINE,
            ctypes.byref(output),
        ):
            self._raise_last_error("proteger")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def unprotect(self, protected: bytes) -> str:
        if not protected:
            raise ScheduleError("A credencial protegida do agendamento nao esta disponivel.")
        source, source_buffer = self._blob(bytes(protected))
        entropy, entropy_buffer = self._blob(self._ENTROPY)
        output = self._DataBlob()
        _ = (source_buffer, entropy_buffer)
        # O escopo de protecao faz parte do blob; CryptUnprotectData nao recebe
        # CRYPTPROTECT_LOCAL_MACHINE e tambem consegue ler blobs antigos do usuario.
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
            raise ScheduleError("A credencial protegida esta corrompida.") from exc
        finally:
            self._kernel32.LocalFree(output.pbData)


@dataclass(frozen=True)
class SchedulerSettings:
    database_path: Path
    firmware_dir: Path
    poll_interval_seconds: float = 1.0
    http_timeout: float = 10.0
    reboot_timeout: int = 7 * 60
    transfer_timeout: int = 20 * 60
    transfer_stall_timeout: int = 5 * 60
    insecure_tls: bool = False
    driver_path: Path | None = None
    draft_ttl_seconds: int = 15 * 60
    log_dir: Path | None = None
    log_retention_months: int = 12


class SwitchUpdateScheduler:
    """Agenda e executa updates sequencialmente em horario de Brasilia."""

    def __init__(
        self,
        settings: SchedulerSettings,
        *,
        protector: CredentialProtector | None = None,
        assessor: Callable[..., UpdateAssessment] | None = None,
        credential_validator: Callable[[UpdateAssessment, str, str], None] | None = None,
        executor: Callable[..., None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.firmware_dir.mkdir(parents=True, exist_ok=True)
        self.draft_dir = self.settings.firmware_dir / "drafts"
        self.scheduled_firmware_dir = self.settings.firmware_dir / "scheduled"
        self.log_root = self.settings.log_dir or (
            self.settings.firmware_dir.parent / "SwitchUpdateLogs"
        )
        self.draft_dir.mkdir(parents=True, exist_ok=True)
        self.scheduled_firmware_dir.mkdir(parents=True, exist_ok=True)
        self.protector = protector or DpapiCredentialProtector()
        self.assessor = assessor or assess_update
        self.credential_validator = credential_validator or self._validate_credentials
        self.executor = executor or run
        self.now = now or (lambda: datetime.now(UTC))
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lifecycle_lock = Lock()
        self._last_log_cleanup_date = None
        self._initialize_database()
        if not TZDATA_AVAILABLE:
            LOGGER.warning(
                "tzdata nao esta instalado; usando UTC-03:00. Instale requirements.txt no servidor."
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.settings.database_path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_updates (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    scheduled_at_utc TEXT NOT NULL,
                    timezone_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    url TEXT NOT NULL,
                    host TEXT NOT NULL,
                    username TEXT NOT NULL,
                    credential_blob BLOB,
                    firmware_path TEXT,
                    original_name TEXT NOT NULL,
                    firmware_sha256 TEXT NOT NULL,
                    expected_model TEXT NOT NULL,
                    expected_version TEXT NOT NULL,
                    current_version_at_creation TEXT NOT NULL,
                    confirmed_decision TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    percent INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL,
                    error TEXT,
                    started_at_utc TEXT,
                    finished_at_utc TEXT,
                    log_relative_path TEXT,
                    result_code TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(scheduled_updates)").fetchall()
            }
            if "log_relative_path" not in columns:
                connection.execute(
                    "ALTER TABLE scheduled_updates ADD COLUMN log_relative_path TEXT"
                )
            if "result_code" not in columns:
                connection.execute(
                    "ALTER TABLE scheduled_updates ADD COLUMN result_code TEXT"
                )
            if "attempt_count" not in columns:
                connection.execute(
                    "ALTER TABLE scheduled_updates "
                    "ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
                )
            if "max_attempts" not in columns:
                connection.execute(
                    "ALTER TABLE scheduled_updates "
                    "ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 1"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_updates_due "
                "ON scheduled_updates(status, scheduled_at_utc)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS firmware_drafts (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    expires_at_utc TEXT NOT NULL,
                    url TEXT NOT NULL,
                    host TEXT NOT NULL,
                    firmware_path TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    firmware_sha256 TEXT NOT NULL,
                    expected_model TEXT NOT NULL,
                    expected_version TEXT NOT NULL,
                    current_model TEXT NOT NULL,
                    current_version TEXT NOT NULL,
                    decision TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_firmware_drafts_expiry "
                "ON firmware_drafts(expires_at_utc)"
            )

    @staticmethod
    def normalize_scheduled_at(value: datetime | str) -> datetime:
        if isinstance(value, str):
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                value = datetime.fromisoformat(text)
            except ValueError as exc:
                raise ScheduleError("Data invalida; use ISO 8601 no horario de Brasilia.") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=BRASILIA_TZ)
        return value.astimezone(UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(UTC).isoformat(timespec="seconds")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    def _create_job_logger(
        self, schedule_id: str
    ) -> tuple[logging.Logger, logging.FileHandler, Path]:
        started = self.now().astimezone(BRASILIA_TZ)
        target_dir = (
            self.log_root
            / f"{MONTH_FOLDERS[started.month]}-{started:%y}"
            / "Logs"
        )
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            base_name = f"SwitchUpdateLog_PENDENTE_{started:%d%m%Y_%H%M%S}"
            log_path = target_dir / f"{base_name}.log"
            suffix = 2
            while log_path.exists():
                log_path = target_dir / f"{base_name}_{suffix}.log"
                suffix += 1
            handler = logging.FileHandler(log_path, encoding="utf-8")
        except OSError as exc:
            raise ScheduleError(
                "Nao foi possivel criar o log da atualizacao; execucao bloqueada antes do upload."
            ) from exc
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", datefmt="%d/%m/%Y %H:%M:%S")
        )
        job_logger = logging.getLogger(f"att-switches.user-log.{schedule_id}")
        job_logger.handlers.clear()
        job_logger.setLevel(logging.INFO)
        job_logger.propagate = False
        job_logger.addHandler(handler)
        return job_logger, handler, log_path

    def _set_job_log_path(self, schedule_id: str, log_path: Path) -> None:
        relative = log_path.relative_to(self.log_root).as_posix()
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE scheduled_updates SET log_relative_path = ? WHERE id = ?",
                (relative, schedule_id),
            )

    def _rename_job_log(self, schedule_id: str, log_path: Path, result_code: str) -> Path:
        parts = log_path.name.split("_", 2)
        suffix = parts[2] if len(parts) == 3 else log_path.name
        target = log_path.with_name(f"SwitchUpdateLog_{result_code}_{suffix}")
        counter = 2
        while target.exists() and target != log_path:
            target = log_path.with_name(
                f"SwitchUpdateLog_{result_code}_{log_path.stem.split('_', 2)[-1]}_{counter}.log"
            )
            counter += 1
        try:
            if target != log_path:
                log_path.replace(target)
        except OSError as exc:
            raise ScheduleError("Nao foi possivel finalizar o nome do log da atualizacao.") from exc
        self._set_job_log_path(schedule_id, target)
        return target

    @staticmethod
    def _classify_result_code(
        stage: str, message: str, exc: Exception | None = None
    ) -> str:
        lowered = message.casefold()
        if isinstance(exc, UpdateNeedsReview):
            return "SWU410"
        if "credencial" in lowered or "dpapi" in lowered:
            return "SWU520"
        if "firmware reservado" in lowered or "arquivo foi alterado" in lowered:
            return "SWU120"
        if stage == "identity":
            if "modelo" in lowered or "versao" in lowered or "versão" in lowered:
                return "SWU110"
            return "SWU200"
        if stage == "authentication":
            return "SWU210"
        if "sessao" in lowered or "sessão" in lowered:
            return "SWU220"
        if stage == "upload_setup":
            if any(term in lowered for term in ("anex", "campo de arquivo", "upload")):
                return "SWU310"
            return "SWU300"
        if stage == "transfer":
            return "SWU320"
        if stage == "restart":
            return "SWU400"
        if stage == "waiting_ping":
            return "SWU410"
        if stage == "verifying_web":
            if "versao" in lowered or "versão" in lowered:
                return "SWU430"
            return "SWU420"
        if stage == "saving":
            return "SWU440"
        return "SWU500"

    def _append_job_log(self, row: sqlite3.Row, *messages: str) -> None:
        relative_value = str(row["log_relative_path"] or "").strip()
        if not relative_value:
            return
        log_path = self._safe_registered_log_path(relative_value)
        timestamp = self.now().astimezone(BRASILIA_TZ).strftime("%d/%m/%Y %H:%M:%S")
        try:
            with log_path.open("a", encoding="utf-8") as stream:
                for message in messages:
                    stream.write(f"{timestamp} | {message}\n")
        except OSError as exc:
            raise ScheduleError("Nao foi possivel atualizar o log da verificacao.") from exc

    def _write_job_log_header(self, job_logger: logging.Logger, row: sqlite3.Row) -> None:
        operation = {
            "update": "Atualização para uma versão mais recente",
            "same_version": "Reinstalação da mesma versão",
            "downgrade": "Instalação de uma versão anterior (downgrade)",
        }.get(row["confirmed_decision"], "Atualização de firmware")
        job_logger.info("ATUALIZAÇÃO DE SWITCH")
        job_logger.info("Identificação do processo: %s", row["id"])
        job_logger.info("Solicitado por: %s", row["owner"])
        job_logger.info("Switch: %s", row["host"])
        job_logger.info("Modelo: Aruba %s", row["expected_model"])
        job_logger.info("Versão encontrada: %s", row["current_version_at_creation"])
        job_logger.info("Versão desejada: %s", row["expected_version"])
        job_logger.info("Operação: %s", operation)
        job_logger.info(
            "Início real do processo: %s (horário de Brasília)",
            self.now().astimezone(BRASILIA_TZ).strftime("%d/%m/%Y %H:%M:%S"),
        )
        job_logger.info("------------------------------------------------------------")

    @staticmethod
    def _write_job_progress(
        job_logger: logging.Logger, stage: str, percent: int, message: str
    ) -> None:
        if stage in {"transfer", "waiting_ping"} and message:
            friendly = message
        else:
            friendly = FRIENDLY_STAGE_MESSAGES.get(stage, "Processando a atualização.")
        job_logger.info("Andamento: %s%% - %s", percent, friendly)

    def preview(
        self,
        *,
        url: str,
        firmware: Path,
        expected_model: str | None = None,
        expected_version: str | None = None,
    ) -> UpdateAssessment:
        return self.assessor(
            url,
            firmware,
            expected_model=expected_model,
            expected_version=expected_version,
            http_timeout=self.settings.http_timeout,
            insecure_tls=self.settings.insecure_tls,
        )

    @staticmethod
    def _public_draft(row: sqlite3.Row) -> dict:
        data = dict(row)
        data.pop("firmware_path", None)
        data["draft_token"] = data.pop("id")
        return data

    def cleanup_expired_drafts(self) -> int:
        now_text = self._iso(self.now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, firmware_path FROM firmware_drafts WHERE expires_at_utc <= ?",
                (now_text,),
            ).fetchall()
            if rows:
                connection.executemany(
                    "DELETE FROM firmware_drafts WHERE id = ?",
                    ((row["id"],) for row in rows),
                )
            connection.commit()
        for row in rows:
            Path(row["firmware_path"]).unlink(missing_ok=True)
        return len(rows)

    @staticmethod
    def _subtract_calendar_months(value: datetime, months: int) -> datetime:
        months = max(1, int(months))
        month_index = value.year * 12 + value.month - 1 - months
        year, zero_based_month = divmod(month_index, 12)
        month = zero_based_month + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)

    def _safe_registered_log_path(self, relative_value: str) -> Path:
        relative = Path(str(relative_value or "").strip())
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            raise ScheduleError("O caminho registrado para o log da atualizacao e invalido.")
        log_root = self.log_root.resolve()
        log_path = (log_root / relative).resolve()
        if log_root != log_path.parent and log_root not in log_path.parents:
            raise ScheduleError("O caminho registrado para o log saiu da pasta permitida.")
        return log_path

    def cleanup_expired_logs(self) -> int:
        """Remove logs com mais de 12 meses, preservando o mais recente por switch."""
        cutoff = self._subtract_calendar_months(
            self.now().astimezone(UTC), self.settings.log_retention_months
        )
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, host, status, created_at_utc, scheduled_at_utc,
                       started_at_utc, finished_at_utc, log_relative_path
                  FROM scheduled_updates
                 WHERE log_relative_path IS NOT NULL
                   AND TRIM(log_relative_path) <> ''
                 ORDER BY host,
                          COALESCE(finished_at_utc, started_at_utc,
                                   scheduled_at_utc, created_at_utc) DESC,
                          id DESC
                """
            ).fetchall()

        newest_seen: set[str] = set()
        removable: list[tuple[str, str, Path]] = []
        for row in rows:
            host = str(row["host"])
            if host not in newest_seen:
                newest_seen.add(host)
                continue
            if row["status"] not in FINAL_STATUSES:
                continue
            timestamp_text = (
                row["finished_at_utc"]
                or row["started_at_utc"]
                or row["scheduled_at_utc"]
                or row["created_at_utc"]
            )
            try:
                timestamp = datetime.fromisoformat(str(timestamp_text).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                LOGGER.warning("Log do job %s tem data invalida e foi preservado.", row["id"])
                continue
            if timestamp.astimezone(UTC) >= cutoff:
                continue
            try:
                path = self._safe_registered_log_path(row["log_relative_path"])
            except ScheduleError as exc:
                LOGGER.warning("Log do job %s foi preservado: %s", row["id"], exc)
                continue
            removable.append((str(row["id"]), str(row["log_relative_path"]), path))

        removed = 0
        empty_dir_candidates: set[Path] = set()
        for schedule_id, relative_value, path in removable:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                LOGGER.warning("Nao foi possivel excluir o log vencido %s: %s", path, exc)
                continue
            with closing(self._connect()) as connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_updates
                       SET log_relative_path = NULL
                     WHERE id = ? AND log_relative_path = ?
                    """,
                    (schedule_id, relative_value),
                )
            if cursor.rowcount:
                removed += 1
                empty_dir_candidates.add(path.parent)

        for logs_dir in empty_dir_candidates:
            try:
                logs_dir.rmdir()
                logs_dir.parent.rmdir()
            except OSError:
                pass
        return removed

    def _cleanup_logs_if_due(self) -> None:
        today = self.now().astimezone(BRASILIA_TZ).date()
        if self._last_log_cleanup_date == today:
            return
        removed = self.cleanup_expired_logs()
        self._last_log_cleanup_date = today
        if removed:
            LOGGER.info("Politica de retencao removeu %s log(s) vencido(s).", removed)

    def create_draft(
        self,
        *,
        owner: str,
        url: str,
        firmware: Path,
        original_name: str | None = None,
        expected_model: str | None = None,
        expected_version: str | None = None,
    ) -> dict:
        owner = str(owner or "").strip()
        if not owner:
            raise ScheduleError("O responsavel pelo preflight e obrigatorio.")
        self.cleanup_expired_drafts()
        assessment = self.preview(
            url=url,
            firmware=firmware,
            expected_model=expected_model,
            expected_version=expected_version,
        )
        draft_id = uuid4().hex
        managed_path = self.draft_dir / f"{draft_id}.swi"
        created = self.now().astimezone(UTC)
        expires = created + timedelta(seconds=max(60, self.settings.draft_ttl_seconds))
        try:
            shutil.copyfile(assessment.firmware, managed_path)
            digest = self._sha256(managed_path)
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT INTO firmware_drafts (
                        id, owner, created_at_utc, expires_at_utc, url, host,
                        firmware_path, original_name, firmware_sha256,
                        expected_model, expected_version, current_model,
                        current_version, decision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft_id,
                        owner,
                        self._iso(created),
                        self._iso(expires),
                        assessment.url,
                        assessment.host,
                        str(managed_path),
                        (original_name or assessment.firmware.name)[:255],
                        digest,
                        assessment.expected_model,
                        assessment.expected_version,
                        assessment.current_model,
                        assessment.current_version,
                        assessment.decision,
                    ),
                )
        except Exception:
            managed_path.unlink(missing_ok=True)
            raise
        return self.get_draft(draft_id, owner=owner)

    def _get_draft_row(self, draft_id: str, *, owner: str) -> sqlite3.Row:
        self.cleanup_expired_drafts()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM firmware_drafts WHERE id = ? AND owner = ?",
                (draft_id, owner),
            ).fetchone()
        if not row:
            raise ScheduleError("Preflight expirado ou nao encontrado.")
        return row

    def get_draft(self, draft_id: str, *, owner: str) -> dict:
        return self._public_draft(self._get_draft_row(draft_id, owner=owner))

    def delete_draft(self, draft_id: str, *, owner: str) -> None:
        row = self._get_draft_row(draft_id, owner=owner)
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM firmware_drafts WHERE id = ? AND owner = ?",
                (draft_id, owner),
            )
        Path(row["firmware_path"]).unlink(missing_ok=True)

    def schedule_from_draft(
        self,
        *,
        draft_id: str,
        owner: str,
        scheduled_at: datetime | str,
        username: str,
        password: str,
        confirmed_decision: str,
        max_attempts: int = 1,
    ) -> dict:
        row = self._get_draft_row(draft_id, owner=owner)
        firmware = Path(row["firmware_path"])
        if not firmware.is_file() or self._sha256(firmware) != row["firmware_sha256"]:
            self.delete_draft(draft_id, owner=owner)
            raise ScheduleError("O firmware temporario do preflight foi alterado ou removido.")
        result = self.create_schedule(
            owner=owner,
            scheduled_at=scheduled_at,
            url=row["url"],
            username=username,
            password=password,
            firmware=firmware,
            confirmed_decision=confirmed_decision,
            max_attempts=max_attempts,
            expected_model=row["expected_model"],
            expected_version=row["expected_version"],
        )
        self.delete_draft(draft_id, owner=owner)
        return result

    def _validate_credentials(
        self,
        assessment: UpdateAssessment,
        username: str,
        password: str,
    ) -> None:
        updater: ArubaWebUpdater | None = None
        try:
            updater = ArubaWebUpdater(
                url=assessment.url,
                username=username,
                password=password,
                driver_path=self.settings.driver_path,
                insecure_tls=self.settings.insecure_tls,
                show_browser=False,
                diagnostics_dir=self.settings.database_path.parent / "diagnostics",
            )
            updater.login()
            detected = updater.detected_model(assessment.identity.sys_descr)
            if detected != assessment.expected_model:
                raise ScheduleError(
                    f"O login retornou Aruba {detected}, esperado {assessment.expected_model}."
                )
        finally:
            if updater:
                updater.close()

    def create_schedule(
        self,
        *,
        owner: str,
        scheduled_at: datetime | str,
        url: str,
        username: str,
        password: str,
        firmware: Path,
        confirmed_decision: str,
        max_attempts: int = 1,
        expected_model: str | None = None,
        expected_version: str | None = None,
    ) -> dict:
        owner = str(owner or "").strip()
        username = str(username or "").strip()
        if not owner:
            raise ScheduleError("O responsavel pelo agendamento e obrigatorio.")
        if not username or not password:
            raise ScheduleError("Usuario e senha da WebUI sao obrigatorios.")
        if confirmed_decision not in VALID_DECISIONS:
            raise ScheduleError("A decisao confirmada para o update e invalida.")
        try:
            normalized_max_attempts = int(max_attempts)
        except (TypeError, ValueError) as exc:
            raise ScheduleError("A quantidade de tentativas e invalida.") from exc
        if not MIN_UPDATE_ATTEMPTS <= normalized_max_attempts <= MAX_UPDATE_ATTEMPTS:
            raise ScheduleError(
                f"A quantidade de tentativas deve ficar entre "
                f"{MIN_UPDATE_ATTEMPTS} e {MAX_UPDATE_ATTEMPTS}."
            )

        scheduled_utc = self.normalize_scheduled_at(scheduled_at)
        current_utc = self.now().astimezone(UTC)
        if scheduled_utc < current_utc - timedelta(seconds=30):
            raise ScheduleError("O horario agendado ja passou.")

        assessment = self.preview(
            url=url,
            firmware=firmware,
            expected_model=expected_model,
            expected_version=expected_version,
        )
        if assessment.decision != confirmed_decision:
            raise ScheduleConflictError(
                "A situacao do switch mudou; execute o preflight novamente antes de confirmar."
            )
        self.credential_validator(assessment, username, password)

        schedule_id = uuid4().hex
        managed_firmware = self.scheduled_firmware_dir / f"{schedule_id}.swi"
        credential_blob: bytes | None = None
        try:
            shutil.copyfile(assessment.firmware, managed_firmware)
            firmware_hash = self._sha256(managed_firmware)
            credential_blob = self.protector.protect(password)
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                duplicate = connection.execute(
                    """
                    SELECT id FROM scheduled_updates
                    WHERE host = ? AND status IN ('scheduled', 'running', 'needs_review')
                    LIMIT 1
                    """,
                    (assessment.host,),
                ).fetchone()
                if duplicate:
                    connection.rollback()
                    raise ScheduleConflictError(
                        "Ja existe uma atualizacao pendente ou em revisao para este switch."
                    )
                connection.execute(
                    """
                    INSERT INTO scheduled_updates (
                        id, owner, created_at_utc, scheduled_at_utc, timezone_name,
                        status, url, host, username, credential_blob, firmware_path,
                        original_name, firmware_sha256, expected_model,
                        expected_version, current_version_at_creation,
                        confirmed_decision, stage, percent, message,
                        attempt_count, max_attempts
                    ) VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'scheduled', 0, ?, 0, ?)
                    """,
                    (
                        schedule_id,
                        owner,
                        self._iso(current_utc),
                        self._iso(scheduled_utc),
                        "America/Sao_Paulo",
                        assessment.url,
                        assessment.host,
                        username,
                        credential_blob,
                        str(managed_firmware),
                        assessment.firmware.name,
                        firmware_hash,
                        assessment.expected_model,
                        assessment.expected_version,
                        assessment.current_version,
                        assessment.decision,
                        "Atualizacao agendada no horario de Brasilia.",
                        normalized_max_attempts,
                    ),
                )
                connection.commit()
        except Exception:
            managed_firmware.unlink(missing_ok=True)
            raise
        finally:
            credential_blob = None
            password = ""

        return self.get_schedule(schedule_id, owner=owner)

    @staticmethod
    def _public_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data.pop("credential_blob", None)
        data.pop("firmware_path", None)
        scheduled = datetime.fromisoformat(data["scheduled_at_utc"])
        data["scheduled_at_brasilia"] = scheduled.astimezone(BRASILIA_TZ).isoformat(
            timespec="seconds"
        )
        for field in ("started_at_utc", "finished_at_utc"):
            value = data.get(field)
            if value:
                timestamp = datetime.fromisoformat(str(value))
                data[field.replace("_utc", "_brasilia")] = timestamp.astimezone(
                    BRASILIA_TZ
                ).isoformat(timespec="seconds")
        data["result_description"] = RESULT_CODES.get(data.get("result_code"))
        return data

    def get_schedule(self, schedule_id: str, *, owner: str | None = None) -> dict:
        query = "SELECT * FROM scheduled_updates WHERE id = ?"
        params: list[str] = [schedule_id]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)
        with closing(self._connect()) as connection:
            row = connection.execute(query, params).fetchone()
        if not row:
            raise ScheduleError("Agendamento nao encontrado.")
        return self._public_row(row)

    def get_active_schedule_for_host(self, host: str) -> dict | None:
        """Retorna o job que mantém um switch bloqueado, independentemente do solicitante."""
        normalized_host = str(host or "").strip()
        if not normalized_host:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM scheduled_updates
                 WHERE host = ? AND status IN ('scheduled', 'running', 'needs_review')
                 ORDER BY scheduled_at_utc ASC, created_at_utc ASC
                 LIMIT 1
                """,
                (normalized_host,),
            ).fetchone()
        return self._public_row(row) if row else None

    def list_schedules(self, *, owner: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM scheduled_updates"
        params: list[object] = []
        if owner is not None:
            query += " WHERE owner = ?"
            params.append(owner)
        query += " ORDER BY scheduled_at_utc DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._public_row(row) for row in rows]

    def cancel_schedule(self, schedule_id: str, *, owner: str) -> dict:
        firmware_path: str | None = None
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, firmware_path FROM scheduled_updates WHERE id = ? AND owner = ?",
                (schedule_id, owner),
            ).fetchone()
            if not row:
                connection.rollback()
                raise ScheduleError("Agendamento nao encontrado.")
            if row["status"] != "scheduled":
                connection.rollback()
                raise ScheduleConflictError(
                    "Somente um agendamento ainda nao iniciado pode ser cancelado."
                )
            firmware_path = row["firmware_path"]
            connection.execute(
                """
                UPDATE scheduled_updates
                SET status = 'cancelled', stage = 'cancelled', percent = 0,
                    message = 'Agendamento cancelado pelo usuario.', credential_blob = NULL,
                    firmware_path = NULL, result_code = 'SWU090', finished_at_utc = ?
                WHERE id = ?
                """,
                (self._iso(self.now()), schedule_id),
            )
            connection.commit()
        if firmware_path:
            Path(firmware_path).unlink(missing_ok=True)
        return self.get_schedule(schedule_id, owner=owner)

    def recover_interrupted(self) -> int:
        """Nunca repete automaticamente um job que pode ter alterado o switch."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM scheduled_updates WHERE status = 'running'"
            ).fetchall()
            if rows:
                connection.execute(
                    """
                    UPDATE scheduled_updates
                    SET status = 'needs_review', stage = 'needs_review',
                        message = 'O servico reiniciou durante a atualizacao; verifique o switch.',
                        error = 'Estado final desconhecido; repeticao automatica bloqueada.',
                        credential_blob = NULL, firmware_path = NULL,
                        result_code = 'SWU510', finished_at_utc = ?
                    WHERE status = 'running'
                    """,
                    (self._iso(self.now()),),
                )
        for row in rows:
            if row["firmware_path"]:
                Path(row["firmware_path"]).unlink(missing_ok=True)
            if row["log_relative_path"]:
                try:
                    self._append_job_log(
                        row,
                        "------------------------------------------------------------",
                        "CÓDIGO DO RESULTADO: SWU510",
                        "RESULTADO: VERIFICAÇÃO NECESSÁRIA",
                        "O serviço do Sentinel foi interrompido durante a atualização.",
                        "Orientação: verifique o switch antes de liberar uma nova atualização.",
                    )
                    current_log = self.log_root / Path(row["log_relative_path"])
                    self._rename_job_log(row["id"], current_log, "SWU510")
                except ScheduleError as exc:
                    LOGGER.error("Nao foi possivel finalizar o log do job %s: %s", row["id"], exc)
        return len(rows)

    def acknowledge_review(self, schedule_id: str, *, owner: str) -> dict:
        """Libera o switch somente apos verificacao manual de um job interrompido."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM scheduled_updates WHERE id = ? AND owner = ?",
                (schedule_id, owner),
            ).fetchone()
            if not row:
                connection.rollback()
                raise ScheduleError("Agendamento nao encontrado.")
            if row["status"] != "needs_review":
                connection.rollback()
                raise ScheduleConflictError("Este job nao esta aguardando revisao manual.")
            connection.execute(
                """
                UPDATE scheduled_updates
                SET status = 'reviewed', stage = 'reviewed',
                    message = 'Revisao manual confirmada pelo operador.'
                WHERE id = ?
                """,
                (schedule_id,),
            )
            connection.commit()
        return self.get_schedule(schedule_id, owner=owner)

    def recheck_review(self, schedule_id: str, *, owner: str) -> dict:
        """Reconsulta um switch que excedeu o tempo de retorno apos o restart."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_updates WHERE id = ? AND owner = ?",
                (schedule_id, owner),
            ).fetchone()
        if not row:
            raise ScheduleError("Agendamento nao encontrado.")
        if row["status"] != "needs_review":
            raise ScheduleConflictError("Este job nao esta aguardando nova verificacao.")

        try:
            identity = fetch_web_identity(
                row["url"],
                self.settings.http_timeout,
                self.settings.insecure_tls,
            )
        except UpdateError:
            self._append_job_log(
                row,
                "NOVA VERIFICAÇÃO: o switch ainda não respondeu.",
                "Orientação: confira a conexão e tente 'Verificar novamente' mais tarde.",
            )
            raise
        if identity.model != row["expected_model"]:
            self._append_job_log(
                row,
                "NOVA VERIFICAÇÃO: o equipamento respondeu, mas o modelo esperado não foi confirmado.",
                "Orientação: encaminhe este arquivo à equipe responsável.",
            )
            raise ScheduleConflictError(
                "O switch retornou, mas o modelo nao corresponde ao esperado; mantenha a revisao manual."
            )
        if not final_version_matches(row["expected_version"], identity.sys_descr):
            self._append_job_log(
                row,
                "NOVA VERIFICAÇÃO: o switch respondeu, mas a versão desejada não foi confirmada.",
                "Orientação: não repita a atualização sem avaliação da equipe responsável.",
            )
            raise ScheduleConflictError(
                "O switch retornou, mas a versao esperada nao foi confirmada; mantenha a revisao manual."
            )

        self._append_job_log(
            row,
            "------------------------------------------------------------",
            "CÓDIGO DO RESULTADO: SWU411",
            "RESULTADO APÓS NOVA VERIFICAÇÃO: SUCESSO",
            LATE_SUCCESS_MESSAGE,
            "Orientação: consulte a integridade geral do switch antes de encerrar o atendimento.",
        )

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """
                UPDATE scheduled_updates
                SET status = 'completed', stage = 'completed_after_review', percent = 100,
                    message = ?, result_code = 'SWU411', finished_at_utc = ?
                WHERE id = ? AND owner = ? AND status = 'needs_review'
                """,
                (LATE_SUCCESS_MESSAGE, self._iso(self.now()), schedule_id, owner),
            ).rowcount
            if changed != 1:
                connection.rollback()
                raise ScheduleConflictError("O estado do job mudou durante a verificacao.")
            connection.commit()
        if row["log_relative_path"]:
            current_log = self.log_root / Path(row["log_relative_path"])
            self._rename_job_log(schedule_id, current_log, "SWU411")
        return self.get_schedule(schedule_id, owner=owner)

    def _claim_next_due(self) -> sqlite3.Row | None:
        now_text = self._iso(self.now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM scheduled_updates
                WHERE status = 'scheduled' AND scheduled_at_utc <= ?
                ORDER BY scheduled_at_utc ASC, created_at_utc ASC
                LIMIT 1
                """,
                (now_text,),
            ).fetchone()
            if not row:
                connection.commit()
                return None
            changed = connection.execute(
                """
                UPDATE scheduled_updates
                SET status = 'running', stage = 'starting', percent = 0,
                    message = 'Iniciando tentativa de atualizacao.',
                    attempt_count = attempt_count + 1,
                    started_at_utc = ?, finished_at_utc = NULL,
                    error = NULL, result_code = NULL
                WHERE id = ? AND status = 'scheduled'
                """,
                (now_text, row["id"]),
            ).rowcount
            connection.commit()
        if changed != 1:
            return None
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM scheduled_updates WHERE id = ?", (row["id"],)
            ).fetchone()

    def _update_progress(self, schedule_id: str, stage: str, percent: int, message: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE scheduled_updates
                SET stage = ?, percent = ?, message = ?
                WHERE id = ? AND status = 'running'
                """,
                (stage, max(0, min(100, int(percent))), str(message)[:500], schedule_id),
            )

    def _finalize(
        self,
        schedule_id: str,
        *,
        status: str,
        message: str,
        result_code: str,
        error: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE scheduled_updates
                SET status = ?, stage = ?,
                    percent = CASE WHEN ? = 'completed' THEN 100 ELSE percent END,
                    message = ?, error = ?, result_code = ?,
                    credential_blob = NULL, firmware_path = NULL, finished_at_utc = ?
                WHERE id = ?
                """,
                (
                    status,
                    status,
                    status,
                    message[:500],
                    error[:500] if error else None,
                    result_code,
                    self._iso(self.now()),
                    schedule_id,
                ),
            )

    def _schedule_retry(
        self,
        schedule_id: str,
        *,
        attempt_count: int,
        max_attempts: int,
        error: str,
        result_code: str,
    ) -> datetime:
        next_attempt = self.now().astimezone(UTC) + timedelta(
            seconds=RETRY_DELAY_SECONDS
        )
        message = (
            f"Tentativa {attempt_count} de {max_attempts} nao concluida "
            f"({result_code}). Nova tentativa automatica em cinco minutos."
        )
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE scheduled_updates
                SET status = 'scheduled', stage = 'retry_scheduled', percent = 0,
                    scheduled_at_utc = ?, message = ?, error = ?,
                    result_code = NULL, finished_at_utc = NULL
                WHERE id = ? AND status = 'running'
                """,
                (
                    self._iso(next_attempt),
                    message,
                    error[:500],
                    schedule_id,
                ),
            )
        return next_attempt

    def _execute_claimed(self, row: sqlite3.Row) -> None:
        schedule_id = row["id"]
        firmware_path = Path(row["firmware_path"])
        password = ""
        job_handler: logging.FileHandler | None = None
        job_logger: logging.Logger | None = None
        reporter: ProgressReporter | None = None
        final_status = "failed"
        result_code = "SWU500"
        log_path: Path | None = None
        cleanup_artifacts = True
        try:
            job_logger, job_handler, log_path = self._create_job_logger(schedule_id)
            self._set_job_log_path(schedule_id, log_path)
            self._write_job_log_header(job_logger, row)
            job_logger.info(
                "Tentativa: %s de %s",
                row["attempt_count"],
                row["max_attempts"],
            )
            job_logger.info("Andamento: 0% - Atualização iniciada.")
            LOGGER.info(
                "Inicio do job %s | switch=%s | modelo=%s | versao_destino=%s | log=%s",
                schedule_id,
                row["host"],
                row["expected_model"],
                row["expected_version"],
                log_path.name,
            )
            if not firmware_path.is_file():
                raise ScheduleError("O firmware reservado para o agendamento nao foi encontrado.")
            if self._sha256(firmware_path) != row["firmware_sha256"]:
                raise ScheduleError("O firmware agendado foi alterado depois da validacao.")
            password = self.protector.unprotect(row["credential_blob"])
            argv = [
                "--url", row["url"],
                "--username", row["username"],
                "--firmware", str(firmware_path),
                "--expected-model", row["expected_model"],
                "--expected-version", row["expected_version"],
                "--http-timeout", str(self.settings.http_timeout),
                "--reboot-timeout", str(self.settings.reboot_timeout),
                "--transfer-timeout", str(self.settings.transfer_timeout),
                "--transfer-stall-timeout", str(self.settings.transfer_stall_timeout),
                "--execute",
                "--sentinel-approved",
            ]
            if self.settings.insecure_tls:
                argv.append("--insecure-tls")
            if self.settings.driver_path:
                argv.extend(("--driver-path", str(self.settings.driver_path)))
            if row["confirmed_decision"] == "same_version":
                argv.append("--allow-same-version")
            elif row["confirmed_decision"] == "downgrade":
                argv.append("--allow-downgrade")

            args = build_parser().parse_args(argv)
            def report_progress(stage: str, percent: int, message: str) -> None:
                self._update_progress(schedule_id, stage, percent, message)
                if job_logger:
                    self._write_job_progress(job_logger, stage, percent, message)

            reporter = ProgressReporter(callback=report_progress)
            self.executor(args, switch_password=password, reporter=reporter)
            confirmed_release = release_version(row["expected_version"])
            self._finalize(
                schedule_id,
                status="completed",
                message=f"Versao {confirmed_release} confirmada; atualizacao concluida.",
                result_code="SWU000",
            )
            final_status = "completed"
            result_code = "SWU000"
            job_logger.info("------------------------------------------------------------")
            job_logger.info("CÓDIGO DO RESULTADO: SWU000")
            job_logger.info("RESULTADO: SUCESSO")
            job_logger.info(
                "A versão %s foi confirmada e o processo terminou normalmente.",
                confirmed_release,
            )
            job_logger.info("Orientação: nenhuma ação adicional é necessária.")
        except UpdateNeedsReview as exc:
            message = concise_exception_message(exc)
            self._finalize(
                schedule_id,
                status="needs_review",
                message=message,
                result_code="SWU410",
                error=message,
            )
            final_status = "needs_review"
            result_code = "SWU410"
            if job_logger:
                job_logger.info("------------------------------------------------------------")
                job_logger.warning("CÓDIGO DO RESULTADO: SWU410")
                job_logger.warning("RESULTADO: VERIFICAÇÃO NECESSÁRIA")
                job_logger.warning(
                    "O arquivo foi enviado e o switch recebeu o comando para reiniciar, "
                    "mas não voltou a responder em até sete minutos."
                )
                job_logger.warning(
                    "Orientação: use a opção 'Verificar novamente' no Sentinel. "
                    "Não repita a atualização nem reinicie fisicamente o equipamento antes da consulta."
                )
            LOGGER.warning("Agendamento %s aguarda revisao: %s", schedule_id, message)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ScheduleError) else concise_exception_message(exc)
            stage = (reporter.failure_stage or reporter.last_stage) if reporter else "starting"
            result_code = self._classify_result_code(stage, message, exc)
            attempt_count = int(row["attempt_count"] or 0)
            max_attempts = int(row["max_attempts"] or 1)
            retry_allowed = (
                result_code in RETRYABLE_RESULT_CODES
                and attempt_count < max_attempts
            )
            if retry_allowed:
                next_attempt = self._schedule_retry(
                    schedule_id,
                    attempt_count=attempt_count,
                    max_attempts=max_attempts,
                    error=message,
                    result_code=result_code,
                )
                final_status = "scheduled"
                cleanup_artifacts = False
                if job_logger:
                    job_logger.warning("------------------------------------------------------------")
                    job_logger.warning("CÓDIGO DA TENTATIVA: %s", result_code)
                    job_logger.warning(
                        "Tentativa %s de %s não concluída; nova tentativa às %s.",
                        attempt_count,
                        max_attempts,
                        next_attempt.astimezone(BRASILIA_TZ).strftime("%d/%m/%Y %H:%M:%S"),
                    )
                LOGGER.warning(
                    "Agendamento %s retornou %s e será tentado novamente (%s/%s).",
                    schedule_id,
                    result_code,
                    attempt_count,
                    max_attempts,
                )
            else:
                self._finalize(
                    schedule_id,
                    status="failed",
                    message=message,
                    result_code=result_code,
                    error=message,
                )
                if job_logger:
                    friendly = FRIENDLY_FAILURE_MESSAGES.get(
                        stage, "A atualização não pôde ser concluída."
                    )
                    job_logger.info("------------------------------------------------------------")
                    job_logger.error("CÓDIGO DO RESULTADO: %s", result_code)
                    job_logger.error("RESULTADO: NÃO CONCLUÍDO")
                    job_logger.error("O que aconteceu: %s", friendly)
                    job_logger.error(
                        "Orientação: confira a conexão e o acesso ao switch. "
                        "Se o problema continuar, encaminhe este arquivo à equipe responsável."
                    )
                LOGGER.error("Agendamento %s falhou: %s", schedule_id, message)
        finally:
            password = ""
            if cleanup_artifacts:
                firmware_path.unlink(missing_ok=True)
            if job_handler and job_logger:
                job_logger.info(
                    "Fim real do processo: %s (horário de Brasília)",
                    self.now().astimezone(BRASILIA_TZ).strftime("%d/%m/%Y %H:%M:%S"),
                )
                job_logger.info("Status registrado pelo sistema: %s", final_status)
                job_logger.removeHandler(job_handler)
                job_handler.close()
            if log_path and log_path.exists():
                try:
                    self._rename_job_log(schedule_id, log_path, result_code)
                except ScheduleError as exc:
                    LOGGER.error("Nao foi possivel renomear o log do job %s: %s", schedule_id, exc)
            LOGGER.info("Fim do job %s | status=%s", schedule_id, final_status)

    def run_due_once(self) -> str | None:
        row = self._claim_next_due()
        if not row:
            return None
        self._execute_claimed(row)
        return str(row["id"])

    def run_all_due(self) -> list[str]:
        """Executa, em sequencia, todos os jobs vencidos neste instante."""
        processed: list[str] = []
        while True:
            schedule_id = self.run_due_once()
            if schedule_id is None:
                return processed
            processed.append(schedule_id)

    def perform_maintenance(self) -> None:
        """Executa a manutencao segura usada pelos workers interno e externo."""
        self.cleanup_expired_drafts()
        self._cleanup_logs_if_due()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.perform_maintenance()
                processed = self.run_due_once()
            except Exception:
                LOGGER.exception("Falha interna no ciclo do agendador; nova tentativa sera feita.")
                processed = None
            if processed is None:
                self._stop_event.wait(max(0.1, self.settings.poll_interval_seconds))

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            recovered = self.recover_interrupted()
            if recovered:
                LOGGER.warning("%s job(s) interrompido(s) exigem revisao manual.", recovered)
            self._cleanup_logs_if_due()
            self._stop_event.clear()
            self._thread = Thread(
                target=self._loop,
                name="switch-update-scheduler",
                daemon=True,
            )
            self._thread.start()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self, *, wait: bool = False, timeout: float | None = None) -> None:
        self._stop_event.set()
        thread = self._thread
        if wait and thread:
            thread.join(timeout=timeout)


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agendador da alpha v0.1.")
    parser.add_argument("--runtime-dir", type=Path, default=Path("runtime"))
    parser.add_argument("--insecure-tls", action="store_true")
    parser.add_argument("--driver-path", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Valida e cria um agendamento.")
    create.add_argument("--at", required=True, help="Data/hora ISO; sem offset usa Brasilia.")
    create.add_argument("--url", required=True)
    create.add_argument("--username", required=True)
    create.add_argument("--firmware", required=True, type=Path)
    create.add_argument("--expected-model", choices=("1830", "1930"))
    create.add_argument("--expected-version")
    create.add_argument("--owner", default=os.environ.get("USERNAME") or "operador-local")

    subparsers.add_parser("list", help="Lista agendamentos.")
    status = subparsers.add_parser("status", help="Consulta um agendamento.")
    status.add_argument("id")
    cancel = subparsers.add_parser("cancel", help="Cancela um agendamento pendente.")
    cancel.add_argument("id")
    cancel.add_argument("--owner", default=os.environ.get("USERNAME") or "operador-local")
    subparsers.add_parser("serve", help="Mantem o agendador executando.")
    return parser


def cli_main() -> int:
    args = build_cli_parser().parse_args()
    settings = SchedulerSettings(
        database_path=args.runtime_dir / "scheduled_updates.sqlite3",
        firmware_dir=args.runtime_dir / "scheduled_firmware",
        insecure_tls=args.insecure_tls,
        driver_path=args.driver_path,
    )
    scheduler = SwitchUpdateScheduler(settings)
    try:
        if args.command == "list":
            print(json.dumps(scheduler.list_schedules(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            print(json.dumps(scheduler.get_schedule(args.id), ensure_ascii=False, indent=2))
            return 0
        if args.command == "cancel":
            print(
                json.dumps(
                    scheduler.cancel_schedule(args.id, owner=args.owner),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "create":
            assessment = scheduler.preview(
                url=args.url,
                firmware=args.firmware,
                expected_model=args.expected_model,
                expected_version=args.expected_version,
            )
            print(
                f"Atual: {assessment.current_version} | Destino: "
                f"{assessment.expected_version} | Operacao: {assessment.decision}"
            )
            if input("Digite AGENDAR para confirmar: ").strip() != "AGENDAR":
                raise ScheduleError("Agendamento cancelado pelo usuario.")
            password = getpass("Senha da interface web do switch: ")
            result = scheduler.create_schedule(
                owner=args.owner,
                scheduled_at=args.at,
                url=args.url,
                username=args.username,
                password=password,
                firmware=args.firmware,
                confirmed_decision=assessment.decision,
                expected_model=assessment.expected_model,
                expected_version=assessment.expected_version,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        scheduler.start()
        print("Agendador iniciado. Pressione Ctrl+C para encerrar.")
        while True:
            time.sleep(1)
    except (ScheduleError, UpdateError) as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        scheduler.stop()
        return 130
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    raise SystemExit(cli_main())
