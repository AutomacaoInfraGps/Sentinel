"""Captura evidências regionais no ADUC em sessão interativa elevada.

O bot navega no ADUC real; não desenha telas nem transforma texto em imagem.
Cada PNG só é salvo quando a janela e o objeto esperados estão visíveis.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from access_review_progress import publish_detail

from aduc_windows import children, click_button, click_tab, close_dialog, only, stretch_security_dialog, top_windows, user32
from console_bot import capture_dsacls_corporate, capture_script

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])


def wait_for(predicate, label: str, seconds: int = 15):
    publish_detail('Aguardando janela do ADUC', target=label)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise TimeoutError(f"Janela não apareceu: {label}")


def run_python(script: str, *args: object) -> None:
    command = [sys.executable, str(CODE_ROOT / "src" / script), *(str(x) for x in args)]
    result = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)}: {result.stdout} {result.stderr}")
    print(f"ADUC command completed: {script}", flush=True)


def capture(pid: int, slot: str, dialog_hwnd: int | None = None, force: bool = False) -> None:
    target = ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slot}.png"
    if target.exists() and not force:
        print(f"Já capturada: {slot}", flush=True)
        return
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(CODE_ROOT / "auditorias" / "servidores-windows" / "scripts" / "Capturar-Janela.ps1"), "-IdProcesso", str(pid), "-Saida", str(target),
    ]
    if dialog_hwnd:
        command += ["-JanelaEmPrimeiroPlano", str(dialog_hwnd), "-AreaJanelaPrincipal"]
    result = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode or not target.exists():
        raise RuntimeError(f"Falha de captura {slot}: {result.stdout} {result.stderr}")
    print(f"Capturada no ADUC: {slot}", flush=True)


def dialog(pid: int, name: str) -> dict | None:
    return next((x for x in top_windows(pid) if x["class"] == "#32770" and x["title"] == name), None)


def close(pid: int, name: str) -> None:
    item = dialog(pid, name)
    if item:
        close_dialog(item["hwnd"])
        wait_for(lambda: dialog(pid, name) is None, f"fechamento de {name}")


def tree_path(dn: str) -> str:
    parts = [item[3:] for item in dn.split(",") if item.upper().startswith("OU=")]
    return "Galaxia.local/" + "/".join(reversed(parts))


def canonical_name(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(ch))


def resolve_ad_group(model_name: str, current_groups: list[dict]) -> str:
    """Usa o nome retornado pelo AD; a grafia do modelo fica só no DOCX."""
    matches = [item["Nome"] for item in current_groups if canonical_name(item["Nome"]) == canonical_name(model_name)]
    if len(matches) != 1:
        raise ValueError(f"Grupo {model_name!r} corresponde a {len(matches)} objetos na coleta atual")
    return matches[0]


def capture_group_members(pid: int, main: dict, tree: dict, container: str, group: str, slot: str) -> None:
    if (ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slot}.png").exists():
        print(f"Já capturada: {slot}", flush=True)
        return
    dialog_name = f"Propriedades de {group}"
    close(pid, dialog_name)
    run_python("aduc_tree.py", pid, tree["hwnd"], "--select", container)
    listview = only(children(main["hwnd"]), cls="SysListView32")
    run_python("aduc_list.py", pid, listview["hwnd"], group, "--main-hwnd", main["hwnd"], "--open-properties")
    props = wait_for(lambda: dialog(pid, dialog_name), dialog_name)
    tab = only(children(props["hwnd"]), cls="SysTabControl32")
    click_tab(tab["hwnd"], 120, 26)
    time.sleep(0.5)
    if user32.SendMessageW(tab["hwnd"], 0x130B, 0, 0) != 1:
        raise RuntimeError(f"A aba Membros não foi selecionada em {dialog_name}")
    capture(pid, slot, props["hwnd"])
    close(pid, dialog_name)


def reuse_evidence(source_slot: str, target_slot: str) -> bool:
    evidence = ROOT / "dados" / "evidencias" / "ServidoresWindows"
    source = evidence / f"{source_slot}.png"
    target = evidence / f"{target_slot}.png"
    if target.exists():
        print(f"Já capturada: {target_slot}", flush=True)
        return True
    if not source.exists():
        return False
    shutil.copy2(source, target)
    print(f"Evidência atual reutilizada: {source_slot} -> {target_slot}", flush=True)
    return True


def capture_matrix(
    pid: int,
    region: dict,
    slots: list[dict],
    corporate_group: str,
    domain_admins: str,
    deny_group: str,
) -> None:
    if len(slots) != 7 or len(region["ou_atual"]) != 1:
        raise ValueError(f"Seção Matriz fora do padrão de sete capturas: {region['secao']}")
    ou_dn = region["ou_atual"][0]
    ou_name = ou_dn.split(",", 1)[0][3:]
    main = only(top_windows(pid), cls="MMCMainFrame")
    tree = only(children(main["hwnd"]), cls="SysTreeView32")
    ou_dialog = f"Propriedades de {ou_name}"
    advanced_title = f"Configurações de Segurança Avançadas de {ou_name}"

    # As cinco evidências independentes são concluídas antes da ACL especial.
    if not reuse_evidence("p036_1", slots[1]["slot"]):
        capture_group_members(
            pid, main, tree, "Galaxia.local/Galaxia/Grupos de Seguranca", corporate_group, slots[1]["slot"]
        )
    if not reuse_evidence("p012_1", slots[2]["slot"]):
        capture_group_members(pid, main, tree, "Galaxia.local/Users", domain_admins, slots[2]["slot"])
    capture_dsacls_corporate(slots[3]["slot"])
    capture_script("Allow", domain_admins, slots[4]["slot"], ou_dn)

    # ACL da Matriz, destacando o Corporativo e depois a regra Deny.
    acl_slots = (slots[0]["slot"], slots[5]["slot"])
    if any(not (ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slot}.png").exists() for slot in acl_slots):
        close(pid, advanced_title)
        close(pid, ou_dialog)
        run_python("aduc_tree.py", pid, tree["hwnd"], "--select", tree_path(ou_dn), "--main-hwnd", main["hwnd"], "--open-properties")
        props = wait_for(lambda: dialog(pid, ou_dialog), ou_dialog)
        tab = only(children(props["hwnd"]), cls="SysTabControl32")
        click_tab(tab["hwnd"], 200, 10)
        time.sleep(0.6)
        if user32.SendMessageW(tab["hwnd"], 0x130B, 0, 0) != 3:
            raise RuntimeError(f"A aba Segurança não foi selecionada em {ou_dialog}")
        advanced = only(children(props["hwnd"]), cls="Button", title="A&vançadas")
        click_button(advanced["hwnd"])
        adv = wait_for(lambda: dialog(pid, advanced_title), advanced_title)
        stretch_security_dialog(adv["hwnd"], main["hwnd"])
        time.sleep(0.6)
        security_list = only(children(adv["hwnd"]), cls="SysListView32")
        if not (ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slots[0]['slot']}.png").exists():
            # Nesta ACL nativa, a coluna Principal não é exposta por Win32/UIA.
            # O primeiro Allow é o Corporativo, conforme o padrão visual do modelo.
            run_python("aduc_list.py", pid, security_list["hwnd"], corporate_group, "--index", 29)
            capture(pid, slots[0]["slot"], adv["hwnd"])
        if not (ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slots[5]['slot']}.png").exists():
            run_python("aduc_list.py", pid, security_list["hwnd"], deny_group, "--index", 0)
            capture(pid, slots[5]["slot"], adv["hwnd"])
        close(pid, advanced_title)
        close(pid, ou_dialog)
    capture_script("Deny", deny_group, slots[6]["slot"])

def capture_region(pid: int, region: dict, slots: list[dict], group: str, deny_group: str) -> None:
    title = region["secao"]
    if len(slots) != 5 or len(region["grupos_suporte_modelo"]) != 1 or len(region["ou_atual"]) != 1:
        raise ValueError(f"Regional fora do padrão de cinco capturas: {title}")
    ou_dn = region["ou_atual"][0]
    main = only(top_windows(pid), cls="MMCMainFrame")
    tree = only(children(main["hwnd"]), cls="SysTreeView32")
    group_dialog = f"Propriedades de {group}"
    ou_name = ou_dn.split(",", 1)[0][3:]
    ou_dialog = f"Propriedades de {ou_name}"
    close(pid, group_dialog)
    close(pid, ou_dialog)

    # 1 e 2: localização e membros. Em retomadas, não repete o que já existe.
    location_exists = (ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slots[0]['slot']}.png").exists()
    members_exists = (ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{slots[1]['slot']}.png").exists()
    listview = None
    if not location_exists or not members_exists:
        run_python("aduc_tree.py", pid, tree["hwnd"], "--select", "Galaxia.local/Galaxia/Grupos de Seguranca")
        listview = only(children(main["hwnd"]), cls="SysListView32")
    if not location_exists:
        run_python("aduc_list.py", pid, listview["hwnd"], group)
        capture(pid, slots[0]["slot"])

    # 2: propriedades do grupo, aba Membros.
    if not members_exists:
        run_python("aduc_list.py", pid, listview["hwnd"], group, "--main-hwnd", main["hwnd"], "--open-properties")
        props = wait_for(lambda: dialog(pid, group_dialog), group_dialog)
        tab = only(children(props["hwnd"]), cls="SysTabControl32")
        click_tab(tab["hwnd"], 120, 26)
        time.sleep(0.5)
        if user32.SendMessageW(tab["hwnd"], 0x130B, 0, 0) != 1:
            raise RuntimeError(f"A aba Membros não foi selecionada em {group_dialog}")
        capture(pid, slots[1]["slot"], props["hwnd"])
        close(pid, group_dialog)

    # 3: janela PowerShell real com a consulta Allow do grupo de suporte.
    capture_script("Allow", group, slots[2]["slot"], ou_dn)

    # 4: segurança avançada da OU e regra Deny.
    security_slot = slots[3]["slot"]
    run_python("aduc_tree.py", pid, tree["hwnd"], "--select", tree_path(ou_dn), "--main-hwnd", main["hwnd"], "--open-properties")
    props = wait_for(lambda: dialog(pid, ou_dialog), ou_dialog)
    tab = only(children(props["hwnd"]), cls="SysTabControl32")
    click_tab(tab["hwnd"], 200, 10)
    time.sleep(0.6)
    if user32.SendMessageW(tab["hwnd"], 0x130B, 0, 0) != 3:
        raise RuntimeError(f"A aba Segurança não foi selecionada em {ou_dialog}")
    advanced = only(children(props["hwnd"]), cls="Button", title="A&vançadas")
    click_button(advanced["hwnd"])
    advanced_title = f"Configurações de Segurança Avançadas de {ou_name}"
    adv = wait_for(lambda: dialog(pid, advanced_title), advanced_title)
    stretch_security_dialog(adv["hwnd"], main["hwnd"])
    time.sleep(0.6)
    security_list = only(children(adv["hwnd"]), cls="SysListView32")
    if not (ROOT / "dados" / "evidencias" / "ServidoresWindows" / f"{security_slot}.png").exists():
        # As ACLs seguem a ordem canônica: a regra Deny explícita fica na
        # primeira linha. A captura mostra somente essa entrada selecionada.
        run_python("aduc_list.py", pid, security_list["hwnd"], deny_group, "--index", 0)
        capture(pid, security_slot, adv["hwnd"])
    close(pid, advanced_title)
    close(pid, ou_dialog)

    # 5: membros diretos do grupo de bloqueio na janela PowerShell real.
    capture_script("Deny", deny_group, slots[4]["slot"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True, help="PID da janela ADUC elevada")
    parser.add_argument("--secao", required=True, help="Título da seção do inventário, por exemplo OU Amazonas")
    args = parser.parse_args()
    publish_detail('Regional do Active Directory', target=args.secao)
    inventory = json.loads((ROOT / "dados" / "execucoes" / "Inventario-Evidencias-ServidoresWindows.json").read_text(encoding="utf-8"))
    region = next((x for x in inventory["secoes"] if x["secao"] == args.secao), None)
    if not region:
        raise ValueError(f"Seção não encontrada: {args.secao}")
    if len(region["grupos_suporte_modelo"]) != 1 or len(region["grupos_bloqueio_na_imagem_modelo"]) != 1:
        raise ValueError(f"Grupos da seção não identificados de forma única: {args.secao}")
    collection = json.loads((ROOT / "dados" / "execucoes" / "ServidoresWindows" / "Coleta-ServidoresWindows.json").read_text(encoding="utf-8-sig"))
    group = resolve_ad_group(region["grupos_suporte_modelo"][0], collection["Grupos"])
    deny_group = resolve_ad_group(region["grupos_bloqueio_na_imagem_modelo"][0], collection["Grupos"])
    print(f"Grupos consultados no AD: suporte={group}; bloqueio={deny_group}", flush=True)
    publish_detail('Grupo de suporte', target=group)
    publish_detail('Grupo de bloqueio', target=deny_group)
    slots = [x for x in inventory["slots"] if x["secao"] == args.secao]
    ou_name = region["ou_atual"][0].split(",", 1)[0][3:] if region["ou_atual"] else ""
    domain_admins = resolve_ad_group("Domain Admins", collection["Grupos"])
    try:
        if len(slots) == 7 and "Matriz" in region["secao"]:
            capture_matrix(args.pid, region, slots, group, domain_admins, deny_group)
        else:
            capture_region(args.pid, region, slots, group, deny_group)
    finally:
        for name in (
            f"Configurações de Segurança Avançadas de {ou_name}",
            f"Propriedades de {ou_name}",
            f"Propriedades de {group}",
            f"Propriedades de {domain_admins}",
        ):
            if name:
                try:
                    close(args.pid, name)
                except Exception as error:
                    print(f"Aviso ao fechar {name}: {error}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        publish_detail('Falha no bot ADUC; consulte a regional e o objeto anteriores', status='warning', error=error)
        raise
