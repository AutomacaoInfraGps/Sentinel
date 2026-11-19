import ast
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

from services.unifi_radio_collection import ap_radio_evidence

AT = '2026-11-19T14:00:00-03:00'


class UnifiRadioCollectionTests(unittest.TestCase):
    def ap(self):
        return {'mac': '00-11-22-AA-BB-CC', 'state': 1, 'password': 'SECRET_MARKER',
                'radio_table': [{'name': 'wifi0', 'radio': 'na', 'channel': 'auto'}],
                'radio_table_stats': [{'name': 'wifi0', 'radio': 'na', 'cu_total': 0,
                                       'cu_self_tx': 1.5, 'tx_retries_pct': 3,
                                       'password': 'SECRET_MARKER', 'clients': ['PRIVATE_PERSON']}]}

    def test_explicit_zero_missing_null_and_receipt_not_measurement(self):
        ap = self.ap()
        before = copy.deepcopy(ap)
        result = ap_radio_evidence(ap, 'site-a', AT)
        self.assertEqual(result['mac'], '00:11:22:aa:bb:cc')
        self.assertTrue(result['identidade_ap_informada'])
        self.assertEqual(result['recebido_em'], '2026-11-19T17:00:00+00:00')
        self.assertIsNone(result['medido_em'])
        self.assertFalse(result['data_medicao_confirmada'])
        row = result['estatisticas']['registros'][0]
        self.assertEqual(row['cu_total'], 0)
        self.assertEqual(row['situacao_campos']['cu_total'], 'informado')
        self.assertIsNone(row['cu_self_rx'])
        self.assertEqual(row['situacao_campos']['cu_self_rx'], 'ausente')
        self.assertEqual(row['tx_retry'], 3)
        self.assertNotIn('SECRET_MARKER', json.dumps(result))
        self.assertNotIn('PRIVATE_PERSON', json.dumps(result))
        self.assertEqual(before, ap)

    def test_invalid_metrics_not_coerced_to_zero(self):
        for value in (None, True, '0', -1, 101, 10**400, float('nan'), float('inf'), [], {}):
            ap = self.ap()
            ap['radio_table_stats'][0]['cu_total'] = value
            row = ap_radio_evidence(ap, 'site-a', AT)['estatisticas']['registros'][0]
            self.assertIsNone(row['cu_total'])
            self.assertEqual(row['situacao_campos']['cu_total'], 'nulo' if value is None else 'invalido')

    def test_missing_empty_and_invalid_tables_distinct(self):
        for ap, expected in (({}, 'ausente'), ({'radio_table': None}, 'nulo'),
                             ({'radio_table': {}}, 'estrutura_invalida'),
                             ({'radio_table': []}, 'presente')):
            self.assertEqual(ap_radio_evidence(ap, 'site-a', AT)['configuracoes']['situacao'], expected)
        result = ap_radio_evidence({'radio_table': [None, 'SECRET_MARKER', {}]}, 'site-a', AT)
        self.assertEqual(result['configuracoes']['registros_invalidos'], 2)
        self.assertIsNone(result['configuracoes']['registros'][0]['nome_interface'])

    def test_duplicate_or_missing_interface_not_identified_by_band(self):
        ap = self.ap()
        ap['radio_table'].append(dict(ap['radio_table'][0]))
        ap['radio_table_stats'][0].pop('name')
        result = ap_radio_evidence(ap, 'site-a', AT)
        self.assertTrue(all(not r['interface_unica_na_tabela'] for r in result['configuracoes']['registros']))
        self.assertFalse(result['estatisticas']['registros'][0]['interface_unica_na_tabela'])

    def test_all_bands_auto_zero_and_offline_preserved_without_inference(self):
        ap = self.ap()
        ap['state'] = 0
        ap['radio_table'].extend([{'name': 'wifi1', 'radio': 'ng', 'channel': 0},
                                  {'name': 'wifi2', 'radio': '6e', 'channel': 37}])
        result = ap_radio_evidence(ap, 'site-a', AT)
        self.assertFalse(result['ap_online_declarado'])
        self.assertEqual([r['canal'] for r in result['configuracoes']['registros']], ['auto', 0, 37])
        self.assertEqual(len(result['estatisticas']['registros']), 1)
        self.assertFalse(result['data_medicao_confirmada'])

    def test_invalid_identity_and_time_fail_closed_without_exceptions(self):
        for mac in ('00:00:00:00:00:00', 'ffffffffffff', 'invalid', [], None):
            result = ap_radio_evidence({'mac': mac, 'state': True}, [], '2026-11-19T12:00:00')
            self.assertFalse(result['identidade_ap_informada'])
            self.assertIsNone(result['mac'])
            self.assertIsNone(result['ap_online_declarado'])
            self.assertIsNone(result['recebido_em'])

    def test_both_collectors_use_same_response_and_do_not_change_legacy_projection(self):
        root = Path(__file__).resolve().parents[2]
        for path in ('UniFi.py', 'scripts/Unifi.py'):
            tree = ast.parse((root / path).read_text(encoding='utf-8-sig'))
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'ap_radio_evidence']
            self.assertEqual(len(calls), 1)
            self.assertEqual([arg.id for arg in calls[0].args], ['ap', 'site_id', 'collected_at'])
            containers = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
                          and any(isinstance(key, ast.Constant) and key.value == 'radios_nativos' for key in node.keys)]
            self.assertEqual(len(containers), 1)
            self.assertFalse(any(isinstance(key, ast.Constant) and key.value == 'cu_total' for key in containers[0].keys))

    def test_complete_collectors_preserve_legacy_json_and_request_count(self):
        root = Path(__file__).resolve().parents[2]

        class WithoutRadioExtension(ast.NodeTransformer):
            def visit_Dict(self, node):
                node = self.generic_visit(node)
                pairs = [(key, value) for key, value in zip(node.keys, node.values)
                         if not (isinstance(key, ast.Constant) and key.value == 'radios_nativos')]
                node.keys = [key for key, _ in pairs]
                node.values = [value for _, value in pairs]
                return node

        def run(source, directory):
            requests = ModuleType('requests')
            session = MagicMock()
            requests.Session = lambda: session
            devices = [dict(self.ap(), type='uap', name='AP TEST', ip='192.0.2.1',
                            model='U7PG2', version='test', num_sta=2, uptime=10)]

            def response(url, **kwargs):
                result = MagicMock(status_code=200, text='ok')
                data = ([{'name': 'site-a', 'desc': 'Site A'}] if '/self/sites' in url else
                        copy.deepcopy(devices) if '/stat/device' in url else [])
                result.json.return_value = {'meta': {'rc': 'ok'}, 'data': data}
                return result

            session.get.side_effect = response
            session.post.side_effect = response
            config, store = ModuleType('config'), ModuleType('data_store')
            config.UNIFI_HTML = str(Path(directory) / 'unifi.html')
            config.UNIFI_CONFIG = {'host': 'synthetic.invalid', 'port': 8443,
                                   'username': 'fake', 'password': 'fake'}
            config.ensure_directories = lambda: None
            saved = []
            store.save_data = lambda component, data: saved.append(copy.deepcopy(data))
            with patch.dict('sys.modules', {'requests': requests, 'config': config, 'data_store': store}), redirect_stdout(io.StringIO()):
                exec(compile(source, '<synthetic-unifi>', 'exec'), {'__name__': '__synthetic__'})
            self.assertEqual(len(saved), 1)
            return saved[0], [call.args[0] for call in session.get.call_args_list]

        with tempfile.TemporaryDirectory() as directory:
            for filename in ('UniFi.py', 'scripts/Unifi.py'):
                with self.subTest(collector=filename):
                    tree = ast.parse((root / filename).read_text(encoding='utf-8-sig'))
                    original = ast.fix_missing_locations(WithoutRadioExtension().visit(copy.deepcopy(tree)))
                    with patch('services.unifi_ap_collection.confirmed_device_response',
                               side_effect=lambda response: (response.json()['data'], AT)), patch(
                                   'services.unifi_wlan_collection.confirmed_wlan_receipt',
                                   return_value={'coletado_em': AT, 'origem': 'configuracao_unifi'}):
                        before, old_requests = run(original, directory)
                        after, new_requests = run(tree, directory)
                    self.assertEqual(old_requests, new_requests)
                    for ap in after['aps']:
                        self.assertTrue(ap.pop('radios_nativos')['identidade_ap_informada'])
                    self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
