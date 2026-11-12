import json
from pathlib import Path
import shutil
import subprocess
import unittest


TEMPLATE = Path(__file__).resolve().parents[2] / 'templates' / 'mapa_monitoramento.html'


@unittest.skipUnless(shutil.which('node'), 'Node required for map text tests')
class MapLicenseSummaryTests(unittest.TestCase):
    def test_license_deadlines_and_missing_data(self):
        source = TEMPLATE.read_text(encoding='utf-8')
        helper = source[source.index('        function alertSummaryText('):source.index('        function tooltipDetail(')]
        license = dict(nome='forticare', notificacao_critica=True, status='valid',
                       expiracao=1794873600, dias_restantes=4)
        alert = dict(tipo='firewalls', descricao='licencas a vencer', quantidade=1)

        def regional(*licenses, **changes):
            return {'firewalls': [{'status': 'warning', 'status_disponibilidade': 'online',
                                   'licencas': list(licenses), **changes}]}

        cases = [
            [alert, regional(license), 'Licença vence em 4 dias'],
            [alert, regional({**license, 'dias_restantes': 39}), 'Licença vence em 39 dias'],
            [alert, regional({**license, 'dias_restantes': 1}), 'Licença vence em 1 dia'],
            [alert, regional({**license, 'dias_restantes': 0}), 'Licença vence hoje'],
            [alert, regional({**license, 'dias_restantes': -2}), 'Licença vencida há 2 dias'],
            [alert, regional({**license, 'dias_restantes': 0, 'notificacao_expirada': True}), 'Licença vencida'],
            [alert, regional(license, {**license, 'dias_restantes': 2}), 'Menor prazo: 2 dias para vencer'],
            [alert, regional(license, {**license, 'dias_restantes': 1, 'notificacao_critica': False}), 'Licença vence em 4 dias'],
            [alert, regional(license, {**license, 'dias_restantes': None}), 'Menor prazo: 4 dias para vencer (dados parciais)'],
            [alert, regional({**license, 'dias_restantes': '4', 'expiracao': '2026-11-17'}), 'Licença vence em 4 dias'],
            [dict(tipo='links', descricao='links offline', quantidade=2), regional(license), 'links offline: 2'],
            [dict(tipo='firewalls', descricao='firewall offline', quantidade=1), regional(license), 'firewall offline: 1'],
        ]
        for value in (None, '', False, 'N/A', 0.5):
            cases.append([alert, regional({**license, 'dias_restantes': value}), 'Prazo da licença indisponível'])
        for expiry in ('N/A', '', None, 0):
            cases.append([alert, regional({**license, 'expiracao': expiry}), 'Prazo da licença indisponível'])
        for changes in ({'status': 'offline'}, {'status_disponibilidade': 'inativo'},
                        {'status_disponibilidade': 'maintenance'}):
            cases.append([alert, regional(license, **changes), 'Prazo da licença indisponível'])
        for changes in ({'status': 'offline'}, {'status': 'unavailable'}, {'status_indisponivel': True}):
            cases.append([alert, regional({**license, **changes}), 'Prazo da licença indisponível'])
        cases.append([alert, {}, 'Prazo da licença indisponível'])
        runner = helper + """
const fs = require('node:fs');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = cases.map(([alert, regional]) => {
    const before = JSON.stringify([alert, regional]);
    const text = alertSummaryText(alert, regional);
    if (before !== JSON.stringify([alert, regional])) throw new Error('Map data mutated');
    return text;
});
process.stdout.write(JSON.stringify(results));
"""
        result = subprocess.run(['node', '-e', runner], input=json.dumps(cases), capture_output=True,
                                text=True, encoding='utf-8', check=True)
        self.assertEqual(json.loads(result.stdout), [case[2] for case in cases])

    def test_both_map_tooltips_and_sidebar_use_deadline_text(self):
        source = TEMPLATE.read_text(encoding='utf-8')
        self.assertIn('visible.map((a) => alertSummaryText(a, regional))', source)
        self.assertIn('escapeMapHtml(alertSummaryText(alerta, regional))', source)
        # Timeline identity and severity totals must continue using original descriptions/counts.
        self.assertIn('Number(alerta.quantidade || 0)', source)


if __name__ == '__main__':
    unittest.main()
