def gerar_print_rede_universo(timeout: int = 30) -> None:
    # Gera um "print" do portal Rede Universo no Public:
    #   - C:/Users/Public/Automacao/output/public/rede_universo.png
    #   - C:/Users/Public/Automacao/output/public/rede_universo.html (HTML com a imagem em base64)
    #
    # Sem Selenium: usa Edge/Chrome headless por CLI (subprocess). Com Selenium instalado, usa Selenium.
    # Logs do navegador são silenciados.
    # Se não gerar imagem, cria placeholder HTML igual GPS
    def criar_placeholder():
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        UNIVERSO_HTML.write_text(
            f"""<!doctype html>\n<html lang='pt-br'>\n<head>\n  <meta charset='utf-8'>\n  <title>Rede Universo</title>\n  <style>body{{font-family:Segoe UI,Arial;margin:16px}}.note{{color:#666}}</style>\n</head>\n<body>\n  <div class='note'>Prévia indisponível no momento. ({ts})</div>\n  <p><a href='{url}' target='_blank'>Abrir Rede Universo</a></p>\n</body>\n</html>""",
            encoding="utf-8",
        )
    """Gera o print do portal Rede Universo."""
    from pathlib import Path
    import time
    import os
    ensure_directories()
    OUTPUT_DIR_PUBLIC.mkdir(parents=True, exist_ok=True)
    # Garante criação do diretório output/public
    from datetime import datetime
    now = datetime.now()
    ano = str(now.year)
    mes = f"{now.month:02d}"
    dia = f"{now.day:02d}"
    public_base = Path(r"C:/Users/Public/Automacao/output/public")
    public_dir = public_base / ano / mes / dia
    public_dir.mkdir(parents=True, exist_ok=True)
    print(f"[DEBUG] public_dir: {public_dir}")
    # Atualiza caminhos dos prints
    UNIVERSO_IMG = public_dir / "rede_universo.png"
    UNIVERSO_HTML = public_dir / "rede_universo.html"
    # Caminho absoluto para debug
    UNIVERSO_IMG = Path(r"C:/Users/Public/Automacao/output/public/rede_universo.png")
    UNIVERSO_HTML = Path(r"C:/Users/Public/Automacao/output/public/rede_universo.html")
    print(f"[DEBUG] UNIVERSO_IMG: {UNIVERSO_IMG}")
    print(f"[DEBUG] UNIVERSO_HTML: {UNIVERSO_HTML}")
    print(f"[DEBUG] OUTPUT_DIR_PUBLIC exists: {OUTPUT_DIR_PUBLIC.exists()}")
    print(f"[DEBUG] Current working dir: {os.getcwd()}")
    url = SATURNO_PORTAL.get("url", "https://portal.exemplo.local/guest")
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
        opts.add_argument(f"--user-data-dir={PUBLIC_BASE / 'browser_profile'}")
        drv = webdriver.Edge(options=opts)
        try:
            drv.get(url)
            WebDriverWait(drv, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(2)
            # Captura WI-FI
            try:
                wifi_clicked = False
                for xpath in [
                    "//button[contains(.,'WI-FI')]",
                    "//a[contains(.,'WI-FI')]",
                    "//div[contains(.,'WI-FI')]",
                    "//span[contains(.,'WI-FI')]",
                    "//*[contains(text(),'WI-FI')]"
                ]:
                    btns = drv.find_elements(By.XPATH, xpath)
                    for btn in btns:
                        if btn.is_displayed():
                            btn.click()
                            print(f"[DEBUG] Clique WI-FI realizado via {xpath}")
                            wifi_clicked = True
                            time.sleep(1)
                            break
                    if wifi_clicked:
                        break
            except Exception as e:
                print(f"[DEBUG] Falha ao clicar WI-FI: {e}")
            wifi_img = public_dir / "rede_universo_wifi.png"
            drv.save_screenshot(str(wifi_img))
            wifi_html = public_dir / "rede_universo_wifi.html"
            wifi_html.write_text(_html_from_image_base64(wifi_img), encoding="utf-8")
            print(f"[DEBUG] Screenshot WI-FI salvo: {wifi_img.exists()} tamanho: {wifi_img.stat().st_size if wifi_img.exists() else 0}")
            print(f"[DEBUG] HTML WI-FI gerado: {wifi_html.exists()} tamanho: {wifi_html.stat().st_size if wifi_html.exists() else 0}")

            # Captura DIRETORIA
            try:
                # Clica diretamente no botão da aba DIRETORIA
                btn = drv.find_element(By.CSS_SELECTOR, '.switcher-signup')
                drv.execute_script('arguments[0].click();', btn)
                # Força visualmente a ativação da aba DIRETORIA
                js_force_active = '''
                    var wrappers = document.querySelectorAll('.form-wrapper');
                    wrappers.forEach(function(w, i) {
                        w.classList.remove('is-active');
                    });
                    var btns = document.querySelectorAll('.switcher');
                    btns.forEach(function(b, i) {
                        b.classList.remove('active');
                    });
                    // Ativa a segunda aba (DIRETORIA)
                    if (wrappers.length > 1) {
                        wrappers[1].classList.add('is-active');
                        btns[1].classList.add('active');
                    }
                '''
                drv.execute_script(js_force_active)
                print("[DEBUG] Forçou ativação visual da aba DIRETORIA")
                time.sleep(2)
            except Exception as e:
                print(f"[DEBUG] Falha ao ativar DIRETORIA: {e}")
            # Loga HTML da página para depuração
            page_html = drv.page_source
            with open(str(public_dir / "debug_diretoria.html"), "w", encoding="utf-8") as f:
                f.write(page_html)
            print(f"[DEBUG] HTML da aba DIRETORIA salvo em debug_diretoria.html (tamanho: {len(page_html)})")
            diretoria_img = public_dir / "rede_universo_diretoria.png"
            drv.save_screenshot(str(diretoria_img))
            diretoria_html = public_dir / "rede_universo_diretoria.html"
            diretoria_html.write_text(_html_from_image_base64(diretoria_img), encoding="utf-8")
            print(f"[DEBUG] Screenshot DIRETORIA salvo: {diretoria_img.exists()} tamanho: {diretoria_img.stat().st_size if diretoria_img.exists() else 0}")
            print(f"[DEBUG] HTML DIRETORIA gerado: {diretoria_html.exists()} tamanho: {diretoria_html.stat().st_size if diretoria_html.exists() else 0}")

            # Captura geral (default)
            drv.save_screenshot(str(UNIVERSO_IMG))
            UNIVERSO_HTML.write_text(_html_from_image_base64(UNIVERSO_IMG), encoding="utf-8")
            print(f"[DEBUG] Screenshot geral salvo: {UNIVERSO_IMG.exists()} tamanho: {UNIVERSO_IMG.stat().st_size if UNIVERSO_IMG.exists() else 0}")
            print(f"[DEBUG] HTML geral gerado: {UNIVERSO_HTML.exists()} tamanho: {UNIVERSO_HTML.stat().st_size if UNIVERSO_HTML.exists() else 0}")
            return
        finally:
            drv.quit()
    except Exception as e:
        print(f"[DEBUG] Selenium falhou: {e}")
        browser = _find_browser_exe()
        if not browser:
            raise RuntimeError("Não encontrei msedge.exe nem chrome.exe. Instale Edge ou Chrome no servidor.")
        screenshot_name = "screenshot_universo.png"
        screenshot_path = Path(r"C:/Users/Public/Automacao/output/public/screenshot_universo.png")
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
            f"--user-data-dir={PUBLIC_BASE / 'browser_profile'}",
            "--screenshot",
            url,
        ]
        try:
            _silent_run(args_base + ["--headless=new"], cwd=OUTPUT_DIR_PUBLIC, timeout=90)
        except Exception as e:
            print(f"[DEBUG] Headless CLI falhou: {e}")
            _silent_run(args_base + ["--headless"], cwd=OUTPUT_DIR_PUBLIC, timeout=90)
        print(f"[DEBUG] Screenshot CLI salvo: {screenshot_path.exists()} tamanho: {screenshot_path.stat().st_size if screenshot_path.exists() else 0}")
        try:
            if UNIVERSO_IMG.exists():
                UNIVERSO_IMG.unlink()
        except Exception:
            pass
        screenshot_path.rename(UNIVERSO_IMG)
        UNIVERSO_HTML.write_text(_html_from_image_base64(UNIVERSO_IMG), encoding="utf-8")
        print(f"[DEBUG] HTML gerado: {UNIVERSO_HTML.exists()} tamanho: {UNIVERSO_HTML.stat().st_size if UNIVERSO_HTML.exists() else 0}")
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
                "//button[contains(translate(normalize-space(.),'ENTRARLOGINACCESSSIGN IN','entrarloginaccesssign in'),'login')]",
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
        APPGATE_HTML.write_text(_html_from_named_image_base64(APPGATE_IMG, "Firewall Rio de Janeiro"), encoding="utf-8")
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


def _click_saturno_tab(drv, tab_name: str) -> bool:
    """Alterna entre as abas WI-FI e DIRETORIA do portal SATURNO."""
    tab_name = (tab_name or "").strip().lower()

    script = """
    const tabName = arguments[0];
    const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();

    const clickIfFound = (selectors) => {
        for (const selector of selectors) {
            const elements = Array.from(document.querySelectorAll(selector));
            for (const el of elements) {
                const text = normalize(el.innerText || el.textContent);
                if (text === tabName) {
                    el.click();
                    return true;
                }
            }
        }
        return false;
    };

    if (tabName === 'wi-fi' || tabName === 'wifi') {
        const wifiButton = document.querySelector('.switcher-login');
        if (wifiButton) {
            wifiButton.click();
            return true;
        }
    }

    if (tabName === 'diretoria') {
        const diretoriaButton = document.querySelector('.switcher-signup');
        if (diretoriaButton) {
            diretoriaButton.click();
            return true;
        }
    }

    return clickIfFound(['button', 'a', 'div', 'span', 'li', 'label']);
    """

    return bool(drv.execute_script(script, tab_name))


def _wait_for_saturno_tab(drv, tab_name: str, timeout: int):
    from selenium.webdriver.support.ui import WebDriverWait

    tab_name = (tab_name or "").strip().lower()

    def _predicate(_):
        body = (drv.page_source or "").lower()
        if tab_name in {"wi-fi", "wifi"}:
            return "cpf" in body and "data nascimento" in body
        if tab_name == "diretoria":
            return "login" in body and "senha" in body
        return False

    WebDriverWait(drv, timeout).until(_predicate)


def gerar_print_saturno_portal(timeout: int = 30) -> list[Path]:
    """Gera 3 prints do portal SATURNO: WI-FI, DIRETORIA e aprovação do WI-FI."""
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

        if not _click_saturno_tab(drv, "wi-fi"):
            raise RuntimeError("Nao foi possivel abrir a aba WI-FI do portal SATURNO")
        _wait_for_saturno_tab(drv, "wi-fi", timeout)
        time.sleep(1)

        wifi_path = out_dir / "saturno_wifi.png"
        _capture_step(drv, wifi_path)
        paths.append(wifi_path)

        if not _click_saturno_tab(drv, "diretoria"):
            raise RuntimeError("Nao foi possivel abrir a aba DIRETORIA do portal SATURNO")
        _wait_for_saturno_tab(drv, "diretoria", timeout)
        time.sleep(1)

        diretoria_path = out_dir / "saturno_diretoria.png"
        _capture_step(drv, diretoria_path)
        paths.append(diretoria_path)

        if not _click_saturno_tab(drv, "wi-fi"):
            raise RuntimeError("Nao foi possivel retornar para a aba WI-FI do portal SATURNO")
        _wait_for_saturno_tab(drv, "wi-fi", timeout)
        time.sleep(1)

        cpf_input = _find_input(drv, [
            "//input[contains(@placeholder,'CPF') or contains(@aria-label,'CPF') or contains(translate(@name,'CPF','cpf'),'cpf') or contains(translate(@id,'CPF','cpf'),'cpf')]",
        ])
        data_input = _find_input(drv, [
            "//input[contains(@placeholder,'Nascimento') or contains(@placeholder,'Data') or contains(translate(@name,'DATA','data'),'data') or contains(translate(@id,'DATA','data'),'data')]",
        ])

        if not cpf_input or not data_input:
            raise RuntimeError("Campos de CPF/Data nao encontrados na aba WI-FI do Saturno")

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

        try:
            botao = drv.find_element(By.XPATH, "//button[contains(.,'Conectar') or contains(.,'CONECTAR')]")
            botao.click()
        except Exception:
            if not _click_by_text(drv, "conectar"):
                raise RuntimeError("Nao foi possivel clicar no botao Conectar da aba WI-FI")

        _wait_for_text(drv, ["aguardando", "aprovação", "aprovacao", "solicitação foi enviada", "solicitacao foi enviada"], timeout)
        time.sleep(1)

        aprovacao_path = out_dir / "saturno_wifi_aprovacao.png"
        _capture_step(drv, aprovacao_path)
        paths.append(aprovacao_path)

        return paths
    finally:
        drv.quit()


if __name__ == "__main__":
    ensure_gps_placeholder()
    gerar_print_gps_amigo()
    print("OK - print gerado em:")
    print("  ", GPS_IMG)
    print("  ", GPS_HTML)

    # Gera print do Rede Universo
    try:
        gerar_print_rede_universo()
        print("OK - print Rede Universo gerado em:")
        print("  C:/Users/Public/Automacao/output/public/rede_universo.png")
        print("  C:/Users/Public/Automacao/output/public/rede_universo.html")
    except Exception as e:
        print("Falha ao gerar print Rede Universo:", e)
