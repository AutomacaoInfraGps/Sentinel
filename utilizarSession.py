# utilizarSession.py — captura print do GPS Amigo com Playwright (Edge do sistema)
# Salva HTML com imagem embutida em C:\Users\Public\Automacao\output\print_temp.html

import os
import base64
import webbrowser
from pathlib import Path
import asyncio
from playwright.async_api import async_playwright

# --- Ambiente / Pastas públicas ---
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:\Users\Public\Automacao\pw_browsers")

from config import (
    GPS_HTML,
    GPS_CONFIG,
    ensure_directories,
    OUTPUT_DIR_PUBLIC,
    PUBLIC_BASE,
)

AUTH_DIR = PUBLIC_BASE / "playwright" / "auth"
AUTH_DIR.mkdir(parents=True, exist_ok=True)
AUTH_STATE = AUTH_DIR / "auth_state.json"   # se você gravar login, deixe aqui

def _make_html_from_png(png_path: Path) -> str:
    b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><title>GPS Amigo</title>
<style>body{{font-family:Segoe UI,Arial;margin:16px;background:#eee;margin:0;text-align:center}}</style></head>
<body>
  <img alt="GPS Amigo" style="max-width:100%;height:auto;" src="data:image/png;base64,{b64}">
</body></html>"""

def _is_interactive() -> bool:
    # Evita abrir navegador quando rodar como serviço/Agendador
    return os.environ.get("SESSIONNAME", "").upper() == "CONSOLE" and os.environ.get("USERNAME", "").lower() != "system"

async def main(open_after: bool = False) -> None:
    ensure_directories()
    OUTPUT_DIR_PUBLIC.mkdir(parents=True, exist_ok=True)
    GPS_HTML.parent.mkdir(parents=True, exist_ok=True)

    url = GPS_CONFIG.get("url", "https://gpsamigo.com.br/login.php")
    screenshot_path = OUTPUT_DIR_PUBLIC / "screenshot.png"
    if screenshot_path.exists():
        try: screenshot_path.unlink()
        except Exception: pass

    async with async_playwright() as p:
        # Usa Edge do sistema (ou troque para channel="chrome" se preferir)
        browser = await p.chromium.launch(
            channel="msedge",
            headless=True,
            args=[
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1366,768",
            ],
        )

        # Usa estado salvo se existir (login prévio, opcional)
        storage_state = str(AUTH_STATE) if AUTH_STATE.exists() else None
        context = await browser.new_context(storage_state=storage_state)

        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60_000)

        # Faça login aqui se precisar e depois salve o estado:
        # await context.storage_state(path=str(AUTH_STATE))

        await page.screenshot(path=str(screenshot_path), full_page=True)
        GPS_HTML.write_text(_make_html_from_png(screenshot_path), encoding="utf-8")

        await browser.close()

    if open_after and _is_interactive():
        webbrowser.open(GPS_HTML.resolve().as_uri())

if __name__ == "__main__":
    asyncio.run(main(open_after=True))
