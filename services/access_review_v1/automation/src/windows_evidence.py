"""Captura o monitor do Windows, incluindo a barra de tarefas e seu relógio."""
from __future__ import annotations
import subprocess, sys, time
from pathlib import Path

SCRIPT=Path(__file__).with_name("Capturar-Monitor.ps1")

def capture_monitor(page, path: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Evidências com data e horário exigem uma sessão gráfica do Windows.")
    page.bring_to_front(); time.sleep(.5)
    title=page.title()
    result=subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(SCRIPT),"-Saida",str(path),"-TituloJanela",title],text=True,capture_output=True,encoding="utf-8",errors="replace")
    if result.returncode or not path.is_file() or path.stat().st_size < 20_000:
        raise RuntimeError(f"Captura de monitor inválida: {path.name}: {result.stdout} {result.stderr}")
