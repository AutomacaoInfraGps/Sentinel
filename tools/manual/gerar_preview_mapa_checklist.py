"""Gera somente o mapa visual do checklist usando o cache compartilhado."""

import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PREVIEW = PROJECT_ROOT / "output" / "dashboard_preview.html"
MAP_CACHE = PROJECT_ROOT / "output" / "mapa_monitoramento_cache.json"
EXECUTAR_TUDO = PROJECT_ROOT / "executar_tudo.py"
PREVIEW_FILE = PROJECT_ROOT / "output" / "mapa_checklist_preview.html"


def _extract_section(document, section_id):
    start_match = re.search(
        rf"<section\b[^>]*\bid=[\"']{re.escape(section_id)}[\"'][^>]*>",
        document,
        re.IGNORECASE,
    )
    if not start_match:
        return ""
    depth = 1
    for tag in re.finditer(r"</?section\b[^>]*>", document[start_match.end():], re.IGNORECASE):
        if tag.group(0).lower().startswith("</section"):
            depth -= 1
            if depth == 0:
                end = start_match.end() + tag.end()
                return document[start_match.start():end]
        else:
            depth += 1
    return ""


def _extract_between(document, start_marker, end_marker):
    start = document.find(start_marker)
    end = document.find(end_marker, start + len(start_marker))
    if start < 0 or end <= start:
        return ""
    return document[start:end]


def _json_for_script(value):
    return json.dumps(value, ensure_ascii=False, default=str).replace("</", "<\\/")


def _load_embedded_javascript(function_name):
    source = EXECUTAR_TUDO.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        rf"def {re.escape(function_name)}\(\):.*?return r\"\"\"(.*?)\n\"\"\"",
        source,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"JavaScript embutido nao encontrado: {function_name}.")
    return match.group(1)


def _adjust_tooltips(map_js):
    map_js = map_js.replace("Servidores em warning", "Servidores em atenção")
    map_js = map_js.replace("Switches em warning", "Switches em atenção")
    map_js = map_js.replace(
        "problemText: mainProblem ? `${mainProblem[0]}: ${mainProblem[1]}` : 'Sem alerta detectado',",
        "problemText: problems.length ? `${problems.slice(0, 2).map((item) => `${item[0]}: ${item[1]}`).join(' | ')}${problems.length > 2 ? '...' : ''}` : 'Sem alerta detectado',",
    )
    map_js = map_js.replace(
        "const problemText = mainProblem\n            ? `${mainProblem[0]}: ${mainProblem[1]}`\n            : 'Sem alerta detectado';",
        "const problemText = problems.length\n            ? `${problems.slice(0, 2).map((item) => `${item[0]}: ${item[1]}`).join(' | ')}${problems.length > 2 ? '...' : ''}`\n            : 'Sem alerta detectado';",
    )
    return map_js


def generate_preview():
    if not SOURCE_PREVIEW.exists():
        raise FileNotFoundError("dashboard_preview.html nao encontrado para fornecer o visual do checklist.")
    if not MAP_CACHE.exists():
        raise FileNotFoundError("Cache do mapa nao encontrado. Abra o mapa principal primeiro.")

    source = SOURCE_PREVIEW.read_text(encoding="utf-8", errors="replace")
    payload = json.loads(MAP_CACHE.read_text(encoding="utf-8"))
    css = _extract_between(source, "        .regional-inventory-group {", "        .kpi-container {")
    map_html = _extract_section(source, "map-view")
    map_js = _extract_between(
        source,
        "let infraMapSelectedRegional = '';",
        "setDashboardView(document.querySelector('.dashboard-view-tab.active')",
    )
    if not css or not map_html or not map_js:
        raise ValueError("O visual do mapa do checklist nao pode ser extraido do preview existente.")

    bootstrap = "\n".join(
        [
            "window.SENTINEL_MAPA_CHECKLIST_STATIC = true;",
            f"window.SENTINEL_MAPA_CHECKLIST_DATA = {_json_for_script(payload)};",
        ]
    )
    adapter = _load_embedded_javascript("_montar_adaptador_dados_mapa_checklist")
    criticality_tooltips = _load_embedded_javascript("_montar_tooltips_criticidade_mapa_checklist")
    counters = _load_embedded_javascript("_montar_contadores_mapa_checklist")
    map_js = _adjust_tooltips(map_js)
    document = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preview do mapa do checklist - Sentinel</title>
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; min-height: 100%; background: #071923; font-family: Arial, sans-serif; }}
.dashboard-view {{ display: block !important; min-height: 100vh; }}
{css}
</style>
</head>
<body>
{map_html}
<script>
{bootstrap}
{adapter}
window.abrirEIrParaDetalhe = window.abrirEIrParaDetalhe || function () {{}};
{map_js}
{criticality_tooltips}
{counters}
</script>
</body>
</html>
"""
    PREVIEW_FILE.write_text(document, encoding="utf-8")
    resumo = payload.get("resumo") or {}
    print(f"Preview do mapa do checklist gerado: {PREVIEW_FILE}")
    print(f"Regionais: {len(payload.get('regionais') or [])}")
    print(f"VPNs offline: {resumo.get('vpns_offline', 0)}")
    return PREVIEW_FILE


if __name__ == "__main__":
    generate_preview()
