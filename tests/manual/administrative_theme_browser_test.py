"""Isolated synthetic previews: no production imports, accounts, workbook, or SQL."""

from threading import Thread

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from tests.manual.theme_browser_test import create_theme_app, ROOT


def main():
    server = make_server('127.0.0.1', 0, create_theme_app(), threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    folder = ROOT / 'instance' / 'theme-preview'
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1080})
            context.route('**/test/api_notifications*', lambda route: route.fulfill(
                content_type='application/json', body='{"notifications":[],"unread_count":0}'))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for route, selectors in (
                ('admins', ('.filter-bar', '.device-card.ok .device-header', '.device-card.indisponivel .device-header')),
                ('emails', ('.editor-shell', '.contact-block--diretor', '.field-warning')),
                ('firewalls', ('.firewall-metric-panel', '.verification-meta'))):
                response = page.goto(f'http://127.0.0.1:{server.server_port}/theme-{route}', wait_until='networkidle')
                assert response.status == 200, route
                page.get_by_role('button', name='Tema escuro', exact=True).click()
                if route == 'emails':
                    page.locator('#regional-select').select_option('0')
                    page.wait_for_timeout(100)
                for selector in selectors:
                    color = page.locator(selector).first.evaluate('e => getComputedStyle(e).backgroundColor')
                    assert color not in ('rgb(255, 255, 255)', 'rgba(0, 0, 0, 0)'), (route, selector, color)
                    rgb = [int(value.strip()) for value in color[color.index('(') + 1:color.index(')')].split(',')[:3]]
                    assert max(rgb) < 120, (route, selector, color)
                if route == 'admins':
                    page.locator('.device-card.ok .device-header').click()
                    assert page.locator('.device-card.ok .admins-ok-list').is_visible()
                    page.locator('[data-filter="indisponivel"]').click()
                    assert page.locator('.device-card:visible').count() == 1
                    page.locator('[data-filter="total"]').click()
                if route == 'emails':
                    assert page.locator('.email-stats-card[data-filter-mode="pending-emails"]').evaluate(
                        'e => getComputedStyle(e).color') == 'rgb(220, 231, 237)'
                    assert page.locator('.table-primary').first.evaluate(
                        'e => getComputedStyle(e).getPropertyValue("--bs-table-color").trim()') == '#dce7ed'
                page.screenshot(path=str(folder / f'{route}-dark.png'), full_page=True)
                page.get_by_role('button', name='Tema claro', exact=True).click()
                if route == 'admins':
                    assert page.locator('.filter-bar').evaluate('e => getComputedStyle(e).backgroundColor') == 'rgb(255, 255, 255)'
                page.screenshot(path=str(folder / f'{route}-light.png'), full_page=True)
                page.get_by_role('button', name='Tema escuro', exact=True).click()
                page.set_viewport_size({'width': 390, 'height': 844})
                page.evaluate('window.scrollTo(0, 0)')
                page.wait_for_timeout(500)
                page.screenshot(path=str(folder / f'{route}-mobile-dark.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1080})
            assert not errors, errors
            browser.close()
            print('OK: admin filters/expansion, email selection, dark surfaces, light theme and mobile previews')
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
