# gps_print.py
# Gera um "print" do GPS Amigo no Public:
#   - C:\Users\Public\Automacao\output\gps_amigo.png
#   - C:\Users\Public\Automacao\output\print_temp.html (HTML com a imagem em base64)
#
# Sem Selenium: usa Edge/Chrome headless por CLI (subprocess). Com Selenium instalado, usa Selenium.
# Logs do navegador são silenciados.

from pathlib import Path
import base64
import os
import subprocess
import time
from datetime import datetime


from config import (
    OUTPUT_DIR_PUBLIC,
    GPS_HTML,
    APPGATE_HTML,
    APPGATE_IMG,
    GPS_CONFIG,
    APPGATE_CONFIG,
    SATURNO_PORTAL,
    SATURNO_OUTPUT_BASE,
    ensure_directories,
    PUBLIC_BASE,
)

# GPS_IMG pode não existir no config; definimos padrão aqui.
try:
    from config import GPS_IMG  # opcional no seu config.py
except Exception:
    GPS_IMG = OUTPUT_DIR_PUBLIC / "gps_amigo.png"


def ensure_gps_placeholder() -> None:
    """Cria um placeholder se o print não existir, sem H2 interno para evitar barra duplicada."""
    ensure_directories()
    OUTPUT_DIR_PUBLIC.mkdir(parents=True, exist_ok=True)
    GPS_HTML.parent.mkdir(parents=True, exist_ok=True)

    if not GPS_HTML.exists():
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        GPS_HTML.write_text(
            f"""<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>GPS Amigo</title>
  <style>
    body{{font-family:Segoe UI,Arial;margin:16px}}
    .note{{color:#666}}
  </style>
</head>
<body>
  <div class="note">Prévia indisponível no momento. ({ts})</div>
  <p><a href="{GPS_CONFIG.get('url','https://gpsamigo.com.br/login.php')}" target="_blank">Abrir GPS Amigo</a></p>
</body>
</html>""",
            encoding="utf-8",
        )



def _html_from_image_base64(png_path: Path) -> str:
    b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><title>GPS Amigo</title>
<style>body{{font-family:Segoe UI,Arial;margin:16px}}</style></head>
<body>
  <img alt="GPS Amigo" style="max-width:100%; height:auto;" src="data:image/png;base64,{b64}">
</body></html>"""


def _html_from_named_image_base64(png_path: Path, title: str) -> str:
        b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
        return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:Segoe UI,Arial;margin:16px}}</style></head>
<body>
    <img alt="{title}" style="max-width:100%; height:auto;" src="data:image/png;base64,{b64}">
</body></html>"""


def _find_browser_exe() -> str | None:
    """Procura Edge (preferência) ou Chrome instalados."""
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / r"Google\Chrome\Application\chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / r"Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _silent_run(args: list[str], cwd: Path, timeout: int = 90) -> None:
    """Executa subprocesso silenciando stdout/stderr e levanta exceção se falhar."""
    subprocess.run(
        args,
        check=True,
        timeout=timeout,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _gerar_print_via_headless_cli() -> None:
    """Usa Edge/Chrome headless (sem Selenium) para tirar screenshot.
    Estratégia:
      - Executa com cwd = OUTPUT_DIR_PUBLIC
      - Usa '--screenshot' sem caminho (gera 'screenshot.png' no cwd)
      - Renomeia para gps_amigo.png e gera o HTML base64
    """
    ensure_directories()
    OUTPUT_DIR_PUBLIC.mkdir(parents=True, exist_ok=True)
    GPS_HTML.parent.mkdir(parents=True, exist_ok=True)

    browser = _find_browser_exe()
    if not browser:
        raise RuntimeError("Não encontrei msedge.exe nem chrome.exe. Instale Edge ou Chrome no servidor.")

    url = GPS_CONFIG.get("url", "https://gpsamigo.com.br/login.php")

    screenshot_name = "screenshot.png"
    screenshot_path = OUTPUT_DIR_PUBLIC / screenshot_name
    # remove resíduo antigo
    try:
        if screenshot_path.exists():
            screenshot_path.unlink()
    except Exception:
        pass

    args_base = [
        browser,
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-service-autorun",
        "--disable-logging",
        "--log-level=3",               # reduz verbosidade do browser
        "--window-size=1366,768",
        f"--user-data-dir={PUBLIC_BASE / 'browser_profile'}",
        "--screenshot",                # sem caminho: gera 'screenshot.png' no cwd
        url,
    ]

    # Tenta headless=new; se falhar, tenta o headless antigo
    try:
        _silent_run(args_base + ["--headless=new"], cwd=OUTPUT_DIR_PUBLIC, timeout=90)
    except Exception:
        _silent_run(args_base + ["--headless"], cwd=OUTPUT_DIR_PUBLIC, timeout=90)

    if not screenshot_path.exists() or screenshot_path.stat().st_size == 0:
        raise RuntimeError("Screenshot não foi gerado pelo navegador headless.")

    # Renomeia para o caminho padrão e gera o HTML base64
    try:
        if GPS_IMG.exists():
            GPS_IMG.unlink()
    except Exception:
        pass
    screenshot_path.rename(GPS_IMG)

    GPS_HTML.write_text(_html_from_image_base64(GPS_IMG), encoding="utf-8")


def gerar_print_gps_amigo(timeout: int = 30) -> None:
    """Gera o print do GPS Amigo.
    Fluxo:
      1) Tenta via Selenium (se instalado);
      2) Se não houver Selenium ou falhar, usa Edge/Chrome headless via CLI.
    """
    ensure_directories()
    OUTPUT_DIR_PUBLIC.mkdir(parents=True, exist_ok=True)
    GPS_HTML.parent.mkdir(parents=True, exist_ok=True)

    # Tenta Selenium (opcional)
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        url = GPS_CONFIG.get("url", "https://gpsamigo.com.br/login.php")

        opts = webdriver.EdgeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--window-size=1366,768")
        opts.add_argument(f"--user-data-dir={PUBLIC_BASE / 'browser_profile'}")

        drv = webdriver.Edge(options=opts)  # Selenium Manager resolve driver automaticamente
        try:
            drv.get(url)
            WebDriverWait(drv, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(2)
            drv.save_screenshot(str(GPS_IMG))
            GPS_HTML.write_text(_html_from_image_base64(GPS_IMG), encoding="utf-8")
            return
        finally:
            drv.quit()
    except Exception:
        # Fallback automático sem Selenium
        _gerar_print_via_headless_cli()


def gerar_print_rede_universo(timeout: int = 30) -> None:
    """Gera o print do portal Rede Universo e os recortes de WI-FI e DIRETORIA."""
    ensure_directories()
    OUTPUT_DIR_PUBLIC.mkdir(parents=True, exist_ok=True)

    public_dir = OUTPUT_DIR_PUBLIC / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    universo_img = public_dir / "rede_universo.png"
    universo_html = public_dir / "rede_universo.html"
    wifi_img = public_dir / "rede_universo_wifi.png"
    wifi_html = public_dir / "rede_universo_wifi.html"
    diretoria_img = public_dir / "rede_universo_diretoria.png"
    diretoria_html = public_dir / "rede_universo_diretoria.html"
    debug_html = public_dir / "debug_diretoria.html"

    url = "https://www.gpsamigo.com.br/guest/s/default/?ap=28:70:4e:54:11:c1&id=d4:1b:81:8a:4e:13&t=1772215964&url=http://www.msftconnecttest.com%2Fredirect&ssid=SATURNO"

    def criar_placeholder() -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        universo_html.write_text(
            f"""<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>Rede Universo</title>
  <style>body{{font-family:Segoe UI,Arial;margin:16px}}.note{{color:#666}}</style>
</head>
<body>
  <div class="note">Previa indisponivel no momento. ({ts})</div>
  <p><a href="{url}" target="_blank">Abrir Rede Universo</a></p>
</body>
</html>""",
            encoding="utf-8",
        )

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        opts = webdriver.EdgeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--window-size=1366,768")
        opts.add_argument(f"--user-data-dir={PUBLIC_BASE / 'browser_profile_universo'}")

        drv = webdriver.Edge(options=opts)
        try:
            drv.get(url)
            WebDriverWait(drv, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(2)

            _click_saturno_tab(drv, "wi-fi")
            time.sleep(1)
            drv.save_screenshot(str(wifi_img))
            wifi_html.write_text(_html_from_image_base64(wifi_img), encoding="utf-8")

            if _click_saturno_tab(drv, "diretoria"):
                time.sleep(2)
            debug_html.write_text(drv.page_source, encoding="utf-8")
            drv.save_screenshot(str(diretoria_img))
            diretoria_html.write_text(_html_from_image_base64(diretoria_img), encoding="utf-8")

            drv.save_screenshot(str(universo_img))
            universo_html.write_text(_html_from_image_base64(universo_img), encoding="utf-8")
            return
        finally:
            drv.quit()
    except Exception:
        browser = _find_browser_exe()
        if not browser:
            criar_placeholder()
            return

        screenshot_path = public_dir / "screenshot_universo.png"
        try:
            if screenshot_path.exists():
                screenshot_path.unlink()
        except Exception:
            pass

        args_base = [
            browser,
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-service-autorun",
            "--disable-logging",
            "--log-level=3",
            "--window-size=1366,768",
            f"--user-data-dir={PUBLIC_BASE / 'browser_profile_universo'}",
            "--screenshot",
            url,
        ]

        try:
            _silent_run(args_base + ["--headless=new"], cwd=public_dir, timeout=90)
        except Exception:
            _silent_run(args_base + ["--headless"], cwd=public_dir, timeout=90)

        if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
            try:
                if universo_img.exists():
                    universo_img.unlink()
            except Exception:
                pass
            screenshot_path.rename(universo_img)
            universo_html.write_text(_html_from_image_base64(universo_img), encoding="utf-8")
            return

        criar_placeholder()


def gerar_print_appgate(timeout: int = 45) -> Path:
    """Gera um print autenticado do dashboard do AppGate."""
    ensure_directories()
    OUTPUT_DIR_PUBLIC.mkdir(parents=True, exist_ok=True)
    APPGATE_HTML.parent.mkdir(parents=True, exist_ok=True)

    url = (APPGATE_CONFIG.get("url") or "").strip()
    username = (APPGATE_CONFIG.get("username") or "admin").strip()
    password = APPGATE_CONFIG.get("password") or ""

    if not url:
        raise RuntimeError("appgate.url nao configurado no environment.json")
    if not password:
        raise RuntimeError("appgate.password nao configurado no environment.json")

    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    opts = webdriver.EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--allow-insecure-localhost")
    opts.add_argument("--window-size=1600,1200")
    opts.add_argument(f"--user-data-dir={PUBLIC_BASE / 'browser_profile_appgate'}")
    opts.set_capability("acceptInsecureCerts", True)

    drv = webdriver.Edge(options=opts)

    try:
        def _dashboard_loaded() -> bool:
            current_url = (drv.current_url or "").lower()
            body_text = drv.find_element(By.TAG_NAME, "body").text.lower()
            return "/ng/system/dashboard/" in current_url and "dashboard" in body_text

        drv.get(url)
        WebDriverWait(drv, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)

        password_input = _find_input(drv, [
            "//input[@type='password']",
            "//input[contains(translate(@name,'PASSWORDSENHA','passwordsenha'),'password') or contains(translate(@id,'PASSWORDSENHA','passwordsenha'),'password') or contains(translate(@placeholder,'PASSWORDSENHA','passwordsenha'),'password') or contains(translate(@placeholder,'PASSWORDSENHA','passwordsenha'),'senha')]",
        ])

        if password_input:
            username_input = _find_input(drv, [
                "//input[@type='text' or @type='email'][1]",
                "//input[contains(translate(@name,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'user') or contains(translate(@name,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'usuario') or contains(translate(@name,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'login')]",
                "//input[contains(translate(@id,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'user') or contains(translate(@id,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'usuario') or contains(translate(@id,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'login')]",
                "//input[contains(translate(@placeholder,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'user') or contains(translate(@placeholder,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'usuario') or contains(translate(@placeholder,'USERNAMEUSUARIOLOGIN','usernameusuariologin'),'login')]",
            ])

            if username_input:
                username_input.clear()
                username_input.send_keys(username)

            password_input.clear()
            password_input.send_keys(password)

            submitted = False
            for xpath in [
                "//button[@type='submit']",
                "//input[@type='submit']",
                "//button[@type='button' and contains(normalize-space(.), 'Login')]",
                "//button[contains(@onclick, 'try_login')]",
                "//button[contains(translate(normalize-space(.),'ENTRARLOGINACCESSSIGN IN','entrarloginaccesssign in'),'entrar')]",
                "//button[contains(translate(normalize-space(.),'ENTRARLOGINACCESSSIGN IN','entrarloginaccesssign in'),'login')]",
                "//button[contains(translate(normalize-space(.),'ENTRARLOGINACCESSSIGN IN','entrarloginaccesssign in'),'access')]",
                "//button[contains(translate(normalize-space(.),'ENTRARLOGINACCESSSIGN IN','entrarloginaccesssign in'),'sign in')]",
            ]:
                try:
                    button = drv.find_element(By.XPATH, xpath)
                    drv.execute_script("arguments[0].click();", button)
                    submitted = True
                    break
                except Exception:
                    continue

            if not submitted:
                password_input.send_keys(Keys.ENTER)

        for _ in range(10):
            drv.get(url)
            WebDriverWait(drv, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(5)
            if _dashboard_loaded():
                break
        else:
            raise RuntimeError("Nao foi possivel abrir o dashboard do AppGate apos o login")

        time.sleep(3)

        drv.save_screenshot(str(APPGATE_IMG))
        APPGATE_HTML.write_text(_html_from_named_image_base64(APPGATE_IMG, "AppGate"), encoding="utf-8")
        return APPGATE_IMG
    finally:
        drv.quit()


def _month_abbr_pt(month: int) -> str:
    months = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return months[month - 1]


def _saturno_output_dir(base_dir: Path, now: datetime) -> Path:
    month_dir = _month_abbr_pt(now.month)
    return base_dir / f"{now.year}" / month_dir / f"{now.day:02d}"


def _click_by_text(drv, text: str) -> bool:
    script = """
    const text = arguments[0].toLowerCase();
    const elements = Array.from(document.querySelectorAll('button, a, div, span, li, label'));
    for (const el of elements) {
        const t = (el.innerText || '').trim().toLowerCase();
        if (t === text) { el.click(); return true; }
    }
    return false;
    """
    return bool(drv.execute_script(script, text))


def _find_input(drv, xpaths: list[str]):
    from selenium.webdriver.common.by import By
    for xpath in xpaths:
        try:
            return drv.find_element(By.XPATH, xpath)
        except Exception:
            continue
    return None


def _wait_for_text(drv, texts: list[str], timeout: int):
    from selenium.webdriver.support.ui import WebDriverWait

    lowered = [t.lower() for t in texts]

    def _predicate(_):
        body = (drv.page_source or "").lower()
        return any(t in body for t in lowered)

    WebDriverWait(drv, timeout).until(_predicate)


def _capture_step(drv, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    drv.save_screenshot(str(path))


def gerar_print_saturno_portal(timeout: int = 30) -> list[Path]:
    """Gera prints do portal SATURNO em modo Wi-Fi e Diretoria (passo a passo)."""
    ensure_directories()

    url = SATURNO_PORTAL.get("url") or ""
    cpf = SATURNO_PORTAL.get("cpf") or ""
    data_nascimento = SATURNO_PORTAL.get("data_nascimento") or ""

    if not url or not cpf or not data_nascimento:
        raise RuntimeError("saturno_portal.url/cpf/data_nascimento nao configurados no environment.json")

    now = datetime.now()
    out_dir = _saturno_output_dir(SATURNO_OUTPUT_BASE, now)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Selenium e Edge headless (necessario para preencher o formulario)
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    opts = webdriver.EdgeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument(f"--user-data-dir={PUBLIC_BASE / 'browser_profile_saturno'}")

    drv = webdriver.Edge(options=opts)
    paths = []

    try:
        drv.get(url)
        WebDriverWait(drv, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)

        def preencher_e_capturar(prefix: str, aba_texto: str):
            if aba_texto:
                _click_by_text(drv, aba_texto)
                time.sleep(1)

            step1 = out_dir / f"{prefix}_1_abertura.png"
            _capture_step(drv, step1)
            paths.append(step1)

            cpf_input = _find_input(drv, [
                "//input[contains(@placeholder,'CPF') or contains(@aria-label,'CPF') or contains(translate(@name,'CPF','cpf'),'cpf') or contains(translate(@id,'CPF','cpf'),'cpf')]",
            ])
            data_input = _find_input(drv, [
                "//input[contains(@placeholder,'Nascimento') or contains(@placeholder,'Data') or contains(translate(@name,'DATA','data'),'data') or contains(translate(@id,'DATA','data'),'data')]",
            ])

            if not cpf_input or not data_input:
                raise RuntimeError("Campos de CPF/Data nao encontrados na pagina do Saturno")

            cpf_input.clear()
            cpf_input.send_keys(cpf)
            data_input.clear()
            data_input.send_keys(data_nascimento)

            try:
                termos = _find_input(drv, [
                    "//label[contains(translate(.,'TERMO','termo'),'termo')]//input[@type='checkbox']",
                    "//input[@type='checkbox']",
                ])
                if termos and not termos.is_selected():
                    termos.click()
            except Exception:
                pass

            step2 = out_dir / f"{prefix}_2_preenchido.png"
            _capture_step(drv, step2)
            paths.append(step2)

            try:
                botao = drv.find_element(By.XPATH, "//button[contains(.,'Conectar') or contains(.,'CONECTAR')]")
                botao.click()
            except Exception:
                _click_by_text(drv, "conectar")

            _wait_for_text(drv, ["pendente", "aprovacao", "autorizado", "autorizacao"], timeout)
            time.sleep(1)

            step3 = out_dir / f"{prefix}_3_resultado.png"
            _capture_step(drv, step3)
            paths.append(step3)

        preencher_e_capturar("wifi", "WI-FI")
        preencher_e_capturar("diretoria", "DIRETORIA")

        return paths
    finally:
        drv.quit()


if __name__ == "__main__":
    ensure_gps_placeholder()
    gerar_print_gps_amigo()
    print("OK - print gerado em:")
    print("  ", GPS_IMG)
    print("  ", GPS_HTML)
