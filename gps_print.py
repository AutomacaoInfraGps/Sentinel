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
    GPS_CONFIG,
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


if __name__ == "__main__":
    ensure_gps_placeholder()
    gerar_print_gps_amigo()
    print("OK - print gerado em:")
    print("  ", GPS_IMG)
    print("  ", GPS_HTML)
