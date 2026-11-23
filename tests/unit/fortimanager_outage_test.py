"""Disconnected firewall is evidence of unavailability, not a fresh WAN measurement."""

import ast
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from fortimanager_client import FortiManagerClient
from services.firewall_licenses import license_alert_flags
from tests.unit import link_sdwan_canonical_test as canonical


class FortimanagerOutageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        canonical.LinkSdwanCanonicalTests.setUpClass()
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'_get_gerenciador_fortigate_regional', '_device_fortimanager_desconectado',
                 '_status_firewall_disponibilidade', 'listar_firewalls', '_recalcular_totais_firewalls'}
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        for node in selected:
            node.decorator_list = []
        cls.code = compile(ast.Module(body=selected, type_ignores=[]), 'isolated-outage', 'exec')

    def setUp(self):
        base = canonical.LinkSdwanCanonicalTests()
        base.setUp()
        self.ns = base.ns
        self.ns.update(license_alert_flags=license_alert_flags, _FIREWALL_ALERTA_DIAS=60)
        exec(self.code, self.ns)
        self.ns.update(_resolve_fortigate_credentials=lambda: {}, _get_fortimanager_adom=lambda: 'root',
                       _REGIONAL_DEVICE_OVERRIDE={'REG_ORMEC_PARA': ['FTG_ORMEC_PARA']},
                       _get_cached_fortimanager_device=lambda code: {}, _rank_fortimanager_devices=lambda *args: [],
                       _match_fortimanager_device=lambda code, info, devices: devices[0])
        self.device = {'name': 'FTG_ORMEC_PARA', 'ip': '192.0.2.1', 'status': 'ready',
                       'conn_status': 'down', 'dev_status': 'auto_updated', 'adm_pass': 'SECRET'}
        self.old = {'id': 'wan1', 'nome': 'WAN1', 'interface_monitorada': 'wan1', 'provedor': 'GARRA',
                    'ip': '8.8.8.8', 'status': 'online', 'coleta_status_confirmada': True,
                    'coletado_em': '2026-11-18T12:00:00+00:00', 'ultima_verificacao': 'old',
                    'link_mode_status': 'online', 'packet_loss_percent': 0}

    def resolve(self):
        return self.ns['_get_gerenciador_fortigate_regional'](
            'REG_ORMEC_PARA', {}, adom='root', fortimanager_devices=[self.device])

    def test_resolver_preserves_connection_state_but_not_password_or_other_raw_fields(self):
        result = self.resolve()
        self.assertTrue(result['fortimanager_inventory_available'])
        self.assertEqual(result['device']['conn_status'], 'down')
        self.assertEqual(result['device']['dev_status'], 'auto_updated')
        self.assertNotIn('adm_pass', result['device'])

    def test_live_disconnected_inventory_short_circuits_proxy(self):
        client = MagicMock()
        self.ns['_get_gerenciador_fortigate_regional'] = lambda *args, **kwargs: self.resolve_result
        # Resolve before replacing the function used by the loader.
        self.resolve_result = {'device': self.device, 'adom': 'root', 'fortimanager_inventory_available': True}
        result = self.ns['_load_regional_interfaces']('REG_ORMEC_PARA', {}, fortimanager_client=client)
        self.assertEqual(result['status'], 'fortimanager_device_offline')
        self.assertFalse(result['success'])
        self.assertTrue(result['disponibilidade_observada_em'].endswith('+00:00'))
        client.list_device_interfaces.assert_not_called()
        client.proxy_monitor_interfaces.assert_not_called()

    def test_cached_inventory_down_alone_does_not_short_circuit_current_proxy(self):
        self.ns['_get_gerenciador_fortigate_regional'] = lambda *args, **kwargs: {
            'device': self.device, 'adom': 'root', 'fortimanager_inventory_available': False}
        client = MagicMock()
        client.list_device_interfaces.return_value = {'result': [{'data': [{'name': 'wan1'}]}]}
        client.proxy_monitor_interfaces.return_value = {'wan1': {'status': 'up'}}
        result = self.ns['_load_regional_interfaces']('REG_ORMEC_PARA', {}, fortimanager_client=client)
        self.assertTrue(result['success'])
        client.proxy_monitor_interfaces.assert_called_once()

    def test_outage_keeps_link_visible_offline_without_fabricating_interface_time_or_loss(self):
        self.ns['_get_gerenciador_fortigate_regional'] = lambda *args, **kwargs: {
            'device': self.device, 'adom': 'root', 'fortimanager_inventory_available': True}
        client = MagicMock()
        result = self.ns['_coletar_links_regional']('REG_ORMEC_PARA', {'links_internet_auto': [deepcopy(self.old)]},
                                                   fortimanager_client=client, persist=True)
        self.assertTrue(result['success'])
        link = result['links'][0]
        self.assertEqual(link['status'], 'offline')
        self.assertEqual(link['modo_verificacao'], 'fortimanager_device_offline')
        self.assertTrue(link['estado_inferido_do_firewall'])
        self.assertFalse(link['coleta_status_confirmada'])
        self.assertEqual(link['coletado_em'], self.old['coletado_em'])
        self.assertEqual(link['ultima_verificacao'], 'old')
        self.assertIsNone(link['packet_loss_percent'])
        self.assertEqual(link['sla_status'], 'unknown')
        self.ns['_persistir_links_internet_exibicao'].assert_called_once()
        client.proxy_sdwan_members_with_sla.assert_not_called()

    def test_offline_without_known_links_does_not_invent_wans(self):
        self.ns['_get_gerenciador_fortigate_regional'] = lambda *args, **kwargs: {
            'device': self.device, 'adom': 'root', 'fortimanager_inventory_available': True}
        result = self.ns['_coletar_links_regional']('REG_ORMEC_PARA', {}, fortimanager_client=MagicMock())
        self.assertEqual(result['links'], [])
        self.assertFalse(result['success'])

    def test_recovery_uses_new_interface_evidence_and_removes_outage_inference(self):
        previous = {**self.old, 'estado_inferido_do_firewall': True, 'firewall_nome_origem': 'FTG_ORMEC_PARA',
                    'disponibilidade_observada_em': '2026-11-18T12:01:00+00:00', 'status': 'offline'}
        self.ns['_find_link_for_interface'] = lambda *args: previous
        self.ns['_load_regional_interfaces'] = MagicMock(return_value={
            'success': True, 'interfaces': [{'name': 'wan1', 'ip': '8.8.8.8', 'alias': 'GARRA',
                                           'role': 'wan', 'status': 'up', '_link_mode_status': 'online'}],
            'device': {'name': 'FTG_ORMEC_PARA', 'conn_status': 'up'}, 'adom': 'root',
            'runtime_coletado_em': '2026-11-19T19:00:00+00:00', 'source': 'fortimanager_config+proxy_monitor'})
        result = self.ns['_coletar_links_regional']('REG_ORMEC_PARA', {'links_internet_auto': [previous]}, include_sdwan=False)
        self.assertEqual(result['links'][0]['status'], 'online')
        self.assertTrue(result['links'][0]['coleta_status_confirmada'])
        self.assertEqual(result['links'][0]['coletado_em'], '2026-11-19T19:00:00+00:00')
        self.assertNotIn('estado_inferido_do_firewall', result['links'][0])

    def test_proxy_error_without_manager_down_is_not_evidence_of_an_outage(self):
        self.ns['_load_regional_interfaces'] = MagicMock(return_value={
            'success': False, 'status': 'fortimanager_interfaces_error', 'message': 'Unavailable'})
        result = self.ns['_coletar_links_regional']('REG_ORMEC_PARA', {'links_internet_auto': [self.old]}, persist=True)
        self.assertFalse(result['success'])
        self.assertEqual(result['links'][0]['status'], 'online')
        saved = self.ns['_persistir_links_internet_exibicao'].call_args.args[1][0]
        self.assertFalse(saved['coleta_status_confirmada'])
        self.assertNotIn('estado_inferido_do_firewall', saved)

    def test_consistent_text_states_and_legacy_numeric_values_not_guessed(self):
        for value, disconnected, availability in (('down', True, 'offline'), ('up', False, 'online'),
                                                   ('unknown', False, 'unknown'), (0, False, 'unknown'),
                                                   (1, False, 'unknown'), (2, False, 'unknown')):
            with self.subTest(value=value):
                data = {'conn_status': value, 'status': 'ready', 'licencas': [{'status': 'registered'}]}
                self.assertEqual(self.ns['_device_fortimanager_desconectado'](data), disconnected)
                self.assertEqual(self.ns['_status_firewall_disponibilidade'](data), availability)
        self.assertEqual(self.ns['_status_firewall_disponibilidade']({'licencas': [{'status': 'registered'}]}), 'unknown')
        self.assertEqual(self.ns['_status_firewall_disponibilidade']({'status': 'maintenance', 'conn_status': 'down'}), 'maintenance')

    def test_device_list_requests_textual_enums_without_changing_other_requests(self):
        client = object.__new__(FortiManagerClient)
        client.session = MagicMock()
        client.base_url = 'https://example.invalid/jsonrpc'
        client.sessionid = 'TEST_SESSION'
        client.session.post.return_value.json.return_value = {'result': [{'status': {'code': 0}, 'data': []}]}
        client.list_devices('root')
        self.assertEqual(client.session.post.call_args.kwargs['json']['verbose'], 1)
        client.list_adoms()
        self.assertNotIn('verbose', client.session.post.call_args.kwargs['json'])

    def test_unknown_connection_is_not_counted_as_ok_in_map(self):
        regional = {key: [] for key in ('servidores', 'switches', 'links', 'aps', 'vpns', 'firewalls', 'admins', 'redes_wifi')}
        regional.update(totais={}, firewalls=[{'status': 'unknown', 'status_disponibilidade': 'unknown', 'licencas': []}])
        summary = self.ns['_mapa_recalcular_regionais']({'REG_ORMEC_PARA': regional})
        self.assertEqual(summary['firewalls_ok'], 0)
        self.assertEqual(summary['firewalls_unknown'], 1)

    def test_firewall_remains_in_inventory_if_offline_or_license_proxy_fails(self):
        for connection in ('down', 'up'):
            with self.subTest(connection=connection):
                device = {**self.device, 'conn_status': connection}
                client = MagicMock()
                client.list_devices.return_value = {'result': [{'data': [device]}]}
                client.proxy_monitor_license.side_effect = RuntimeError('SECRET')
                save = MagicMock()
                self.ns.update(
                    request=SimpleNamespace(args={}), FortiManagerClient=lambda: client,
                    gerenciador_regionais=SimpleNamespace(listar_regionais=lambda: ['REG_ORMEC_PARA'], obter_regional=lambda code: {}),
                    gerenciador_switches=SimpleNamespace(obter_hosts_em_manutencao_direta=lambda **kwargs: []),
                    _carregar_cache_dashboard=lambda *args, **kwargs: {}, _salvar_cache_dashboard=save,
                    _resolver_regional_firewall=lambda name, codes: 'REG_ORMEC_PARA',
                    _formatar_firmware_firewall=lambda data: '7.4.0', format_firmware=str,
                    catalog_from_fortimanager=lambda data: None, assess_firewall_release=lambda *args: {},
                    _aplicar_fallback_forticare_device_data=lambda *args: None,
                    _aplicar_ultima_licenca_valida=lambda *args: None,
                    apply_device_maintenance=lambda records, hosts, **kwargs: records,
                )
                with redirect_stdout(StringIO()):
                    result = self.ns['listar_firewalls'](return_data=True, force_refresh=True)
                self.assertTrue(result['success'], result.get('message'))
                firewall = result['firewalls_por_regional']['REG_ORMEC_PARA'][0]
                self.assertEqual(firewall['nome'], device['name'])
                self.assertEqual(firewall['conn_status'], connection)
                self.assertEqual(firewall['status_disponibilidade'], 'offline' if connection == 'down' else 'online')
                self.assertEqual(result['total_firewalls'], 1)
                save.assert_called_once()
                if connection == 'down':
                    client.proxy_monitor_license.assert_not_called()


if __name__ == '__main__':
    unittest.main()
