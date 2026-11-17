import ast
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from services.unifi_wlan_collection import configured_wlan_catalog, confirmed_wlan_receipt, without_wlan_catalog
from services.unifi_networks import (
    extract_unifi_items, merge_wifi_networks, sanitize_ap_wifi_networks, sanitize_site_wifi_networks,
)

AT = '2026-11-17T13:00:00+00:00'
RECEIPT = {'coletado_em': AT, 'origem': 'configuracao_unifi'}


def wlan(**changes):
    return {'_id': 'wlan-1', 'name': 'MARTE', 'networkconf_id': 'network-1', 'enabled': False,
            'wlan_bands': ['2g', '5g'], 'x_passphrase': 'SECRET_VALUE',
            'radius': {'password': 'SECRET_VALUE'}, 'security': 'wpapsk', **changes}


def response(data, status=200):
    result = MagicMock()
    result.status_code = status
    result.json.return_value = data
    return result


def native_functions():
    path = Path(__file__).resolve().parents[2] / 'Unifi.Py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    names = {'_obter_dados_unifi_caminhos', '_obter_dados_unifi_site', 'obter_redes_wifi_site'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = dict(session=MagicMock(), base_url='https://controller.invalid',
                     extract_unifi_items=extract_unifi_items, merge_wifi_networks=merge_wifi_networks,
                     sanitize_ap_wifi_networks=sanitize_ap_wifi_networks,
                     sanitize_site_wifi_networks=sanitize_site_wifi_networks,
                     confirmed_wlan_receipt=confirmed_wlan_receipt, configured_wlan_catalog=configured_wlan_catalog)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class UnifiWlanCollectionTests(unittest.TestCase):
    def test_public_status_keeps_existing_fields_without_new_configuration(self):
        sites = [{'id': 'site', 'nome': 'Site', 'total_aps': 1, 'redes_wifi': [{'nome': 'MARTE'}],
                  'wlans_configuradas': [{'wlan_id': 'CONFIG_PRIVATE'}], 'wlans_coletadas_em': AT,
                  'wlans_situacao': 'confirmada', 'coleta_wlans_confirmada': True}]
        before = deepcopy(sites)
        result = without_wlan_catalog(sites)
        self.assertEqual(before, sites)
        self.assertEqual(result, [{'id': 'site', 'nome': 'Site', 'total_aps': 1, 'redes_wifi': [{'nome': 'MARTE'}]}])
        self.assertNotIn('CONFIG_PRIVATE', repr(result))
        self.assertEqual(without_wlan_catalog(None), [])
        path = Path(__file__).resolve().parents[2] / 'web_config.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'api_public_status_unifi')
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == 'without_wlan_catalog' for node in ast.walk(function)))

    def test_safe_projection_is_detached_and_keeps_real_id_without_passwords(self):
        source = [wlan()]
        before = deepcopy(source)
        result = configured_wlan_catalog(source, RECEIPT)
        self.assertEqual(before, source)
        self.assertTrue(result['coleta_wlans_confirmada'])
        self.assertEqual(result['wlans_coletadas_em'], AT)
        item = result['wlans_configuradas'][0]
        self.assertEqual(item['wlan_id'], 'wlan-1')
        self.assertEqual(item['networkconf_id'], 'network-1')
        self.assertFalse(item['ativo'])
        self.assertNotIn('SECRET_VALUE', str(result))
        self.assertNotIn('security', str(result))
        source[0]['wlan_bands'].append('6g')
        self.assertEqual(item['bandas'], ['2g', '5g'])

    def test_same_name_different_ids_and_case_variants_are_not_merged(self):
        result = configured_wlan_catalog([wlan(), wlan(_id='wlan-2'), wlan(_id='wlan-3', name='marte')], RECEIPT)
        self.assertTrue(result['coleta_wlans_confirmada'])
        self.assertEqual(len(result['wlans_configuradas']), 3)

    def test_duplicate_missing_conflicting_or_invalid_ids_fail_entire_projection(self):
        for items in ([wlan(), wlan()], [wlan(), wlan(_id=None)], [wlan(id='other')],
                      [wlan(_id=True)], [wlan(networkconf_id={'password': 'SECRET_VALUE'})],
                      [wlan(_id='x' * 121)], [None]):
            result = configured_wlan_catalog(items, RECEIPT)
            self.assertFalse(result['coleta_wlans_confirmada'])
            self.assertEqual(result['wlans_configuradas'], [])
            self.assertIsNone(result['wlans_coletadas_em'])
            self.assertEqual(result['wlans_situacao'], 'identidade_ou_estrutura_invalida')
            self.assertNotIn('SECRET_VALUE', str(result))

    def test_no_receipt_is_not_empty_success_but_confirmed_empty_is(self):
        self.assertFalse(configured_wlan_catalog([], None)['coleta_wlans_confirmada'])
        result = configured_wlan_catalog([], RECEIPT)
        self.assertTrue(result['coleta_wlans_confirmada'])
        self.assertEqual(result['wlans_configuradas'], [])
        self.assertEqual(result['wlans_coletadas_em'], AT)

    def test_enabled_unknown_stays_unknown_and_native_name_is_not_truncated(self):
        for value in (None, 0, 'true', 'false', {}):
            item = configured_wlan_catalog([wlan(enabled=value, name=' MARTE ')], RECEIPT)['wlans_configuradas'][0]
            self.assertIsNone(item['ativo'])
            self.assertEqual(item['nome'], ' MARTE ')

    def test_collection_requires_aware_full_time_and_valid_origin(self):
        for receipt in ({'origem': 'runtime_ap', 'coletado_em': AT},
                        {'origem': 'configuracao_unifi', 'coletado_em': '2026-11-17T10:00:00'},
                        {'origem': 'configuracao_unifi', 'coletado_em': '10:00:00'}):
            self.assertFalse(configured_wlan_catalog([wlan()], receipt)['coleta_wlans_confirmada'])

    def test_http_and_api_errors_or_unknown_envelopes_have_no_receipt(self):
        for raw in ({'meta': {'rc': 'error'}, 'data': []}, {'data': [], 'success': False},
                    {'data': [], 'error': 'SECRET_VALUE'}, {'data': [], 'items': []},
                    {'data': [None]}, {}, 'SECRET_VALUE'):
            with self.assertRaises(ValueError) as caught:
                confirmed_wlan_receipt(response(raw), raw)
            self.assertNotIn('SECRET_VALUE', str(caught.exception))
        result = response({})
        result.raise_for_status.side_effect = RuntimeError('HTTP failure')
        with self.assertRaises(RuntimeError):
            confirmed_wlan_receipt(result, [])

    def test_legacy_and_v2_response_shapes_have_aware_receipts(self):
        for raw in ([], {'data': []}, {'items': [wlan()]}, {'results': [wlan()]},
                    {'meta': {'rc': 'ok'}, 'data': [wlan()]}):
            receipt = confirmed_wlan_receipt(response(raw), raw)
            self.assertIsNotNone(datetime.fromisoformat(receipt['coletado_em']).utcoffset())
            self.assertEqual(receipt['origem'], 'configuracao_unifi')

    def test_native_default_api_return_shape_stays_compatible(self):
        namespace = native_functions()
        namespace['session'].get.return_value = response({'data': [wlan()]})
        data, diagnostics = namespace['_obter_dados_unifi_caminhos'](['/first'])
        self.assertEqual(data, [wlan()])
        self.assertEqual(len(diagnostics), 1)
        namespace['session'].get.assert_called_once_with('https://controller.invalid/first', timeout=12)

    def test_native_display_merge_unchanged_and_catalog_has_two_configurations(self):
        namespace = native_functions()
        raw = [wlan(), wlan(_id='wlan-2')]
        namespace['session'].get.side_effect = [response({'data': raw}), response({'data': []}), response({'data': []})]
        displayed, catalog = namespace['obter_redes_wifi_site']('site', [], with_catalog=True)
        expected = merge_wifi_networks(sanitize_site_wifi_networks(raw, []), [])
        self.assertEqual(displayed, expected)
        self.assertEqual(len(displayed), 1)
        self.assertEqual(len(catalog['wlans_configuradas']), 2)
        self.assertTrue(catalog['coleta_wlans_confirmada'])
        self.assertEqual(namespace['session'].get.call_count, 3)

    def test_native_empty_and_failed_responses_differ_without_extra_requests(self):
        namespace = native_functions()
        namespace['session'].get.return_value = response({'data': []})
        _, _, receipt = namespace['_obter_dados_unifi_caminhos'](['/a', '/b'], with_evidence=True)
        self.assertIsNotNone(receipt)
        self.assertEqual(namespace['session'].get.call_count, 2)
        namespace['session'].get.reset_mock()
        namespace['session'].get.side_effect = RuntimeError('failure')
        _, _, receipt = namespace['_obter_dados_unifi_caminhos'](['/a', '/b'], with_evidence=True)
        self.assertIsNone(receipt)
        self.assertEqual(namespace['session'].get.call_count, 2)

    def test_native_api_error_may_keep_display_fallback_but_never_catalog_proof(self):
        namespace = native_functions()
        namespace['session'].get.return_value = response({'meta': {'rc': 'error'}, 'data': []})
        aps = [{'name': 'AP-1', 'vap_table': [{'essid': 'MARTE', 'radio': 'na'}]}]
        with redirect_stdout(io.StringIO()):
            displayed, catalog = namespace['obter_redes_wifi_site']('site', aps, with_catalog=True)
        self.assertEqual(displayed, sanitize_ap_wifi_networks(aps))
        self.assertFalse(catalog['coleta_wlans_confirmada'])
        self.assertEqual(catalog['wlans_configuradas'], [])

    def test_existing_site_permission_filter_also_removes_separate_catalog(self):
        path = Path(__file__).resolve().parents[2] / 'web_config.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_filtrar_unifi_por_escopo_regional')
        namespace = {'_mapa_encontrar_regional_unifi': lambda regionals, site: {'Bahia': 'REG_BAHIA', 'Other': 'REG_OTHER'}.get(site)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        source = {'sites': [{'nome': 'Bahia', 'wlans_configuradas': [{'wlan_id': 'allowed', 'nome': 'MARTE'}]},
                            {'nome': 'Other', 'wlans_configuradas': [{'wlan_id': 'denied', 'nome': 'DENIED_SSID'}]}]}
        result = namespace['_filtrar_unifi_por_escopo_regional'](source, {'REG_BAHIA': {}, 'REG_OTHER': {}},
                                                               lambda code: code == 'REG_BAHIA')
        self.assertEqual(len(result['sites']), 1)
        self.assertEqual(result['sites'][0]['wlans_configuradas'][0]['wlan_id'], 'allowed')
        self.assertNotIn('DENIED_SSID', repr(result))
        self.assertEqual(len(source['sites']), 2)


if __name__ == '__main__':
    unittest.main()
