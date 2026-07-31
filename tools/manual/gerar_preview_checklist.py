from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output"
PREVIEW_FILE = OUTPUT_DIR / "dashboard_preview.html"


def _public_base() -> Path:
    configured = os.environ.get("AUTOMACAO_PUBLIC_BASE")
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Automacao"


def _source_candidates() -> list[Path]:
    candidates = [
        OUTPUT_DIR / "dashboard_final.html",
        OUTPUT_DIR / "dashboard_preview_switches.html",
    ]

    public_root = _public_base()
    if public_root.exists():
        candidates.extend(public_root.rglob("dashboard_final.html"))
        candidates.extend(public_root.rglob("relatorio_preventiva_*.html"))

    return [
        path for path in candidates
        if path.exists() and path.is_file() and path.resolve() != PREVIEW_FILE.resolve()
    ]


def _latest_dashboard() -> Path | None:
    candidates = _source_candidates()
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _inject_preview_banner(html: str, source: Path) -> str:
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    source_label = str(source)
    banner = f"""
<div id="sentinel-preview-cache-banner">
    PREVIEW CACHE - gerado em {generated_at} a partir de {source_label}
</div>
<style>
    #sentinel-preview-cache-banner {{
        position: fixed;
        right: 18px;
        bottom: 18px;
        z-index: 999999;
        max-width: min(520px, calc(100vw - 36px));
        background: #084a61;
        color: #fff;
        border: 1px solid rgba(255,255,255,.35);
        border-radius: 7px;
        box-shadow: 0 12px 28px rgba(0,0,0,.24);
        padding: 10px 12px;
        font: 700 12px/1.35 Segoe UI, Arial, sans-serif;
    }}
</style>
"""
    if "</body>" in html:
        return html.replace("</body>", banner + "\n</body>", 1)
    return html + banner


def gerar_preview(source_override: str | None = None, open_after: bool = False) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = Path(source_override).expanduser() if source_override else _latest_dashboard()
    if source is None:
        raise FileNotFoundError(
            "Nenhum dashboard consolidado encontrado. Gere o checklist real uma vez para criar "
            "output/dashboard_final.html ou copie um HTML consolidado para a pasta output."
        )
    if not source.exists():
        raise FileNotFoundError(f"Dashboard informado nao encontrado: {source}")

    html = source.read_text(encoding="utf-8", errors="replace")
    PREVIEW_FILE.write_text(_inject_preview_banner(html, source), encoding="utf-8")

    if open_after:
        os.startfile(str(PREVIEW_FILE.resolve()))

    return PREVIEW_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera preview rapido do checklist usando HTML em cache.")
    parser.add_argument("--source", help="Caminho de um HTML consolidado especifico para usar como base.")
    parser.add_argument("--open", action="store_true", help="Abre o preview no navegador.")
    args = parser.parse_args()

    preview = gerar_preview(source_override=args.source, open_after=args.open)
    print(f"Preview gerado: {preview}")


if __name__ == "__main__":
    main()
