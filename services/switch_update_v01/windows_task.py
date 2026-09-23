"""Integracao pequena e sem shell com a tarefa externa do Windows."""

from __future__ import annotations

import subprocess


DEFAULT_TASK_NAME = "SentinelSwitchUpdateWorker"


def worker_task_health(task_name: str = DEFAULT_TASK_NAME) -> dict:
    """Informa apenas se a tarefa configurada pode ser consultada."""
    try:
        result = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", task_name],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return {"task_name": task_name, "available": False}
    return {"task_name": task_name, "available": result.returncode == 0}


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
