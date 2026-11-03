"""Executa scripts de auditoria em janelas PowerShell reais e captura a tela."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import time
from pathlib import Path

from aduc_windows import all_top_windows, close_dialog

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])


def wait_for(predicate, label: str, seconds: int = 45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.3)
    raise TimeoutError(f"Resultado não apareceu: {label}")


def read_signal(path: Path) -> str | None:
    """Lê o sinal somente depois que o PowerShell liberar o arquivo."""
    try:
        value = path.read_text(encoding="ascii", errors="replace").strip()
        return value or None
    except (FileNotFoundError, PermissionError):
        return None


def remove_signal(path: Path) -> None:
    deadline = time.monotonic() + 5
    while True:
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                print(f"Aviso: sinal temporário ainda está em uso: {path}", flush=True)
                return
            time.sleep(0.2)


def capture_dsacls_corporate(slot: str) -> None:
    """Executa e captura o comando DSACLS exigido para a delegação corporativa."""
    target = ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slot}.png"
    if target.exists():
        print(f"Já capturada: {slot}", flush=True)
        return

    group = "GGS_Suporte_Corporativo"
    title = f"Auditoria DSACLS - {group}"
    before = {x["hwnd"] for x in all_top_windows() if x["title"] == title}
    script = CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "DSACLS-Corporativo.ps1"
    report = ROOT / "dados" / "execucoes" / "ServidoresWindows" / "DSACLS" / "GGS_Suporte_Corporativo.txt"
    signal = Path(tempfile.gettempdir()) / f"auditoria-dsacls-{os.getpid()}-{time.time_ns()}.done"
    process = subprocess.Popen(
        [
            "powershell.exe", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-ArquivoRelatorio", str(report), "-SinalConclusao", str(signal),
        ],
        cwd=ROOT,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    window = None
    try:
        window = wait_for(
            lambda: next((x for x in all_top_windows() if x["title"] == title and x["hwnd"] not in before), None),
            title,
        )
        status = wait_for(lambda: read_signal(signal), str(signal), seconds=90)
        if status != "CONCLUIDO":
            raise RuntimeError(f"Consulta DSACLS falhou: {status}")
        if not report.is_file():
            raise RuntimeError(f"Relatório não encontrado: {report}")
        report_lines = report.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        expected = 'dsacls "OU=Regionais,DC=galaxia,DC=local" | findstr /i "GGS_Suporte_Corporativo"'
        if not report_lines or report_lines[0] != expected:
            raise RuntimeError("O relatório DSACLS não contém o comando esperado")
        if not any("GGS_Suporte_Corporativo" in line for line in report_lines[2:]):
            raise RuntimeError("O relatório DSACLS não contém permissões do grupo esperado")
        time.sleep(0.5)
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "Capturar-Janela.ps1"), "-IdProcesso", str(window["pid"]),
                "-JanelaEmPrimeiroPlano", str(window["hwnd"]), "-MonitorMaior", "-Maximizar",
                "-Saida", str(target),
            ],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode or not target.is_file():
            raise RuntimeError(f"Falha ao capturar {slot}: {result.stdout} {result.stderr}")
        print(f"Capturada consulta DSACLS: {slot}", flush=True)
    finally:
        if window is not None:
            close_dialog(window["hwnd"])
            try:
                wait_for(lambda: not any(x["hwnd"] == window["hwnd"] for x in all_top_windows()), title, seconds=5)
            except TimeoutError:
                print(f"Aviso: a janela {title} não fechou após WM_CLOSE", flush=True)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        remove_signal(signal)


def capture_script(mode: str, group: str, slot: str, ou_dn: str = "") -> None:
    if mode not in {"Allow", "Deny"}:
        raise ValueError(mode)
    target = ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slot}.png"
    if target.exists():
        print(f"Já capturada: {slot}", flush=True)
        return
    title = f"Auditoria {mode} - {group}"
    before = {x["hwnd"] for x in all_top_windows() if x["title"] == title}
    if mode == "Allow":
        if not ou_dn:
            raise ValueError("OU obrigatória para Allow")
        script = CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "Permissao-Allow.ps1"
        ou_name = ou_dn.split(",", 1)[0][3:]
        report = ROOT / "dados" / "execucoes" / "ServidoresWindows" / "Allow" / f"Permissoes_{ou_name}_{group}.txt"
        args = ["-OU", ou_dn, "-Grupo", group, "-PastaRelatorio", str(report.parent)]
    else:
        script = CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "Permissao-Deny.ps1"
        report = ROOT / "dados" / "execucoes" / "ServidoresWindows" / "Deny" / f"Membros_{group}.txt"
        args = ["-Grupo", group, "-PastaRelatorio", str(report.parent)]
    # A existência de um TXT antigo não pode validar uma consulta atual.
    report.unlink(missing_ok=True)
    signal = Path(tempfile.gettempdir()) / f"auditoria-{mode.lower()}-{os.getpid()}-{time.time_ns()}.done"
    args += ["-SinalConclusao", str(signal)]
    process = subprocess.Popen(
        ["powershell.exe", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        cwd=ROOT,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    window = None
    try:
        window = wait_for(
            lambda: next((x for x in all_top_windows() if x["title"] == title and x["hwnd"] not in before), None),
            title,
        )
        status = wait_for(lambda: read_signal(signal), str(signal), seconds=90)
        if status != "CONCLUIDO":
            raise RuntimeError(f"Consulta {mode} falhou: {group}")
        if not report.is_file():
            raise RuntimeError(f"Relatório não encontrado: {report}")
        time.sleep(0.5)
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "Capturar-Janela.ps1"), "-IdProcesso", str(window["pid"]),
                "-JanelaEmPrimeiroPlano", str(window["hwnd"]), "-MonitorMaior", "-Maximizar",
                "-Saida", str(target),
            ],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode or not target.is_file():
            raise RuntimeError(f"Falha ao capturar {slot}: {result.stdout} {result.stderr}")
        print(f"Capturada na janela PowerShell: {slot}", flush=True)
    finally:
        if window is not None:
            close_dialog(window["hwnd"])
            try:
                wait_for(lambda: not any(x["hwnd"] == window["hwnd"] for x in all_top_windows()), title, seconds=5)
            except TimeoutError:
                print(f"Aviso: a janela {title} não fechou após WM_CLOSE", flush=True)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        remove_signal(signal)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["Allow", "Deny", "DSACLS"])
    parser.add_argument("group")
    parser.add_argument("slot")
    parser.add_argument("--ou", default="")
    args = parser.parse_args()
    if args.mode == "DSACLS":
        if args.group != "GGS_Suporte_Corporativo":
            raise ValueError("O modo DSACLS é exclusivo do GGS_Suporte_Corporativo")
        capture_dsacls_corporate(args.slot)
    else:
        capture_script(args.mode, args.group, args.slot, args.ou)


if __name__ == "__main__":
    main()
