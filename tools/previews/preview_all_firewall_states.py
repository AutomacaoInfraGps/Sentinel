"""Prévia isolada dos estados de firmware; não acessa configurações ou rede."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.firewall_releases import assess, format_firmware
from jinja2 import Environment, DictLoader


def main():
    catalog = {'FG-60F': [(7, 4, 13), (8, 0, 2)]}
    cases = [
        ('01 — ✔ Verde: último patch da família 8', '8.0.2', 'FortiGate-60F', catalog, 'current'),
        ('02 — ! Vermelho: patch da família 7 disponível', '7.4.9', 'FortiGate-60F', catalog, 'update'),
        ('03 — ✔ Verde: versão 8 isolada não alerta a família 7', '7.4.13', 'FortiGate-60F', catalog, 'current'),
        ('04 — X Cinza: consulta sem resultado', '7.4.13', 'FortiGate-60F', None, 'unknown'),
        ('05 — X Cinza: modelo não reconhecido', '7.4.13', 'MODELO-SIMULADO', catalog, 'unknown'),
        ('06 — X Cinza: firmware não reconhecido', 'N/A', 'FortiGate-60F', catalog, 'unknown'),
    ]
    groups = {}
    for n, (label, firmware, hardware, data, state) in enumerate(cases, 1):
        update = assess(data, hardware, firmware)
        assert update['state'] == state
        raw = firmware + ', build2933' if firmware != 'N/A' else firmware
        groups[label] = [{'nome': f'FIREWALL-FICTICIO-{n:02}', 'model': hardware,
                          'ip': f'192.0.2.{n}', 'serial': f'SIMULADO-{n:02}',
                          'status': 'online', 'status_disponibilidade': 'online',
                          'firmware': raw, 'firmware_display': format_firmware(raw),
                          'firmware_update': update, 'licencas': []}]
    base = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Exemplos fictícios de firmware</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    </head><body style="background:#edf3f6;padding:24px">
    <div class="alert alert-info"><strong>EXEMPLOS SIMULADOS.</strong> Versões e equipamentos fictícios.
    Nenhum acesso ao FortiManager ou ao catálogo é realizado. Passe o mouse nas badges.
    As bibliotecas visuais são carregadas do CDN, como na página real.</div>
    {% block content %}{% endblock %}
    <script>document.querySelectorAll('button').forEach(b=>b.disabled=true);</script>
    </body></html>'''
    env = Environment(loader=DictLoader({'base.html': base,
        'page': (ROOT / 'templates/firewalls.html').read_text(encoding='utf-8')}), autoescape=True)
    env.tests['maintenance'] = lambda value: False
    env.globals['url_for'] = lambda *args, **kwargs: '#'
    html = env.get_template('page').render(firewalls_por_regional=groups,
        total_firewalls=len(groups), total_firewalls_online=len(groups),
        total_firewalls_offline=0, total_firewalls_inativos=0,
        total_firewalls_maintenance=0, total_alertas=0, total_expirados=0,
        cache_atualizado_em='DADOS FICTÍCIOS', usando_cache=True)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    badges = soup.select('.firmware-symbol')
    assert len(badges) == 6
    assert sum('bg-success' in b['class'] for b in badges) == 2
    assert sum('bg-danger' in b['class'] for b in badges) == 1
    assert sum('bg-warning' in b['class'] for b in badges) == 0
    assert sum('bg-secondary' in b['class'] for b in badges) == 3
    target = ROOT / 'instance/previews/firewall_states.html'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding='utf-8')
    print(f'Seis estados e cores validados. Exemplo: {target}')


if __name__ == '__main__':
    main()
