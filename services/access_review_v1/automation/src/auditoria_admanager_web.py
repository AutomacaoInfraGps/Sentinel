"""Captura as evidências reais da auditoria do ADManager Plus."""

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
from access_review_progress import publish_detail, publish_progress
from windows_evidence import capture_monitor


CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])
REQUIRED_SECRETS = ("ADMANAGER_USUARIO", "ADMANAGER_SENHA")


def read_env(path: Path) -> dict[str, str]:
    from access_review_credentials import load_credentials
    return load_credentials(path, REQUIRED_SECRETS)


def largest_monitor() -> dict[str, int] | None:
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
        for frame in page.frames:
            for selector in selectors:
                item = visible(frame.locator(selector))
                if item is not None:
                    return item
        time.sleep(0.25)
    raise RuntimeError(f"Controle não encontrado: {label}")


def text_control(page, name: str, timeout_seconds: float = 20):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for frame in page.frames:
            for role in ("link", "button", "tab"):
                item = visible(frame.get_by_role(role, name=name, exact=True))
                if item is not None:
                    return item
            item = visible(frame.get_by_text(name, exact=True))
            if item is not None:
                return item
        time.sleep(0.25)
    raise RuntimeError(f"Item visível não encontrado: {name}")


def settle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    time.sleep(0.7)


def screenshot(page, path: Path) -> None:
    settle(page)
    page.evaluate(
        """
        () => {
          window.scrollTo(0, 0);
          document.querySelectorAll('*').forEach(element => {
            if (element.scrollLeft) element.scrollLeft = 0;
            if (element.scrollTop) element.scrollTop = 0;
          });
        }
        """
    )
    time.sleep(0.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    capture_monitor(page, path)


def extract_tables(page) -> list[dict[str, object]]:
    result = []
    for frame in page.frames:
        tables = frame.locator("table")
        for index in range(tables.count()):
            table = tables.nth(index)
            if not table.is_visible():
                continue
            payload = table.evaluate(
                """
                table => {
                  const clean = value => (value || '').replace(/\s+/g, ' ').trim();
                  const headers = [...table.querySelectorAll('thead th')].map(cell => clean(cell.innerText));
                  const rows = [...table.querySelectorAll('tbody tr')].map(row =>
                    [...row.querySelectorAll('td')].map(cell => clean(cell.innerText))
                  ).filter(row => row.some(Boolean));
                  return {headers, rows};
                }
                """
            )
            if payload["rows"]:
                result.append(payload)
    return result


def login(page, url: str, username: str, password: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    user = first_visible(
        page,
        ["input[name='username']", "input[name='j_username']", "input[name='userName']", "input[type='text']"],
        "usuário do ADManager",
    )
    secret = first_visible(page, ["input[name='password']", "input[name='j_password']", "input[type='password']"], "senha do ADManager")
    user.fill(username)
    secret.fill(password)
    submit = visible(page.get_by_role("button", name=re.compile(r"(login|sign in|entrar)", re.I)))
    if submit is None:
        submit = first_visible(page, ["button[type='submit']", "input[type='submit']"], "entrar no ADManager")
    submit.click()
    text_control(page, "Directory/Application Settings", timeout_seconds=25)


def open_directory_settings(page):
    """Abre a página real de configurações e devolve a aba que a contém."""
    before_url = page.url
    before_pages = set(page.context.pages)
    item = text_control(page, "Directory/Application Settings")
    item.scroll_into_view_if_needed()
    box = item.bounding_box()
    if not box:
        raise RuntimeError("Directory/Application Settings não possui área clicável")
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        candidates = [candidate for candidate in page.context.pages if candidate not in before_pages]
        candidates.extend([page])
        for candidate in candidates:
            try:
                current_url = candidate.evaluate("() => location.href")
            except Exception:
                continue
            if current_url not in ("", "about:blank", before_url) and "domainsettings" in current_url.casefold():
                candidate.wait_for_load_state("domcontentloaded")
                first_visible(candidate, ["table"], "tabela Directory/Application Settings")
                return candidate
        time.sleep(0.25)
    raise RuntimeError(f"o clique não saiu da página inicial ({before_url})")


def open_delegation(page) -> None:
    text_control(page, "Delegation").click()
    text_control(page, "Help Desk Technicians")
    first_visible(page, ["table"], "tabela Help Desk Technicians")


def logout(page) -> None:
    # O avatar do ADManager não expõe um nome acessível confiável. Ele fica
    # fixo no extremo superior direito, independentemente da página aberta.
    viewport = page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
    page.mouse.click(int(viewport["width"]) - 27, 11)
    time.sleep(0.4)
    text_control(page, "Sign Out", timeout_seconds=5).click()
    page.wait_for_load_state("domcontentloaded")


def archive_existing(output: Path) -> str | None:
    existing = [output / name for name in ("p003_1.png", "p005_1.png") if (output / name).is_file()]
    if not existing:
        return None
    archive = ROOT / "dados" / "execucoes" / "ADManager" / "prints_substituidos" / datetime.now().strftime("%Y%m%d-%H%M%S")
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
    args = parser.parse_args()
    if args.headless:
        raise ValueError("O modo headless não pode gerar evidências porque não exibe a barra de tarefas do Windows.")

    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    url = config.get("admanager_url", "").strip()
    if not url:
        raise ValueError("Preencha admanager_url em config/admanager.json")
    secrets = read_env(args.credentials)

    from playwright.sync_api import sync_playwright

    output = args.output.resolve()
    archive = archive_existing(output)
    result = {
        "executado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "admanager_url": url,
        "arquivo_credenciais_exibido": False,
        "arquivo_anterior": archive,
        "capturas": [],
        "directory_application_settings": [],
        "delegation": [],
        "logout": False,
    }
    diagnostics = ROOT / "dados" / "execucoes" / "ADManager"
    for stale in (diagnostics / "Erro-AuditoriaADManager.png", diagnostics / "Erro-AuditoriaADManager.json"):
        stale.unlink(missing_ok=True)

    monitor = largest_monitor()
    launch_args = ["--start-maximized", "--disable-translate", "--disable-features=msEdgeTranslate,Translate,TranslateUI"]
    if monitor:
        launch_args = [
            f"--window-position={monitor['x']},{monitor['y']}",
            f"--window-size={monitor['width']},{monitor['height']}",
        ]
        result["monitor_navegador"] = monitor

    timeout = int(config.get("timeout_seconds", 40)) * 1000
    viewport = config.get("viewport", {"width": 1920, "height": 1080})
    step = "inicialização"
    with sync_playwright() as playwright:
        external_browser = bool(args.cdp_url)
        browser = (playwright.chromium.connect_over_cdp(args.cdp_url) if external_browser else playwright.chromium.launch(channel=config.get("browser_channel", "msedge"), headless=args.headless, args=launch_args))
        context_options = {"ignore_https_errors": config.get("verify_tls", True) is False}
        if args.headless:
            context_options["viewport"] = {"width": int(viewport["width"]), "height": int(viewport["height"])}
        else:
            context_options["no_viewport"] = True
        context = browser.new_context(**context_options)
        context.set_default_timeout(timeout)
        page = context.new_page()
        maximize_window(context, page, args.headless)
        try:
            step = "login"
            publish_progress('admanager_login', 18)
            login(page, url, secrets["ADMANAGER_USUARIO"], secrets["ADMANAGER_SENHA"])
            step = "Directory/Application Settings"
            publish_progress('admanager_settings', 34)
            settings_page = open_directory_settings(page)
            target = output / "p003_1.png"
            screenshot(settings_page, target)
            result["capturas"].append(str(target))
            result["directory_application_settings"] = extract_tables(settings_page)
            if settings_page is not page:
                settings_page.close()
                page.bring_to_front()

            step = "Delegation"
            publish_progress('admanager_delegation', 54)
            open_delegation(page)
            target = output / "p005_1.png"
            screenshot(page, target)
            result["capturas"].append(str(target))
            result["delegation"] = extract_tables(page)

            step = "logout"
            publish_progress('admanager_logout', 70)
            logout(page)
            result["logout"] = True
            publish_progress('collecting_done', 74)
        except Exception as error:
            publish_detail(step, target='ADManager Plus', status='warning', error=error)
            diagnostics.mkdir(parents=True, exist_ok=True)
            diagnostic = {"etapa": step, "erro": "Falha na coleta da area.", "tipo": type(error).__name__}
            (diagnostics / "Erro-AuditoriaADManager.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                capture_monitor(page, diagnostics / "Erro-AuditoriaADManager.png")
            except Exception:
                pass
            raise RuntimeError(f"Falha na etapa '{step}'.") from None
        finally:
            context.close()
            if not external_browser:
                browser.close()

    result_path = diagnostics / "Resultado-AuditoriaADManager.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "executado_em": result["executado_em"],
        "capturas": len(result["capturas"]),
        "tabelas_directory": len(result["directory_application_settings"]),
        "tabelas_delegation": len(result["delegation"]),
        "logout": result["logout"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FALHA: {error}", file=sys.stderr)
        raise SystemExit(1)
