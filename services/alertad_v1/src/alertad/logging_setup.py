from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


_SECRET_KEYS = (
    "password|passwd|client_secret|access_token|refresh_token|"
    "authorization|token|secret"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_QUOTED_SECRET_PATTERN = re.compile(
    rf"(?i)(?P<prefix>[\"']?(?:{_SECRET_KEYS})[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)"
)
_UNQUOTED_SECRET_PATTERN = re.compile(
    rf"(?i)(?P<prefix>\b(?:{_SECRET_KEYS})\b\s*[:=]\s*)"
    rf"(?P<value>(?![\"']).*?)(?=(?:[,;]|\s+\b(?:{_SECRET_KEYS})\b\s*[:=]|$))"
)


def sanitize_text(value: object, *, limit: int = 1024) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _QUOTED_SECRET_PATTERN.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"[REDACTED]{match.group('quote')}"
        ),
        text,
    )
    text = _UNQUOTED_SECRET_PATTERN.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        text,
    )
    return text[:limit]


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_text(record.getMessage()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(
    log_file: str | Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = 5_000_000,
    backup_count: int = 10,
) -> None:
    destination = Path(log_file).resolve(strict=False)
    if str(destination).startswith(("\\\\", "//")):
        raise ValueError("Logs devem usar um caminho local")
    if max_bytes < 1024 or backup_count < 1:
        raise ValueError("Configuração de rotação de logs inválida")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        destination,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
