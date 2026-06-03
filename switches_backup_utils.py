from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path


SWITCH_BACKUP_RETENTION_DAYS = int(os.environ.get("SWITCH_BACKUP_RETENTION_DAYS", "90"))
SWITCH_BACKUP_PATTERNS = (
    "switches_zabbix_backup_*.xlsx",
    "switches_zabbix_corrigido_*.xlsx",
)
_TIMESTAMP_REGEX = re.compile(r"_(\d{8})_(\d{6})\.xlsx$", re.IGNORECASE)


def _get_project_base_dir(base_dir: Path | None = None) -> Path:
    return Path(base_dir) if base_dir else Path(__file__).resolve().parent


def get_switch_backup_root(base_dir: Path | None = None) -> Path:
    return _get_project_base_dir(base_dir) / "backups" / "switches"


def get_switch_backup_day_dir(base_dir: Path | None = None, reference: datetime | None = None) -> Path:
    now = reference or datetime.now()
    day_dir = get_switch_backup_root(base_dir) / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def _iter_switch_backup_files(base_dir: Path | None = None):
    backup_root = get_switch_backup_root(base_dir)
    if not backup_root.exists():
        return []

    files = []
    for pattern in SWITCH_BACKUP_PATTERNS:
        files.extend(backup_root.rglob(pattern))
    return files


def cleanup_old_switch_backups(base_dir: Path | None = None, retention_days: int = SWITCH_BACKUP_RETENTION_DAYS) -> int:
    backup_root = get_switch_backup_root(base_dir)
    if not backup_root.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0

    for file_path in _iter_switch_backup_files(base_dir):
        try:
            modified_at = datetime.fromtimestamp(file_path.stat().st_mtime)
        except OSError:
            continue

        if modified_at < cutoff:
            try:
                file_path.unlink()
                removed += 1
            except OSError:
                continue

    _prune_empty_switch_backup_dirs(base_dir)
    return removed


def create_switch_backup(arquivo_excel: str | Path, base_dir: Path | None = None, retention_days: int = SWITCH_BACKUP_RETENTION_DAYS) -> Path:
    arquivo_origem = Path(arquivo_excel)
    destino_dir = get_switch_backup_day_dir(base_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_backup = destino_dir / f"{arquivo_origem.stem}_backup_{timestamp}{arquivo_origem.suffix}"
    shutil.copy2(arquivo_origem, arquivo_backup)
    cleanup_old_switch_backups(base_dir, retention_days)
    return arquivo_backup


def get_switch_generated_file_path(file_prefix: str, extension: str = ".xlsx", base_dir: Path | None = None, reference: datetime | None = None) -> Path:
    timestamp = (reference or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return get_switch_backup_day_dir(base_dir, reference) / f"{file_prefix}_{timestamp}{extension}"


def migrate_existing_switch_backups(base_dir: Path | None = None) -> int:
    backup_root = get_switch_backup_root(base_dir)
    backup_root.mkdir(parents=True, exist_ok=True)

    moved = 0
    for pattern in SWITCH_BACKUP_PATTERNS:
        for file_path in backup_root.glob(pattern):
            target_dir = _resolve_target_dir_for_existing_file(file_path, backup_root)
            target_dir.mkdir(parents=True, exist_ok=True)
            destino = target_dir / file_path.name
            if destino == file_path:
                continue
            shutil.move(str(file_path), str(destino))
            moved += 1

    _prune_empty_switch_backup_dirs(base_dir)
    return moved


def _resolve_target_dir_for_existing_file(file_path: Path, backup_root: Path) -> Path:
    match = _TIMESTAMP_REGEX.search(file_path.name)
    if match:
        data = datetime.strptime(match.group(1), "%Y%m%d")
    else:
        data = datetime.fromtimestamp(file_path.stat().st_mtime)
    return backup_root / data.strftime("%Y") / data.strftime("%m") / data.strftime("%d")


def _prune_empty_switch_backup_dirs(base_dir: Path | None = None) -> None:
    backup_root = get_switch_backup_root(base_dir)
    if not backup_root.exists():
        return

    for directory in sorted((path for path in backup_root.rglob("*") if path.is_dir()), reverse=True):
        try:
            next(directory.iterdir())
        except StopIteration:
            try:
                directory.rmdir()
            except OSError:
                pass
        except OSError:
            continue