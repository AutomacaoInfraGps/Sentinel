import ast
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from flask import Flask

from notification_center import (
    build_notifications, decorate_with_read_state, dismiss_notifications,
    mark_notifications_seen, sort_notifications,
)
from regional_access import filter_records


ROOT = Path(__file__).resolve().parents[2]


def firewall(days=0, **changes):
    return {'nome': 'FGT_NUTRICAR', 'regional': 'REG_NUTRICAR', 'status': 'online',
            'status_disponibilidade': 'online', 'changed_at': '2026-11-16T11:00:00-03:00',
            'licencas': [{'nome': 'forticare', 'status': 'registered',
                          'dias_restantes': days, 'expiracao': 1794873600}], **changes}


class FirewallLicenseNotificationTest(unittest.TestCase):
    def test_zero_online_notifies_even_without_old_warning_flag(self):
        raw = firewall()
        before = deepcopy(raw)
        items = build_notifications({'firewalls': [raw]})
        self.assertEqual(raw, before)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item['type'], 'firewall_license_critical')
        self.assertEqual(item['severity'], 'critical')
        self.assertIn('vence hoje', item['title'])
        self.assertIn('0 dias restantes', item['message'])
        self.assertIn('forticare', item['message'])
        self.assertEqual(item['url'], '/firewalls?q=FGT_NUTRICAR')

    def test_positive_days_and_threshold(self):
        for day in (1, 35, 60):
            item = build_notifications({'firewalls': [firewall(day)]})[0]
            self.assertEqual(item['severity'], 'important')
            self.assertIn(f'vence em {day} ', item['message'])
            self.assertEqual(item['days_remaining'], day)
        self.assertEqual(build_notifications({'firewalls': [firewall(61)]}), [])

    def test_deadlines_precede_other_events_and_sort_by_urgency(self):
        records = {'firewalls': [firewall(35), firewall(0), firewall(4)],
                   'links': [{'nome': 'WAN', 'status': 'offline', 'changed_at': '2026-11-16T15:00:00'}]}
        items = build_notifications(records)
        self.assertEqual([item.get('days_remaining') for item in items], [0, 4, 35, None])
        combined = sort_notifications([{'type': 'admin_baseline', 'occurred_at': '2026-11-17'},
                                       {'type': 'vpn_orphan', 'occurred_at': '2026-11-17'}, *items])
        self.assertEqual(combined[0]['type'], 'firewall_license_critical')
        self.assertEqual(combined[3]['type'], 'vpn_orphan')
        self.assertEqual(combined[4]['type'], 'admin_baseline')

    def test_missing_expiry_zero_does_not_invent_a_deadline(self):
        for expiry in (None, '', 'N/A', 0):
            item = firewall()
            item['licencas'][0]['expiracao'] = expiry
            self.assertEqual(build_notifications({'firewalls': [item]}), [])

    def test_unavailable_and_maintenance_do_not_create_license_notification(self):
        for changes in ({'em_manutencao': True}, {'status_disponibilidade': 'maintenance'},
                        {'status_disponibilidade': 'inativo'}, {'status': 'maintenance'}):
            self.assertEqual(build_notifications({'firewalls': [firewall(**changes)]}), [])
        item = firewall()
        item['licencas'][0]['status'] = 'offline'
        self.assertEqual(build_notifications({'firewalls': [item]}), [])

    def test_offline_preserves_availability_notification_without_duplicate(self):
        items = build_notifications({'firewalls': [firewall(status='offline', status_disponibilidade='offline')]})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'firewalls')
        self.assertEqual(items[0]['severity'], 'critical')

    def test_frontend_renders_messages_as_text_and_supports_critical_color(self):
        script = (ROOT / 'static/notifications/notifications.js').read_text(encoding='utf-8')
        css = (ROOT / 'static/notifications/notifications.css').read_text(encoding='utf-8')
        self.assertIn('message.textContent = notification.message', script)
        self.assertIn('notification.severity', script)
        self.assertIn('.notification-item-icon {', css)
        self.assertIn('background: #e03a47;', css)

    def test_multiple_products_summarized_once_with_critical_first(self):
        item = firewall(35)
        second = dict(item['licencas'][0], nome='fortiguard', dias_restantes=0)
        item['licencas'].append(second)
        items = build_notifications({'firewalls': [item]})
        self.assertEqual(len(items), 1)
        self.assertIn('fortiguard', items[0]['message'])
        self.assertEqual(items[0]['days_remaining'], 0)

    def test_expired_not_falsely_described_as_today(self):
        item = firewall()
        item['licencas'][0]['status'] = 'expired'
        result = build_notifications({'firewalls': [item]})[0]
        self.assertIn('vencida', result['title'])
        self.assertNotIn('vence hoje', result['message'])

    def test_escalation_has_new_id_and_read_dismiss_remain_per_user(self):
        early = build_notifications({'firewalls': [firewall(1)]})
        today = build_notifications({'firewalls': [firewall(0)]})
        self.assertNotEqual(early[0]['id'], today[0]['id'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            mark_notifications_seen('user1', [early[0]['id']], path)
            dismiss_notifications('user1', [early[0]['id']], path)
            visible, unread = decorate_with_read_state('user1', today, path)
            self.assertEqual(unread, 1)
            dismiss_notifications('user1', [today[0]['id']], path)
            self.assertEqual(decorate_with_read_state('user1', today, path)[0], [])
            self.assertEqual(decorate_with_read_state('user2', today, path)[1], 1)

    def test_actual_notification_endpoint_scopes_before_building(self):
        state = {'groups': {'firewalls': {'updated_at': '2026-11-16T14:00:00Z',
                  'records': [firewall(), firewall(nome='FGT_POA', regional='REG_TLSV_POA')]}}}
        app = Flask(__name__)
        namespace = {
            'load_operational_state': lambda: state,
            'snapshot_is_fresh': lambda value: True,
            'filter_records': filter_records,
            '_current_user_groups': lambda: ['GGS_SUPORTE_NUTRICAR'],
            '_available_regional_codes': lambda: ['REG_NUTRICAR', 'REG_TLSV_POA'],
            '_reconcile_notification_servers': lambda records: records,
            'can_operate_sentinel': lambda groups: False,
            '_notification_orphan_vpn_names': lambda records: set(),
            'build_notifications': build_notifications,
            'sort_notifications': sort_notifications,
            'load_alertad_notifications': lambda *args, **kwargs: [],
            'load_access_review_notifications': lambda *args, **kwargs: [],
            '_mapa_carregar_cache': lambda: ({}, 0),
            '_mapa_refresh_esta_em_andamento': lambda: False,
            'decorate_with_read_state': lambda user, records: (records, len(records)),
            'current_user': SimpleNamespace(get_id=lambda: 'user'), 'ENV_CONFIG': {},
            'current_app': app, 'jsonify': lambda value: value,
        }
        tree = ast.parse((ROOT / 'web_config.py').read_text(encoding='utf-8-sig'))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'api_notifications')
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'web_config.py', 'exec'), namespace)
        result = namespace['api_notifications']()
        self.assertEqual(len(result['notifications']), 1)
        self.assertEqual(result['notifications'][0]['regional'], 'REG_NUTRICAR')
        self.assertNotIn('FGT_POA', str(result))


if __name__ == '__main__':
    unittest.main()
