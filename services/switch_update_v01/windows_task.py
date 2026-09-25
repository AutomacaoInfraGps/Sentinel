"""Integracao pequena e sem shell com a tarefa externa do Windows."""

from __future__ import annotations

import subprocess
from pathlib import Path
import time


DEFAULT_TASK_NAME = "SentinelSwitchUpdateWorker"
WORKER_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "switch_update_worker.log"
WORKER_HEALTH_MAX_AGE_SECONDS = 150


def _worker_log_is_recent() -> bool:
    try:
        return (time.time() - WORKER_LOG_PATH.stat().st_mtime) <= WORKER_HEALTH_MAX_AGE_SECONDS
    except OSError:
        return False


def worker_task_health(task_name: str = DEFAULT_TASK_NAME) -> dict:
    """Confirma a atividade do worker pelo heartbeat gravado no log compartilhado."""
    if _worker_log_is_recent():
        return {"task_name": task_name, "available": True, "source": "recent_worker_log"}
    return {"task_name": task_name, "available": False, "source": "stale_worker_log"}


def trigger_worker_task(task_name: str = DEFAULT_TASK_NAME) -> bool:
    """Solicita uma passagem imediata; a repeticao por minuto e o fallback."""
    try:
        result = subprocess.run(
            ["schtasks.exe", "/Run", "/TN", task_name],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
