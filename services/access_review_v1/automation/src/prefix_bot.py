"""Captura o bloco inicial de evidências do AD na sessão local interativa."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from aduc_bot import capture, close, dialog, run_python, wait_for
from aduc_windows import all_top_windows, children, click_button, click_tab, close_dialog, only, stretch_security_dialog, top_windows, user32


CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])
EVIDENCE = ROOT / "dados" / "evidencias" / "ServidoresWindows"
PREFIX_SLOTS = (
    "p012_1", "p014_1", "p017_1", "p025_1", "p026_1",
    "p035_1", "p036_1", "p040_1", "p042_1", "p046_1", "p048_1", "p051_1", "p052_1", "p056_1", "p058_1",
)


def visible_child(hwnd: int, cls: str) -> dict:
    return only([x for x in children(hwnd) if x["class"] == cls and user32.IsWindowVisible(x["hwnd"])], cls=cls)


def archive_excess(prefix: str, pages: int) -> None:
    excess = [path for path in EVIDENCE.glob(f"{prefix}_*.png") if path.stem.rsplit("_", 1)[-1].isdigit() and int(path.stem.rsplit("_", 1)[-1]) > pages]
    if excess:
        archive = ROOT / "dados" / "execucoes" / "ServidoresWindows" / "prints_substituidos" / datetime.now().strftime("%Y%m%d-%H%M%S")
        archive.mkdir(parents=True, exist_ok=True)
        for path in excess:
            shutil.move(str(path), str(archive / path.name))


def capture_pages(pid: int, dialog_hwnd: int, list_hwnd: int, slot: str) -> int:
    count = user32.SendMessageW(list_hwnd, 0x1004, 0, 0)
    per_page = user32.SendMessageW(list_hwnd, 0x1028, 0, 0)
    if count <= 0 or per_page <= 0:
        raise RuntimeError(f"Lista vazia ou indisponível: {slot} ({count}/{per_page})")
    prefix = slot.removesuffix("_1")
    page = 0
    previous = -1
    while True:
        top = user32.SendMessageW(list_hwnd, 0x1027, 0, 0)
        if top <= previous:
            raise RuntimeError(f"Rolagem interrompida: {slot}")
        previous = top
        page += 1
        capture(pid, f"{prefix}_{page}", dialog_hwnd, force=True)
        print(f"{slot}: linhas {top + 1}-{min(count, top + per_page)}/{count}", flush=True)
        if top + per_page >= count:
            break
        user32.SendMessageW(list_hwnd, 0x0115, 3, 0)
        time.sleep(0.4)
    archive_excess(prefix, page)
    return page


def group_evidence(pid: int, main: dict, tree: dict, name: str, tree_path: str, location: str | None, members: str) -> None:
    props_title = f"Propriedades de {name}"
    close(pid, props_title)
    run_python("aduc_tree.py", pid, tree["hwnd"], "--select", tree_path)
    listview = wait_for(
        lambda: next(
            (item for item in children(main["hwnd"])
             if item["class"] == "SysListView32"
             and user32.IsWindowVisible(item["hwnd"])
             and user32.SendMessageW(item["hwnd"], 0x1004, 0, 0) > 0),
            None,
        ),
        f"lista do ADUC carregada: {tree_path}",
        30,
    )
    run_python("aduc_list.py", pid, listview["hwnd"], name, "--main-hwnd", main["hwnd"])
    if location:
        capture(pid, location)
    run_python("aduc_list.py", pid, listview["hwnd"], name, "--main-hwnd", main["hwnd"], "--open-properties")
    try:
        props = wait_for(lambda: dialog(pid, props_title), props_title)
        tab = visible_child(props["hwnd"], "SysTabControl32")
        click_tab(tab["hwnd"], 120, 26)
        time.sleep(0.5)
        if user32.SendMessageW(tab["hwnd"], 0x130B, 0, 0) != 1:
            raise RuntimeError(f"Aba Membros não selecionada em {name}")
        lists = [x for x in children(props["hwnd"]) if x["class"] == "SysListView32" and user32.IsWindowVisible(x["hwnd"])]
        if len(lists) == 1:
            # A caixa de propriedades é estreita; priorizar nomes inteiros dos membros.
            user32.SendMessageW(lists[0]["hwnd"], 0x101E, 0, 270)
            user32.SendMessageW(lists[0]["hwnd"], 0x101E, 1, 80)
            time.sleep(0.3)
            pages = capture_pages(pid, props["hwnd"], lists[0]["hwnd"], members)
            print(f"{name}: {pages} tela(s) de membros", flush=True)
        else:
            capture(pid, members, props["hwnd"], force=True)
            print(f"{name}: lista nativa não enumerada; captura visual única", flush=True)
    finally:
        close(pid, props_title)


def open_regionals_security(pid: int, main: dict, tree: dict) -> tuple[dict, dict]:
    close(pid, "Propriedades de Regionais")
    run_python("aduc_tree.py", pid, tree["hwnd"], "--select", "Galaxia.local/Regionais", "--main-hwnd", main["hwnd"], "--open-properties")
    props = wait_for(lambda: dialog(pid, "Propriedades de Regionais"), "Propriedades de Regionais")
    tab = visible_child(props["hwnd"], "SysTabControl32")
    click_tab(tab["hwnd"], 200, 10)
    time.sleep(0.6)
    if user32.SendMessageW(tab["hwnd"], 0x130B, 0, 0) != 3:
        raise RuntimeError("Aba Segurança da OU Regionais não selecionada")
    advanced = only(children(props["hwnd"]), cls="Button", title="A&vançadas")
    click_button(advanced["hwnd"])
    adv = wait_for(lambda: dialog(pid, "Configurações de Segurança Avançadas de Regionais"), "segurança avançada Regionais")
    size = stretch_security_dialog(adv["hwnd"], main["hwnd"])
    time.sleep(0.6)
    print(f"OU Regionais: diálogo ampliado para {size[0]}x{size[1]}", flush=True)
    return adv, visible_child(adv["hwnd"], "SysListView32")


def select_ace(pid: int, adv: dict, listview: dict, group: str) -> None:
    run_python("aduc_list.py", pid, listview["hwnd"], group, "--partial", "--main-hwnd", adv["hwnd"])


def permission_detail(pid: int, adv: dict, listview: dict, group: str, slot: str) -> None:
    select_ace(pid, adv, listview, group)
    prior = {x["hwnd"] for x in top_windows(pid)}
    view_button = only(children(adv["hwnd"]), cls="Button", title="E&xibir")
    click_button(view_button["hwnd"])
    details = wait_for(
        lambda: next((x for x in top_windows(pid) if x["class"] == "#32770" and x["hwnd"] not in prior), None),
        f"detalhes da permissão {group}",
    )
    try:
        wait_for(
            lambda: len([x for x in children(details["hwnd"]) if user32.IsWindowVisible(x["hwnd"])]) >= 8,
            f"conteúdo dos detalhes de permissão {group}",
            20,
        )
        time.sleep(1.5)
        capture(pid, slot, details["hwnd"], force=True)
        print(f"Detalhes de permissão: {group} ({details['title']})", flush=True)
    finally:
        close_dialog(details["hwnd"])
        wait_for(lambda: all(x["hwnd"] != details["hwnd"] for x in top_windows(pid)), "fechamento de detalhes")


def security_evidence(pid: int, adv: dict, listview: dict) -> None:
    slots = ("p025_1", "p026_1")
    count = user32.SendMessageW(listview["hwnd"], 0x1004, 0, 0)
    per_page = user32.SendMessageW(listview["hwnd"], 0x1028, 0, 0)
    if count <= 0 or per_page <= 0:
        raise RuntimeError("ACL da OU Regionais vazia")
    page = 0
    previous = -1
    while True:
        top = user32.SendMessageW(listview["hwnd"], 0x1027, 0, 0)
        if top <= previous:
            raise RuntimeError("A ACL da OU Regionais não avançou")
        previous = top
        if page < len(slots):
            slot = slots[page]
        else:
            slot = f"p030_{page - len(slots) + 2}"
        page += 1
        capture(pid, slot, adv["hwnd"], force=True)
        print(f"ACL Regionais {slot}: linhas {top + 1}-{min(count, top + per_page)}/{count}", flush=True)
        if top + per_page >= count:
            break
        user32.SendMessageW(listview["hwnd"], 0x0115, 3, 0)
        time.sleep(0.4)
    print(f"OU Regionais: {count} entradas, {page} página(s) necessárias; {len(slots)} posições do modelo", flush=True)


def capture_support_users(part: int, slot: str) -> None:
    title = f"Auditoria Usuarios Apoio - Parte {part}"
    before = {x["hwnd"] for x in all_top_windows() if x["title"] == title}
    signal = Path(tempfile.gettempdir()) / f"apoio-{os.getpid()}-{part}-{time.time_ns()}.done"
    script = CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "Usuarios-Apoio.ps1"
    if not script.is_file():
        raise FileNotFoundError(f"Script de usuários de apoio não encontrado: {script}")
    process = subprocess.Popen(
        [
            "powershell.exe", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(script),
            "-Parte", str(part), "-SinalConclusao", str(signal),
        ],
        cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    window = None
    try:
        window = wait_for(lambda: next((x for x in all_top_windows() if x["title"] == title and x["hwnd"] not in before), None), title, 40)
        wait_for(lambda: signal.exists(), str(signal), 90)
        if signal.read_text(encoding="ascii").strip() != "CONCLUIDO":
            raise RuntimeError(f"Consulta dos usuários de apoio falhou: parte {part}")
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "Capturar-Janela.ps1"), "-IdProcesso", str(window["pid"]), "-JanelaEmPrimeiroPlano", str(window["hwnd"]), "-MonitorMaior", "-Maximizar", "-Saida", str(EVIDENCE / f"{slot}.png")]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode or not (EVIDENCE / f"{slot}.png").exists():
            raise RuntimeError(f"Captura {slot} falhou: {result.stdout} {result.stderr}")
        print(f"Usuários de apoio: {slot}", flush=True)
    finally:
        if window:
            close_dialog(window["hwnd"])
        if process.poll() is None:
            process.terminate()
        signal.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    pid = args.pid
    main_window = only(top_windows(pid), cls="MMCMainFrame")
    tree = visible_child(main_window["hwnd"], "SysTreeView32")
    results: dict[str, str] = {}

    def attempt(name: str, slots: tuple[str, ...], action) -> None:
        if all((EVIDENCE / f"{slot}.png").exists() for slot in slots):
            results[name] = "OK (evidência preservada)"
            print(f"Evidência preservada: {name}", flush=True)
            return
        try:
            action()
            missing = [slot for slot in slots if not (EVIDENCE / f"{slot}.png").exists()]
            if missing:
                raise RuntimeError(f"Imagens ausentes: {missing}")
            results[name] = "OK"
        except Exception as error:
            results[name] = f"FALHA: {error}"
            print(f"FALHA {name}: {error}", flush=True)

    for name, path, slot in (
        ("Domain Admins", "Galaxia.local/Users", "p012_1"),
        ("Administrators", "Galaxia.local/Builtin", "p014_1"),
        ("Account Operators", "Galaxia.local/Builtin", "p017_1"),
    ):
        attempt(name, (slot,), lambda n=name, p=path, s=slot: group_evidence(pid, main_window, tree, n, p, None, s))

    attempt("GGS_Suporte_Corporativo", ("p035_1", "p036_1"), lambda: group_evidence(pid, main_window, tree, "GGS_Suporte_Corporativo", "Galaxia.local/Galaxia/Grupos de Seguranca", "p035_1", "p036_1"))
    attempt("GGS_Computadores_Dominio", ("p046_1", "p048_1"), lambda: group_evidence(pid, main_window, tree, "GGS_Computadores_Dominio", "Galaxia.local/Galaxia/Grupos de Seguranca", "p046_1", "p048_1"))

    adv = None
    security_slots = ("p025_1", "p026_1", "p042_1", "p056_1", "p058_1")
    try:
        if all((EVIDENCE / f"{slot}.png").exists() for slot in security_slots):
            for name in (
                "ACL OU Regionais", "Permissão especial Corporativo",
                "Delegação Computadores", "Permissão especial Computadores",
            ):
                results[name] = "OK (evidência preservada)"
            print("Evidências preservadas: segurança da OU Regionais", flush=True)
        else:
            adv, listview = open_regionals_security(pid, main_window, tree)
            attempt("ACL OU Regionais", ("p025_1", "p026_1"), lambda: security_evidence(pid, adv, listview))
            attempt("Permissão especial Corporativo", ("p042_1",), lambda: permission_detail(pid, adv, listview, "GGS_Suporte_Corporativo", "p042_1"))
            attempt("Delegação Computadores", ("p056_1",), lambda: (select_ace(pid, adv, listview, "GGS_Computadores_Dominio"), capture(pid, "p056_1", adv["hwnd"], force=True)))
            attempt("Permissão especial Computadores", ("p058_1",), lambda: permission_detail(pid, adv, listview, "GGS_Computadores_Dominio", "p058_1"))
    except Exception as error:
        results["Segurança OU Regionais"] = f"FALHA: {error}"
        print(f"FALHA segurança OU Regionais: {error}", flush=True)
    finally:
        for name in ("Configurações de Segurança Avançadas de Regionais", "Propriedades de Regionais"):
            try:
                close(pid, name)
            except Exception as error:
                print(f"Aviso ao fechar {name}: {error}", flush=True)

    from console_bot import capture_dsacls_corporate
    attempt("Delegação Corporativo", ("p040_1",), lambda: capture_dsacls_corporate("p040_1"))
    attempt("Usuários de apoio 1", ("p051_1",), lambda: capture_support_users(1, "p051_1"))
    attempt("Usuários de apoio 2", ("p052_1",), lambda: capture_support_users(2, "p052_1"))

    for item in PREFIX_SLOTS:
        if item not in results and not (EVIDENCE / f"{item}.png").exists():
            results[item] = "PENDENTE"
    summary = {"capturados": [slot for slot in PREFIX_SLOTS if (EVIDENCE / f"{slot}.png").exists()], "total": len(PREFIX_SLOTS), "etapas": results}
    output = ROOT / "dados" / "execucoes" / "ServidoresWindows" / "Resultado-BlocoInicial.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESUMO", json.dumps(summary, ensure_ascii=False), flush=True)
    if len(summary["capturados"]) < len(PREFIX_SLOTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
