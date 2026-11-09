"""Exercise appearance settings in an isolated app, without production services."""

import argparse
from threading import Thread

from flask import render_template, render_template_string
from flask_login import login_user
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from tests.unit.sofia_page_test import ROOT, ChatUser, create_preview_app


def create_theme_app():
    app = create_preview_app()
    app.jinja_env.tests["maintenance"] = lambda value: value == "maintenance"

    @app.before_request
    def preview_user():
        login_user(ChatUser())

    @app.get("/theme-preview")
    def preview():
        return render_template_string("""{% extends 'base.html' %}
        {% block content %}
        <div class="infra-page-header"><h1>Aparência do Sentinel</h1>
        <p>Prévia local dos componentes da interface.</p></div>
        <div class="card mb-4" id="sample-card"><div class="card-body">
          <h2 class="h5">Consulta de infraestrutura</h2>
          <label for="sample-input" class="form-label">Buscar regional</label>
          <input class="form-control mb-3" id="sample-input" placeholder="Nome da regional">
          <select class="form-select" aria-label="Situação"><option>Todos os estados</option></select>
        </div></div>
        <div class="table-responsive mb-4"><table class="table table-striped mb-0">
          <thead><tr><th>Equipamento</th><th>Situação</th></tr></thead>
          <tbody><tr><td>Equipamento de exemplo</td><td><span class="badge bg-success">Online</span></td></tr>
          <tr><td>Outro equipamento</td><td><span class="badge bg-danger">Offline</span></td></tr></tbody>
        </table></div>
        <div class="alert alert-success">Operação normal</div>
        <div class="alert alert-warning">Atenção necessária</div>
        <div class="alert alert-danger">Falha identificada</div>
        <button class="btn btn-outline-primary">Atualizar dados</button>
        {% endblock %}""")

    @app.get("/theme-login")
    def login_preview():
        return render_template("login.html")

    @app.get("/theme-wan")
    def wan_preview():
        return render_template("wan_status.html")

    @app.get("/theme-regionais")
    def regionais_preview():
        regional = dict(codigo="REG_PREVIA", nome="Regional de exemplo", descricao="Dados de teste",
                        total_servidores=0, total_links=0, total_switches=0, total_vpns=0,
                        total_firewalls=0, tem_firewall_a_vencer=False, em_manutencao=False,
                        servidores=[], links=[], switches=[], vpns=[], firewalls=[])
        return render_template("regionais.html", regionais=[regional])

    @app.get("/theme-unifi")
    def unifi_preview():
        sites = {}
        for index, risk in enumerate(("OK", "ATENCAO", "CRITICO")):
            ap = dict(nome=f"AP Exemplo {index}", risco=risk, cu_total=65,
                      cu_self_tx=20, cu_self_rx=30, tx_retry=5, clientes=3,
                      status="online", em_manutencao=False, modelo="U6", ip="192.0.2.1", firmware="teste")
            sites[f"REG_PREVIA_{risk}"] = [dict(canal=36, risco=risk, aps=[ap], quantidade=1)]
        return render_template("antenas_simples.html",
                               unifi_data=dict(interferencia_5ghz_por_site=sites, total_aps=3),
                               sites_agrupados=[dict(nome="Regional de exemplo", online=1, offline=0, maintenance=0, aps=[ap])])

    @app.get("/theme-links")
    def links_preview():
        links = [dict(nome=f"WAN{index + 1}", regional="REG_PREVIA", codigo_regional="REG_PREVIA",
                      status=status, ip=f"192.0.2.{index + 1}", velocidade="100 Mbps", tipo="physical",
                      ultima_verificacao="2026-11-05T10:00:00", alias="Link de exemplo", mascara="",
                      estatisticas=dict(bandwidth_in=10000, bandwidth_out=5000,
                                        bandwidth_in_readable="10 Kbps", bandwidth_out_readable="5 Kbps"))
                 for index, status in enumerate(("online", "offline"))]
        return render_template("links_internet.html", links=links,
                               links_por_regional={"REG_PREVIA": links}, sd_wan_por_regional={}, resumo_links={})

    @app.get("/theme-vpn")
    def vpn_preview():
        return render_template("vpn_ipsec.html", regionais_vpn=["REG_ONLINE", "REG_MISTA"],
                               vpns_por_regional={
                                   "REG_ONLINE": dict(nome_exibicao="Regional online", online=1, offline=0,
                                                      tunels=[dict(tunel="T001_EXEMPLO", status="up", ultima_verificacao="10:00:00")]),
                                   "REG_MISTA": dict(nome_exibicao="Regional mista", online=1, offline=1,
                                                     tunels=[dict(tunel="T002_EXEMPLO", status="up", ultima_verificacao="10:00:00"),
                                                             dict(tunel="T003_EXEMPLO", status="down", ultima_verificacao="10:00:00")])},
                               vpn_total=3, vpn_online=2, vpn_offline=1, vpn_total_regionais=2,
                               vpn_regionais_sem_offline=1, vpn_regionais_com_offline=1)

    return app


def main():
    app = create_theme_app()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    screenshots = ROOT / "instance" / "theme-preview"
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1080})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            context.route("**/test/api_notifications*", lambda route: route.fulfill(
                content_type="application/json", body='{"notifications":[],"unread_count":0}'))
            context.route("**/api/fortigate/wan/status*", lambda route: route.fulfill(
                content_type="application/json", body='{"success":true,"data":[]}'))
            page.goto(base + "/theme-preview", wait_until="networkidle")
            assert page.locator("html").get_attribute("data-sentinel-theme") == "light"
            light_bg = page.locator("#sample-card").evaluate("e => getComputedStyle(e).backgroundColor")
            page.screenshot(path=str(screenshots / "light.png"), full_page=True)
            page.get_by_role("button", name="Tema escuro", exact=True).click()
            assert page.locator("html").get_attribute("data-bs-theme") == "dark"
            assert page.locator("#sample-card").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(23, 30, 39)"
            page.wait_for_function("getComputedStyle(document.getElementById('sample-input')).backgroundColor === 'rgb(17, 26, 35)'")
            assert page.locator(".alert-success").evaluate("e => getComputedStyle(e).backgroundColor") != page.locator(".alert-danger").evaluate("e => getComputedStyle(e).backgroundColor")
            assert page.locator("[data-theme-choice=dark]").get_attribute("aria-pressed") == "true"
            assert page.evaluate("localStorage.getItem('sentinel.theme.v1')") == "dark"
            page.screenshot(path=str(screenshots / "dark.png"), full_page=True)
            page.reload(wait_until="networkidle")
            assert page.locator("html").get_attribute("data-sentinel-theme") == "dark"
            other = context.new_page()
            other.goto(base + "/theme-login", wait_until="networkidle")
            assert other.locator("html").get_attribute("data-sentinel-theme") == "dark"
            assert other.locator("#password").get_attribute("type") == "password"
            other.screenshot(path=str(screenshots / "login-dark.png"), full_page=True)
            page.get_by_role("button", name="Tema claro", exact=True).click()
            other.wait_for_function("document.documentElement.dataset.sentinelTheme === 'light'")
            assert page.locator("#sample-card").evaluate("e => getComputedStyle(e).backgroundColor") == light_bg
            page.get_by_role("button", name="Seguir tema do sistema").click()
            page.emulate_media(color_scheme="dark")
            page.wait_for_function("document.documentElement.dataset.sentinelTheme === 'dark'")
            page.emulate_media(color_scheme="light")
            page.wait_for_function("document.documentElement.dataset.sentinelTheme === 'light'")
            page.get_by_role("button", name="Tema escuro", exact=True).click()
            page.emulate_media(color_scheme="light")
            assert page.locator("html").get_attribute("data-sentinel-theme") == "dark"
            page.goto(base + "/test-widget", wait_until="networkidle")
            page.locator("#sofiaLauncher").click()
            assert page.locator(".sofia-messages").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(17, 27, 36)"
            page.goto(base + "/theme-preview", wait_until="networkidle")
            page.locator("#sofiaClose").click()
            page.emulate_media(media="print")
            assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(255, 255, 255)"
            page.emulate_media(media="screen")
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#sidebarToggle").click()
            page.get_by_role("button", name="Tema claro", exact=True).click()
            page.get_by_role("button", name="Tema escuro", exact=True).click()
            page.screenshot(path=str(screenshots / "mobile-dark.png"), full_page=True)
            page.goto(base + "/theme-wan", wait_until="networkidle")
            assert page.locator("html").get_attribute("data-sentinel-theme") == "dark"
            assert page.locator(".container").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(23, 30, 39)"
            page.set_viewport_size({"width": 1440, "height": 1080})
            page.goto(base + "/theme-regionais", wait_until="networkidle")
            assert page.locator(".regional-card .card-body").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(23, 30, 39)"
            assert page.locator(".regional-device-title").first.evaluate("e => getComputedStyle(e).color") == "rgb(158, 217, 237)"
            page.screenshot(path=str(screenshots / "regionais-dark.png"), full_page=True)
            page.goto(base + "/theme-unifi", wait_until="networkidle")
            page.evaluate("filtrarCanais('all')")
            header = page.locator(".interf-site-header").first
            assert header.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(29, 40, 51)"
            assert header.evaluate("e => getComputedStyle(e).color") == "rgb(220, 231, 237)"
            assert page.locator('[data-site-risco="OK"]').evaluate("e => getComputedStyle(e).borderLeftColor") == "rgb(40, 167, 69)"
            assert page.locator('[data-site-risco="ATENCAO"]').evaluate("e => getComputedStyle(e).borderLeftColor") == "rgb(255, 193, 7)"
            assert page.locator('[data-site-risco="CRITICO"]').evaluate("e => getComputedStyle(e).borderLeftColor") == "rgb(220, 53, 69)"
            header.click()
            assert page.locator(".interf-site-body").first.is_visible()
            assert page.locator(".interf-site-body").first.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(23, 30, 39)"
            page.mouse.move(0, 0)
            page.screenshot(path=str(screenshots / "unifi-dark.png"), full_page=True)
            page.get_by_role("button", name="Tema claro", exact=True).click()
            page.wait_for_function("getComputedStyle(document.querySelector('.interf-site-header')).backgroundColor === 'rgb(248, 249, 250)'")
            page.screenshot(path=str(screenshots / "unifi-light.png"), full_page=True)
            page.goto(base + "/theme-links", wait_until="networkidle")
            assert page.locator(".links-region-block").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(255, 255, 255)"
            page.get_by_role("button", name="Tema escuro", exact=True).click()
            assert page.locator(".links-region-block").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(23, 30, 39)"
            assert page.locator(".link-meta-item").first.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(29, 40, 51)"
            assert page.locator(".link-meta-value").first.evaluate("e => getComputedStyle(e).color") == "rgb(220, 231, 237)"
            assert page.locator(".link-traffic-panel").first.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(29, 40, 51)"
            assert page.locator(".link-online").evaluate("e => getComputedStyle(e).backgroundImage") != page.locator(".link-offline").evaluate("e => getComputedStyle(e).backgroundImage")
            page.screenshot(path=str(screenshots / "links-dark.png"), full_page=True)
            page.goto(base + "/theme-vpn", wait_until="networkidle")
            assert page.locator(".region-online").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(18, 40, 32)"
            assert page.locator(".region-offline").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(45, 32, 37)"
            assert page.locator(".vpn-region-header h4").first.evaluate("e => getComputedStyle(e).color") == "rgb(220, 231, 237)"
            assert page.locator(".vpn-status-pill.up").first.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(25, 135, 84)"
            assert page.locator(".vpn-status-pill.down").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(220, 53, 69)"
            page.screenshot(path=str(screenshots / "vpn-dark.png"), full_page=True)
            page.locator('[data-filter-vpn="offline"]').click()
            assert page.locator(".vpn-tunnel-row:visible").count() == 1
            page.evaluate("limparFiltrosVpn()")
            page.get_by_role("button", name="Tema claro", exact=True).click()
            assert "238, 250, 242" in page.locator(".region-online").evaluate("e => getComputedStyle(e).backgroundImage")
            page.screenshot(path=str(screenshots / "vpn-light.png"), full_page=True)
            blocked = browser.new_context()
            blocked.add_init_script("""Storage.prototype.getItem = Storage.prototype.setItem = function () { throw new Error('blocked'); };""")
            blocked_page = blocked.new_page()
            blocked_page.goto(base + "/theme-login", wait_until="networkidle")
            blocked_page.get_by_role("button", name="Tema escuro", exact=True).click()
            assert blocked_page.locator("html").get_attribute("data-sentinel-theme") == "dark"
            assert not errors, errors
            browser.close()
            print("OK: themes, persistence, system preference, tab sync, login, widget, mobile, WAN, print and blocked storage")
    finally:
        server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=5100)
    args = parser.parse_args()
    if args.serve:
        create_theme_app().run(host="127.0.0.1", port=args.port, debug=False)
    else:
        main()
