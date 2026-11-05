"""Smoke test da interface real com respostas sinteticas, sem iniciar o Sentinel."""
import json
from pathlib import Path
from jinja2 import Environment, DictLoader
from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parents[2]
    template = (root / 'templates/revisao_acessos.html').read_text(encoding='utf-8')
    base = '''<!doctype html><html><head><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">{% block extra_css %}{% endblock %}</head><body><script>window.bootstrap={Modal:{getOrCreateInstance:()=>({show(){}})}};</script>{% block content %}{% endblock %}{% block extra_js %}{% endblock %}</body></html>'''
    env = Environment(loader=DictLoader({'base.html': base, 'page.html': template}), autoescape=True)
    capabilities = {area: {'completa': {'available': True, 'diagnostics': []}} for area in ('windows','linux','admanager','firewalls')}
    html = env.get_template('page.html').render(runner={'available': True, 'message': 'Pronto'}, access_review_capabilities=capabilities)
    source_id = '550e8400-e29b-41d4-a716-446655440000'
    new_id = '550e8400-e29b-41d4-a716-446655440001'
    reviews = [{'id': area, 'name': area, 'state': state, 'can_regenerate': area == 'linux', 'reason': 'Evidência sintética'}
               for area, state in [('windows','collection'), ('linux','document'), ('admanager','success'), ('firewalls','collection')]]
    requests = []
    errors = []
    def route_request(route):
        path = route.request.url.split('sentinel-preview.test')[-1]
        if path == '/':
            route.fulfill(content_type='text/html', body=html)
            return
        if path == '/api/revisao-acessos/logs':
            data = {'success': True, 'logs': [{'id': 'auditoria:' + source_id, 'log_label': 'RevAcc_2026-10-20_12:46:48',
                'url': '/revisao-acessos?execucao=' + source_id, 'duration_seconds': 77, 'reviews': reviews}]}
        elif path == '/api/revisao-acessos/documents':
            data = {'success': True, 'executions': []}
        elif path == '/api/revisao-acessos/executions':
            requests.append(route.request.post_data_json)
            data = {'success': True, 'job_id': new_id}
        else:
            data = {'success': True, 'job': {'id': new_id, 'kind': 'revisao_acessos', 'status': 'completed',
                'percent': 100, 'message': 'Concluído', 'meta': {'events': []}}}
        route.fulfill(content_type='application/json', body=json.dumps(data))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('https://sentinel-preview.test/**', route_request)
            page.goto('https://sentinel-preview.test/')
            page.locator('.review-process').first.wait_for()
            assert page.locator('.review-process').count() == 4
            assert page.locator('.review-state-legend').count() == 1
            assert page.locator('input[name=executionMode]').count() == 0
            page.get_by_role('button', name='Gerar documentos novamente', exact=True).click()
            assert page.locator('.review-recovery input:disabled').count() == 3
            page.locator('.review-recovery input[value=linux]').check()
            page.get_by_role('button', name='Gerar 1 documento(s)', exact=True).click()
            page.wait_for_function('document.getElementById("progressTitle").textContent === "Concluído"')
            assert requests == [{'mode': 'somente_montagem', 'audits': ['linux'], 'source_execution_id': source_id}]
            assert not errors, errors
            print('Interface: ícones, legenda única, expansão, seleção e envio vinculados à origem — OK')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
