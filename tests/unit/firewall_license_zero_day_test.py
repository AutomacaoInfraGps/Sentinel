import ast
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import unittest

from jinja2 import Environment

from services.firewall_licenses import license_alert_flags


ROOT = Path(__file__).resolve().parents[2]


def license(days=0, **changes):
    return {'nome': 'forticare', 'status': 'registered', 'expiracao': 1794873600,
            'dias_restantes': days, 'notificacao_critica': False,
            'notificacao_expirada': False, **changes}


class FirewallLicenseZeroDayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.namespace = {'license_alert_flags': license_alert_flags, '_FIREWALL_ALERTA_DIAS': 60,
                         '_LICENCA_STATUS_INDISPONIVEL': set(), 'datetime': datetime}
        names = {'_recalcular_totais_firewalls', '_status_firewall_disponibilidade',
                 '_mapa_recalcular_regionais', '_mapa_adicionar_alerta', '_normalizar_licenca_firewall'}
        tree = ast.parse((ROOT / 'web_config.py').read_text(encoding='utf-8-sig'))
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        if len(selected) != len(names):
            raise AssertionError('Missing production function')
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'web_config.py', 'exec'), cls.namespace)

    def test_known_zero_critical_and_not_already_expired(self):
        flags = license_alert_flags(license())
        self.assertTrue(flags['vencimento_critico'])
        self.assertTrue(flags['alerta_vencimento'])
        self.assertTrue(flags['notificacao_critica'])
        self.assertFalse(flags['notificacao_expirada'])

    def test_warning_boundaries(self):
        for days in (1, 30, 60):
            flags = license_alert_flags(license(days))
            self.assertTrue(flags['alerta_vencimento'])
            self.assertFalse(flags['vencimento_critico'])
        self.assertFalse(license_alert_flags(license(61))['alerta_vencimento'])

    def test_source_normalization_of_today_and_missing_expiry(self):
        normalize = self.namespace['_normalizar_licenca_firewall']
        today = normalize('forticare', {'status': 'registered', 'expires': datetime.now().timestamp()})
        self.assertEqual(today['dias_restantes'], 0)
        self.assertTrue(today['vencimento_critico'])
        unknown = normalize('forticare', {'status': 'registered'})
        self.assertFalse(unknown['vencimento_critico'])
        self.assertFalse(unknown['prazo_conhecido'])

    def test_existing_positive_day_alert_without_expiry_is_preserved(self):
        flags = license_alert_flags(license(30, expiracao=None))
        self.assertTrue(flags['alerta_vencimento'])
        self.assertFalse(flags['vencimento_critico'])

    def test_unknown_expiry_or_invalid_days_never_become_zero_critical(self):
        for expiry in (None, '', 'N/A', 0, False, float('nan'), 'bad'):
            flags = license_alert_flags(license(expiracao=expiry))
            self.assertFalse(flags['vencimento_critico'])
            self.assertFalse(flags['alerta_vencimento'])
        for days in (None, False, '', float('nan'), float('inf')):
            self.assertFalse(license_alert_flags(license(days))['vencimento_critico'])

    def test_unavailable_suppresses_stale_expired_and_zero_flags(self):
        for changes in ({'status': 'offline'}, {'status': 'unknown'}, {'status_indisponivel': True}):
            flags = license_alert_flags(license(notificacao_expirada=True, **changes))
            self.assertFalse(flags['vencimento_critico'])
            self.assertFalse(flags['notificacao_expirada'])

    def test_expired_and_negative_remain_critical(self):
        self.assertTrue(license_alert_flags(license(status='expired'))['vencimento_critico'])
        self.assertTrue(license_alert_flags(license(-1))['notificacao_expirada'])

    def test_firewall_counter_alerts_zero_without_changing_online(self):
        fw = {'status': 'online', 'status_disponibilidade': 'online', 'licencas': [license()]}
        result = self.namespace['_recalcular_totais_firewalls']({'REG_NUTRICAR': [fw]})
        self.assertEqual(result['total_alertas'], 1)
        self.assertEqual(result['total_firewalls_online'], 1)
        self.assertEqual(result['total_expirados'], 0)
        self.assertEqual(fw['licencas_vencimento_critico'], 1)

    def regional(self, availability='online', **changes):
        regional = {key: [] for key in ('servidores', 'switches', 'links', 'aps', 'vpns', 'admins', 'redes_wifi')}
        regional.update(totais={}, status='ok', firewalls=[{
            'status': availability, 'status_disponibilidade': availability, 'licencas': [license()],
        }], **changes)
        return regional

    def test_map_upgrades_cached_zero_to_critical_without_offline(self):
        regional = self.regional()
        summary = self.namespace['_mapa_recalcular_regionais']({'REG_NUTRICAR': regional})
        self.assertEqual(regional['status'], 'critico')
        self.assertEqual(regional['totais']['firewalls_criticos'], 1)
        self.assertEqual(regional['totais']['firewalls_ok'], 0)
        self.assertEqual(summary['firewalls_alerta'], 1)
        self.assertEqual(regional['firewalls'][0]['status_disponibilidade'], 'online')
        self.assertEqual(regional['alertas'], [{'tipo': 'firewalls', 'quantidade': 1,
                                               'severidade': 'critico', 'descricao': 'licencas a vencer'}])

    def test_map_maintenance_and_inactive_not_promoted_to_license_critical(self):
        for availability in ('maintenance', 'inativo'):
            regional = self.regional(availability)
            self.namespace['_mapa_recalcular_regionais']({'REG_A': regional})
            self.assertEqual(regional['totais']['firewalls_criticos'], 0)
            self.assertFalse(any(alert['descricao'] == 'licencas a vencer' for alert in regional['alertas']))
        regional = self.regional(em_manutencao=True)
        self.namespace['_mapa_recalcular_regionais']({'REG_A': regional})
        self.assertEqual(regional['status'], 'maintenance')

    def test_map_missing_expiry_and_offline_do_not_emit_license_alert(self):
        for availability, expiry in (('online', 'N/A'), ('offline', 1794873600)):
            regional = self.regional(availability)
            regional['firewalls'][0]['licencas'][0]['expiracao'] = expiry
            self.namespace['_mapa_recalcular_regionais']({'REG_A': regional})
            self.assertFalse(any(alert['descricao'] == 'licencas a vencer' for alert in regional['alertas']))

    def test_map_mixed_firewalls_no_double_count(self):
        regional = self.regional()
        other = deepcopy(regional['firewalls'][0])
        other['licencas'] = [license(35)]
        regional['firewalls'].append(other)
        self.namespace['_mapa_recalcular_regionais']({'REG_A': regional})
        self.assertEqual(regional['totais']['firewalls_alerta'], 2)
        self.assertEqual(regional['totais']['firewalls_criticos'], 1)
        self.assertEqual(regional['totais']['firewalls_warning'], 1)
        self.assertEqual(regional['totais']['firewalls_ok'], 0)

    def test_template_zero_badges_red_and_unknown_not_green(self):
        template = (ROOT / 'templates/firewalls.html').read_text(encoding='utf-8')
        start = template.index('{% for licenca in forticare_licenses %}')
        end = template.index('{% endfor %}', start) + len('{% endfor %}')
        row = Environment(autoescape=True).from_string(template[start:end])
        for item, expected in ((license(), 'license-critical'), (license(expiracao='N/A'), 'license-unknown')):
            item.update(license_alert_flags(item))
            rendered = row.render(forticare_licenses=[item])
            self.assertIn(expected, rendered)
            if expected == 'license-critical':
                self.assertIn('badge bg-danger', rendered)
                self.assertIn('0 dias', rendered)
                self.assertNotIn('bg-success', rendered)
            else:
                self.assertNotIn('0 dias', rendered)


if __name__ == '__main__':
    unittest.main()
