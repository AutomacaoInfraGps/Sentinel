"""Captura evidências reais dos usuários no Zabbix e no Grafana."""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from access_review_progress import publish_detail, publish_progress
from windows_evidence import capture_monitor


CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])
REQUIRED_SECRETS = (
    "ZABBIX_USUARIO",
    "ZABBIX_SENHA",
    "GRAFANA_USUARIO",
    "GRAFANA_SENHA",
)


def largest_monitor() -> dict[str, int] | None:
    """Retorna a área útil do maior monitor no Windows."""
    if sys.platform != "win32":
        return None

    class Rect(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("monitor", Rect), ("work", Rect), ("flags", ctypes.c_ulong)]

    monitors: list[dict[str, int]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Rect), ctypes.c_long)

    def collect(handle, _dc, _rect, _data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(MonitorInfo)
        if ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            monitors.append({
                "x": info.work.left,
                "y": info.work.top,
                "width": info.work.right - info.work.left,
                "height": info.work.bottom - info.work.top,
            })
        return 1

    ctypes.windll.user32.SetProcessDPIAware()
    ctypes.windll.user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
    return max(monitors, key=lambda item: item["width"] * item["height"], default=None)


def maximize_window(context, page, headless: bool) -> None:
    if headless:
        return
    session = context.new_cdp_session(page)
    window_id = session.send("Browser.getWindowForTarget")["windowId"]
    session.send("Browser.setWindowBounds", {
        "windowId": window_id,
        "bounds": {"windowState": "maximized"},
    })
    time.sleep(0.5)


def read_env(path: Path) -> dict[str, str]:
    from access_review_credentials import load_credentials
    return load_credentials(path, REQUIRED_SECRETS)


def visible(locator):
    try:
        for index in range(locator.count()):
            item = locator.nth(index)
            if item.is_visible():
                return item
    except Exception:
        return None
    return None


def first_visible(page, selectors: list[str], label: str, timeout_seconds: float = 20):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for selector in selectors:
            item = visible(page.locator(selector))
            if item is not None:
                return item
        time.sleep(0.25)
    raise RuntimeError(f"Controle não encontrado: {label}")


def named(page, name: str, *, last: bool = False, timeout_seconds: float = 20):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        candidates = []
        for role in ("link", "button", "tab"):
            locator = page.get_by_role(role, name=name, exact=True)
            for index in range(locator.count()):
                item = locator.nth(index)
                if item.is_visible():
                    candidates.append(item)
        if not candidates:
            locator = page.get_by_text(name, exact=True)
            for index in range(locator.count()):
                item = locator.nth(index)
                if item.is_visible():
                    candidates.append(item)
        if candidates:
            return candidates[-1] if last else candidates[0]
        time.sleep(0.25)
    raise RuntimeError(f"Item visível não encontrado: {name}")


def settle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        page.wait_for_load_state("domcontentloaded")
    try:
        page.evaluate("document.fonts && document.fonts.ready")
    except Exception:
        pass
    time.sleep(0.7)


def wait_until_logged_in(page, system: str, authenticated_selectors: list[str]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if any(visible(page.locator(selector)) is not None for selector in authenticated_selectors):
            return
        password = visible(page.locator("input[type='password']"))
        if password is None and "/login" not in page.url.casefold():
            return
        time.sleep(0.25)
    raise RuntimeError(f"O {system} permaneceu na tela de login. Confira usuário e senha.")


def screenshot(page, path: Path, *, full_page: bool) -> None:
    settle(page)
    path.parent.mkdir(parents=True, exist_ok=True)
    capture_monitor(page, path)


def extract_table(table) -> list[dict[str, str]]:
    """Extrai cabeçalhos e células visíveis de uma tabela HTML."""
    payload = table.evaluate(
        """
        table => {
          const clean = value => (value || '').replace(/\s+/g, ' ').trim();
          const headers = [...table.querySelectorAll('thead th')].map(cell => clean(cell.innerText));
          return [...table.querySelectorAll('tbody tr')].map(row => {
            const cells = [...row.querySelectorAll('td')].map(cell => clean(cell.innerText));
            const record = {};
            headers.forEach((header, index) => { if (header) record[header] = cells[index] || ''; });
            return record;
          });
        }
        """
    )
    return [record for record in payload if any(record.values())]


def login_zabbix(page, url: str, username: str, password: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    user = first_visible(page, ["input[name='name']", "#name", "input[autocomplete='username']"], "usuário do Zabbix")
    secret = first_visible(page, ["input[name='password']", "#password", "input[type='password']"], "senha do Zabbix")
    user.fill(username)
    secret.fill(password)
    button = visible(page.get_by_role("button", name=re.compile(r"(sign in|entrar|login)", re.I)))
    if button is None:
        button = first_visible(page, ["button[type='submit']", "input[type='submit']"], "entrar no Zabbix")
    button.click()
    page.wait_for_load_state("domcontentloaded")
    wait_until_logged_in(
        page,
        "Zabbix",
        ["a[href*='action=logout']", "a[href*='action=user.list']", ".sidebar-nav", "nav"],
    )


def open_zabbix_users(page) -> None:
    # No modo recolhido, o Zabbix oculta os textos do menu. Expande a barra
    # antes de procurar Users e mantém a URL direta como último recurso.
    if visible(page.get_by_text("Users", exact=True)) is None:
        toggle = None
        for selector in (
            ".sidebar-button-toggle",
            "button[aria-label*='sidebar' i]",
            "button[aria-label*='menu' i]",
            "button[title*='expand' i]",
            "button[title*='menu' i]",
        ):
            toggle = visible(page.locator(selector))
            if toggle is not None:
                break
        if toggle is not None:
            toggle.click()
            time.sleep(0.25)
    try:
        named(page, "Users", timeout_seconds=3).click()
    except Exception:
        page.goto(urljoin(page.url, "zabbix.php?action=user.list"), wait_until="domcontentloaded")
        first_visible(page, ["table", ".list-table"], "lista de usuários do Zabbix")
        return
    time.sleep(0.25)
    try:
        named(page, "Users", last=True, timeout_seconds=3).click()
    except Exception:
        submenu = first_visible(page, ["a[href*='action=user.list']"], "submenu Users do Zabbix", timeout_seconds=3)
        submenu.click()
    page.wait_for_url(re.compile(r"action=user\.list"), timeout=20_000)
    first_visible(page, ["table", ".list-table"], "lista de usuários do Zabbix")


def prepare_zabbix_evidence(page) -> None:
    # O formulário de filtro não faz parte da evidência e ocupa altura útil.
    filter_control = visible(page.get_by_text("Filter", exact=True))
    if filter_control is not None:
        filter_control.click()
        time.sleep(0.5)
    # A lista usa rolagem interna. Esta redução mantém todos os usuários em
    # uma única captura e continua legível no monitor de 1920 pixels.
    page.evaluate("document.body.style.zoom = '85%'")
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)


def logout_zabbix(page) -> None:
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    time.sleep(0.4)
    item = visible(page.get_by_role("link", name=re.compile(r"sign out|sair", re.I)))
    if item is None:
        item = first_visible(page, ["a[href*='action=logout']"], "Sign out do Zabbix")
    item.click()
    page.wait_for_load_state("domcontentloaded")


def login_grafana(page, url: str, username: str, password: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    user = first_visible(page, ["input[name='user']", "input[autocomplete='username']"], "usuário do Grafana")
    secret = first_visible(page, ["input[name='password']", "input[type='password']"], "senha do Grafana")
    user.fill(username)
    secret.fill(password)
    button = visible(page.get_by_role("button", name=re.compile(r"(log in|sign in|entrar)", re.I)))
    if button is None:
        button = first_visible(page, ["button[type='submit']"], "entrar no Grafana")
    button.click()
    page.wait_for_load_state("domcontentloaded")
    wait_until_logged_in(
        page,
        "Grafana",
        ["a[href*='/admin/users']", "[data-testid*='avatar' i]", "nav", "aside"],
    )


def open_grafana_users(page) -> None:
    named(page, "Administration").click()
    time.sleep(0.4)
    named(page, "Users and access").click()
    time.sleep(0.4)
    named(page, "Users", last=True).click()
    page.wait_for_url(re.compile(r"/admin/users"), timeout=20_000)
    try:
        named(page, "Organization users").click()
    except Exception:
        first_visible(
            page,
            ["[role='tab']:has-text('Organization users')", "a:has-text('Organization users')"],
            "Organization users",
        ).click()
    first_visible(page, ["table", "[role='table']", "[data-testid*='user']"], "lista de usuários do Grafana")


def scroll_grafana_bottom(page) -> None:
    page.evaluate(
        """
        () => {
          const nodes = [document.scrollingElement, ...document.querySelectorAll('*')]
            .filter(Boolean)
            .filter(e => e.scrollHeight > e.clientHeight + 100);
          const target = nodes.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
          if (target) target.scrollTop = target.scrollHeight;
          window.scrollTo(0, document.documentElement.scrollHeight);
        }
        """
    )
    time.sleep(0.5)


def open_grafana_second_page(page) -> None:
    table = first_visible(page, ["table", "[role='table']", "[data-testid*='user']"], "lista de usuários do Grafana")
    before = table.inner_text()
    second_page = visible(page.get_by_role("button", name="2", exact=True))
    if second_page is None:
        second_page = first_visible(
            page,
            ["button[aria-label*='page 2' i]", "button:has-text('2')"],
            "página 2 do Grafana",
        )
    if not second_page.is_enabled():
        raise RuntimeError("O botão da página 2 do Grafana está desabilitado")
    second_page.click()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if table.inner_text() != before:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("A tabela do Grafana não mudou após abrir a página 2")
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)


def logout_grafana(page) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    selectors = [
        "button[aria-label*='profile' i]",
        "button[aria-label*='avatar' i]",
        "[data-testid*='avatar' i]",
        "header button:last-of-type",
    ]
    first_visible(page, selectors, "perfil do Grafana").click()
    time.sleep(0.4)
    item = visible(page.get_by_role("menuitem", name=re.compile(r"sign out|sair", re.I)))
    if item is None:
        item = visible(page.get_by_text(re.compile(r"sign out|sair", re.I)))
    if item is None:
        raise RuntimeError("Opção Sign out do Grafana não encontrada")
    item.click()
    page.wait_for_load_state("domcontentloaded")


def archive_existing(output: Path) -> str | None:
    existing = [
        output / name
        for name in ("p005_1.png", "p023_1.png", "p023_2.png", "p024_1.png")
        if (output / name).is_file()
    ]
    if not existing:
        return None
    archive = ROOT / "dados" / "execucoes" / "Linux" / "prints_substituidos" / datetime.now().strftime("%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.move(str(path), str(archive / path.name))
    return str(archive)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--cdp-url")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.headless:
        raise ValueError("O modo headless não pode gerar evidências porque não exibe a barra de tarefas do Windows.")

    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    secrets = read_env(args.credentials)
    for key in ("zabbix_url", "grafana_url", "browser_channel", "timeout_seconds", "viewport"):
        if key not in config:
            raise ValueError(f"Configuração ausente: {key}")
    if args.validate_only:
        print("Configuração e credenciais preenchidas: OK")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("Playwright não instalado. Execute Configurar-AuditoriaLinux.ps1.") from error

    output = args.output.resolve()
    archive = archive_existing(output)
    result = {
        "executado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "zabbix_url": config["zabbix_url"],
        "grafana_url": config["grafana_url"],
        "arquivo_credenciais": str(args.credentials.resolve()),
        "arquivo_credenciais_exibido": False,
        "arquivo_anterior": archive,
        "capturas": [],
        "logout_zabbix": False,
        "logout_grafana": False,
    }
    errors = ROOT / "dados" / "execucoes" / "Linux"
    for stale_error in (errors / "Erro-AuditoriaLinux.png", errors / "Erro-AuditoriaLinux.json"):
        stale_error.unlink(missing_ok=True)
    timeout = int(config["timeout_seconds"]) * 1000
    monitor = largest_monitor()
    launch_args = []
    if monitor:
        launch_args.extend([
            f"--window-position={monitor['x']},{monitor['y']}",
            f"--window-size={monitor['width']},{monitor['height']}",
        ])
        result["monitor_navegador"] = monitor
    else:
        launch_args.extend(["--start-maximized", "--disable-translate", "--disable-features=msEdgeTranslate,Translate,TranslateUI"])
    with sync_playwright() as playwright:
        external_browser = bool(args.cdp_url)
        browser = (playwright.chromium.connect_over_cdp(args.cdp_url) if external_browser else
                   playwright.chromium.launch(channel=config["browser_channel"], headless=args.headless, args=launch_args))
        context_options = {"ignore_https_errors": config.get("verify_tls", True) is False}
        if args.headless:
            context_options["viewport"] = {
                "width": int(config["viewport"]["width"]),
                "height": int(config["viewport"]["height"]),
            }
        else:
            context_options["no_viewport"] = True
        context = browser.new_context(**context_options)
        context.set_default_timeout(timeout)
        page = context.new_page()
        maximize_window(context, page, args.headless)
        step = "inicialização"
        try:
            step = "login do Zabbix"
            publish_progress('linux_zabbix_login', 18)
            login_zabbix(page, config["zabbix_url"], secrets["ZABBIX_USUARIO"], secrets["ZABBIX_SENHA"])
            step = "menu Users do Zabbix"
            publish_progress('linux_zabbix_users', 27)
            open_zabbix_users(page)
            zabbix_table = first_visible(page, ["table", ".list-table"], "lista de usuários do Zabbix")
            result["usuarios_zabbix"] = extract_table(zabbix_table)
            prepare_zabbix_evidence(page)
            target = output / "p005_1.png"
            screenshot(page, target, full_page=False)
            result["capturas"].append(str(target))
            step = "logout do Zabbix"
            logout_zabbix(page)
            result["logout_zabbix"] = True

            step = "login do Grafana"
            publish_progress('linux_grafana_login', 40)
            login_grafana(page, config["grafana_url"], secrets["GRAFANA_USUARIO"], secrets["GRAFANA_SENHA"])
            step = "menu Users do Grafana"
            publish_progress('linux_grafana_users', 52)
            open_grafana_users(page)
            grafana_table = first_visible(page, ["table", "[role='table']"], "lista de usuários do Grafana")
            usuarios_grafana = extract_table(grafana_table)
            page.evaluate("window.scrollTo(0, 0)")
            target = output / "p023_1.png"
            screenshot(page, target, full_page=False)
            result["capturas"].append(str(target))
            step = "continuação da página 1 do Grafana"
            publish_progress('linux_grafana_pages', 62)
            scroll_grafana_bottom(page)
            target = output / "p023_2.png"
            screenshot(page, target, full_page=False)
            result["capturas"].append(str(target))
            step = "página 2 do Grafana"
            publish_progress('linux_grafana_pages', 69)
            open_grafana_second_page(page)
            usuarios_grafana.extend(extract_table(grafana_table))
            result["usuarios_grafana"] = usuarios_grafana
            target = output / "p024_1.png"
            screenshot(page, target, full_page=False)
            result["capturas"].append(str(target))
            step = "logout do Grafana"
            logout_grafana(page)
            result["logout_grafana"] = True
            publish_progress('collecting_done', 74)
        except Exception as error:
            publish_detail(step, status='warning', error=error)
            errors.mkdir(parents=True, exist_ok=True)
            diagnostic = {
                "etapa": step,
                "erro": "Falha na coleta da area.",
                "tipo": type(error).__name__,
            }
            (errors / "Erro-AuditoriaLinux.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                capture_monitor(page, errors / "Erro-AuditoriaLinux.png")
            except Exception as screenshot_error:
                diagnostic["erro_captura"] = type(screenshot_error).__name__
                (errors / "Erro-AuditoriaLinux.json").write_text(
                    json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            raise RuntimeError(f"Falha na etapa '{step}'.") from None
        finally:
            context.close()
            if not external_browser:
                browser.close()

    result_path = ROOT / "dados" / "execucoes" / "Linux" / "Resultado-AuditoriaLinux.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    data_path = ROOT / "dados" / "execucoes" / "Linux" / "Dados-AuditoriaLinux.json"
    data_path.write_text(
        json.dumps(
            {
                "coletado_em": result["executado_em"],
                "zabbix": result.get("usuarios_zabbix", []),
                "grafana": result.get("usuarios_grafana", []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "executado_em": result["executado_em"],
        "capturas": result["capturas"],
        "usuarios_zabbix": len(result.get("usuarios_zabbix", [])),
        "usuarios_grafana": len(result.get("usuarios_grafana", [])),
        "logout_zabbix": result["logout_zabbix"],
        "logout_grafana": result["logout_grafana"],
        "monitor_navegador": result.get("monitor_navegador"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FALHA: {error}", file=sys.stderr)
        raise SystemExit(1)
