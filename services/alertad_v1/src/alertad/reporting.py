from __future__ import annotations

import csv
import os
from pathlib import Path

from .persistence import EventStore


REPORT_FIELDS = (
    "alert_id",
    "event_id",
    "event_record_id",
    "source_computer",
    "time_created_utc",
    "target_user_name",
    "member_sid",
    "attentions",
)


def _same_existing_file(first: Path, second: Path) -> bool:
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def _validate_report_destination(store: EventStore, destination: Path) -> None:
    database = store.database_path.resolve(strict=False)
    resolved_destination = destination.resolve(strict=False)
    protected = (
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        Path(f"{database}-journal"),
        Path(f"{database}.worker.lock"),
    )
    destination_key = os.path.normcase(str(resolved_destination))
    for protected_path in protected:
        if destination_key == os.path.normcase(str(protected_path.resolve(strict=False))):
            raise ValueError("O relatório não pode sobrescrever arquivos protegidos do SQLite")
        if _same_existing_file(resolved_destination, protected_path):
            raise ValueError("O relatório não pode usar um alias de arquivo protegido")


def _csv_safe(value: object) -> str:
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def export_attention_report(store: EventStore, output_path: str | Path) -> int:
    destination = Path(output_path)
    _validate_report_destination(store, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = store.attention_report_rows()
    with destination.open("w", newline="", encoding="utf-8-sig") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=REPORT_FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(
            {name: _csv_safe(value) for name, value in row.items()}
            for row in rows
        )
    return len(rows)

