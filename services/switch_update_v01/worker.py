"""Worker nao interativo para o Agendador de Tarefas do Windows.

O processo consulta apenas o SQLite do Sentinel. Credenciais, firmware e IP
nunca sao recebidos pela linha de comando.
"""

from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
import json
import logging
import msvcrt
import os
from pathlib import Path

from .scheduler import SchedulerSettings, SwitchUpdateScheduler


LOGGER = logging.getLogger("sentinel.switch-update.worker")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / "data" / "switch_updates"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "sim"}


def _config_number(config: dict, name: str, default, converter, minimum):
    try:
        value = converter(config.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _config_flag(config: dict, name: str, default: bool = False) -> bool:
    value = config.get(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "sim"}


class WorkerAlreadyRunning(RuntimeError):
    """Outro worker detem a trava exclusiva do runtime."""


class WorkerFileLock(AbstractContextManager):
    """Trava de processo liberada automaticamente pelo Windows em uma queda."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self._file.write(b"\0")
            self._file.flush()
            os.fsync(self._file.fileno())
        self._file.seek(0)
        try:
            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self._file.close()
            self._file = None
            raise WorkerAlreadyRunning("Outro worker de atualizacao ja esta ativo.") from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._file is not None:
            try:
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self._file.close()
                self._file = None
        return False


def build_scheduler(
    runtime_dir: str | Path,
    *,
    insecure_tls: bool = False,
    driver_path: str | Path | None = None,
    config: dict | None = None,
) -> SwitchUpdateScheduler:
    runtime = Path(runtime_dir).resolve()
    config = config or {}
    return SwitchUpdateScheduler(
        SchedulerSettings(
            database_path=runtime / "scheduled_updates.sqlite3",
            firmware_dir=runtime / "firmware",
            log_dir=runtime / "SwitchUpdateLogs",
            poll_interval_seconds=1.0,
            http_timeout=_config_number(config, "http_timeout", 10.0, float, 0.1),
            reboot_timeout=_config_number(config, "reboot_timeout", 7 * 60, int, 1),
            transfer_timeout=_config_number(config, "transfer_timeout", 15 * 60, int, 1),
            insecure_tls=insecure_tls,
            driver_path=Path(driver_path).resolve() if driver_path else None,
            draft_ttl_seconds=_config_number(
                config, "draft_ttl_seconds", 15 * 60, int, 60
            ),
            log_retention_months=_config_number(
                config, "log_retention_months", 12, int, 1
            ),
        )
    )


def load_project_config(path: str | Path | None = None) -> dict:
    source = Path(path) if path else PROJECT_ROOT / "environment.json"
    if not source.is_file():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        LOGGER.warning("Configuracao switch_update invalida em %s; usando padroes seguros.", source)
        return {}
    config = payload.get("switch_update", {}) if isinstance(payload, dict) else {}
    return dict(config) if isinstance(config, dict) else {}


def run_once(scheduler: SwitchUpdateScheduler, *, lock_path: str | Path) -> list[str]:
    """Recupera quedas, mantem o runtime e esvazia a fila ja vencida."""
    with WorkerFileLock(lock_path):
        recovered = scheduler.recover_interrupted()
        if recovered:
            LOGGER.warning(
                "%s job(s) interrompido(s) foram movidos para needs_review.",
                recovered,
            )
        scheduler.perform_maintenance()
        processed = scheduler.run_all_due()
        scheduler.perform_maintenance()
        return processed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Executa uma passagem da fila de atualizacao de switches do Sentinel."
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME_DIR,
        help="Runtime persistente do Sentinel; nao contem credenciais em texto claro.",
    )
    parser.add_argument(
        "--driver-path",
        type=Path,
        default=(Path(os.environ["SWITCH_UPDATE_DRIVER_PATH"])
                 if os.environ.get("SWITCH_UPDATE_DRIVER_PATH") else None),
        help="ChromeDriver previamente instalado e compativel com o Chrome.",
    )
    parser.add_argument(
        "--insecure-tls",
        action="store_true",
        default=_env_flag("SWITCH_UPDATE_INSECURE_TLS"),
        help="Aceita certificado do switch sem validacao (somente homologacao).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir = args.runtime_dir.resolve()
    try:
        config = load_project_config()
        configured_driver = str(config.get("driver_path") or "").strip()
        driver_path = args.driver_path or (Path(configured_driver) if configured_driver else None)
        if driver_path and not driver_path.is_absolute():
            driver_path = PROJECT_ROOT / driver_path
        scheduler = build_scheduler(
            runtime_dir,
            insecure_tls=args.insecure_tls or _config_flag(config, "insecure_tls"),
            driver_path=driver_path,
            config=config,
        )
        processed = run_once(
            scheduler,
            lock_path=runtime_dir / "switch_update_worker.lock",
        )
    except WorkerAlreadyRunning as exc:
        LOGGER.info("%s", exc)
        return 0
    except Exception:
        LOGGER.exception("Falha interna no worker de atualizacao de switches.")
        return 1

    LOGGER.info("Worker concluido; %s job(s) processado(s).", len(processed))
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    raise SystemExit(main())
