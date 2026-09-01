from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_AUTOMACAO = Path("C:/Users/Public/Automacao")
FALLBACK_MSG = "Mapa por regional indisponivel neste arquivo. Gere o preview/checklist novamente."


def _extrair_bloco_marcado(texto, inicio, fim):
    pos_inicio = texto.find(inicio)
    if pos_inicio < 0:
        return ""
    pos_inicio += len(inicio)
    pos_fim = texto.find(fim, pos_inicio)
    if pos_fim < 0:
        return ""
    return texto[pos_inicio:pos_fim].strip()


def _extrair_section_por_id(texto, section_id):
    marcador = f'<section id="{section_id}"'
    inicio = texto.find(marcador)
    if inicio < 0:
        return ""

    profundidade = 0
    pos = inicio
    while True:
        prox_abre = texto.find("<section", pos)
        prox_fecha = texto.find("</section>", pos)
        if prox_fecha < 0:
            return ""

        if prox_abre != -1 and prox_abre < prox_fecha:
            profundidade += 1
            pos = prox_abre + len("<section")
            continue

        profundidade -= 1
        pos = prox_fecha + len("</section>")
        if profundidade == 0:
            return texto[inicio:pos].strip()


def _extrair_css(texto):
    css = _extrair_bloco_marcado(texto, "/* CHECKLIST_MAP_CSS_START */", "/* CHECKLIST_MAP_CSS_END */")
    if css:
        return css

    inicio = texto.find("        .infra-map-shell {")
    if inicio < 0:
        inicio = texto.find("        .regional-inventory-toolbar {")
    fim = texto.find("        .kpi-container {", inicio)
    if inicio >= 0 and fim <= inicio:
        fim = texto.find("</style>", inicio)
    if inicio < 0 or fim <= inicio:
        return ""
    return texto[inicio:fim].strip()


def _extrair_js(texto):
    js = _extrair_bloco_marcado(texto, "// CHECKLIST_MAP_JS_START", "// CHECKLIST_MAP_JS_END")
    if js:
        return js

    inicio = texto.find("let infraMapSelectedRegional = '';")
    fim = texto.find("setDashboardView(document.querySelector('.dashboard-view-tab.active')", inicio)
    if inicio >= 0 and fim <= inicio:
        fim = texto.find("</script>", inicio)
    if inicio < 0 or fim <= inicio:
        return ""
    return texto[inicio:fim].strip()


def validar(caminho):
    erros = []
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    css = _extrair_css(texto)
    html = _extrair_bloco_marcado(texto, "<!-- CHECKLIST_MAP_HTML_START -->", "<!-- CHECKLIST_MAP_HTML_END -->")
    if not html:
        html = _extrair_section_por_id(texto, "map-view")
    js = _extrair_js(texto)

    if not css or ".infra-map-shell" not in css:
        erros.append("CSS do mapa nao encontrado.")
    if not html or "infra-map-shell" not in html:
        erros.append("HTML do mapa nao encontrado.")
    if html and FALLBACK_MSG in html:
        erros.append("HTML do mapa contem a mensagem de fallback.")
    if not js or "infraMapSelectedRegional" not in js:
        erros.append("JavaScript do mapa nao encontrado.")
    if "/api/mapa" in html or "/api/mapa" in js or "localhost" in html or "localhost" in js:
        erros.append("Mapa do checklist depende de Flask/localhost/API e nao esta estatico.")

    return erros, {
        "css": len(css),
        "html": len(html),
        "js": len(js),
        "regionais": html.count("infra-map-list-item"),
        "pontos": html.count("infra-map-dot"),
    }


def main():
    relatorios = sorted(
        (PUBLIC_AUTOMACAO / "relatorio_preventiva").glob("**/relatorio_preventiva_*.html"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ) if (PUBLIC_AUTOMACAO / "relatorio_preventiva").exists() else []

    candidatos = [
        ("fonte_versionada", PROJECT_ROOT / "templates" / "mapa_checklist_base.html", True),
        ("preview", PROJECT_ROOT / "output" / "mapa_checklist_preview.html", False),
        ("dashboard_final", PROJECT_ROOT / "output" / "dashboard_final.html", False),
    ]
    if relatorios:
        candidatos.append(("relatorio_mais_recente", relatorios[0], False))

    algum_arquivo = False
    preview_ok = False
    for nome, caminho, obrigatorio in candidatos:
        if not caminho.exists():
            nivel = "ERRO" if obrigatorio else "INFO"
            print(f"[{nivel}] Nao encontrado ({nome}): {caminho}")
            continue

        algum_arquivo = True
        erros, metricas = validar(caminho)
        if erros:
            nivel = "ERRO" if obrigatorio else "AVISO"
            print(f"[{nivel}] {nome}: {caminho}")
            for erro in erros:
                print(f"  - {erro}")
            continue

        if obrigatorio:
            preview_ok = True
        print(f"[OK] {nome}: {caminho}")
        print(
            "  css={css} html={html} js={js} regionais={regionais} pontos={pontos}".format(
                **metricas
            )
        )

    if not algum_arquivo:
        print("[ERRO] Nenhuma fonte ou saida do mapa do checklist foi encontrada.")
        return 1

    if not preview_ok:
        print("[ERRO] Fonte versionada invalida. Corrija o mapa-base antes de gerar o checklist.")
        return 1

    print("[OK] Mapa do checklist pronto para ser embutido no dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
