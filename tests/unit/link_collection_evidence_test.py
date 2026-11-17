"""Run native collection functions in isolation from Flask/DPAPI/network."""

import ast
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[2]


class LinkCollectionEvidenceTest(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'_coletar_links_regional', '_load_regional_interfaces', '_resolve_link_operational_status'}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.ns = {'datetime': datetime, 'timezone': timezone, 'current_app': MagicMock(),
                   '_selecionar_links_internet_canonicos': lambda value: value,
                   '_obter_links_internet_fallback_local': lambda value: deepcopy(value.get('links', [])),
                   '_is_wan_interface': lambda value: True,
                   '_REGIONAL_LINK_INTERFACE_INCLUDE_OVERRIDE': {},
                   '_selecionar_interface_lan': lambda value: None,
                   '_device_fortimanager_desconectado': lambda value: False,
                   '_should_keep_synced_link': lambda value: True,
                   '_find_link_for_interface': lambda records, value: records[0] if records else None,
                   '_preparar_link_para_template': lambda value: dict(value),
                   '_build_auto_link_id': lambda *args: 'new',
                   '_persistir_links_internet_exibicao': MagicMock(),
                   'gerenciador_regionais': MagicMock(),
                   '_extract_monitor_zabbix_packet_loss': lambda data: (data or {}).get('loss'),
                   '_registrar_sdwan_member': lambda mapping, member: mapping.update(wan1=member),
                   '_buscar_sdwan_member': lambda mapping, *args: mapping.get('wan1'),
                   '_normalize_synced_link': lambda interface, **kwargs: {
                       'nome': 'WAN1', 'interface_monitorada': 'wan1', 'status': 'online',
                       'link_mode_status': interface.get('_link_mode_status', ''),
                       'origem_sync': kwargs['source'], 'fortigate_host': kwargs['fortigate_host']}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'web_config.py', 'exec'), self.ns)
        self.loader = self.ns['_load_regional_interfaces']
        self.real_resolver = self.ns['_resolve_link_operational_status']
        self.ns['_load_regional_interfaces'] = MagicMock(return_value={
            'success': True, 'interfaces': [{'name': 'wan1', '_link_mode_status': 'online'}],
            'runtime_coletado_em': '2026-11-17T12:00:00+00:00',
            'source': 'fortimanager_config+proxy_monitor',
            'device': {'name': 'FGT', 'ip': '192.0.2.1'}, 'adom': 'root'})
        self.regional = {'links': [{'id': '1', 'nome': 'WAN1', 'status': 'online',
                                   'coleta_status_confirmada': True,
                                   'coletado_em': '2026-11-16T12:00:00Z'}]}

    def collect(self, **kwargs):
        return self.ns['_coletar_links_regional']('REG_A', self.regional, **kwargs)

    def test_live_interface_has_real_receipt_time_and_unchanged_status(self):
        result = self.collect(include_sdwan=False)
        item = result['links'][0]
        self.assertTrue(item['coleta_status_confirmada'])
        self.assertEqual(item['coletado_em'], '2026-11-17T12:00:00+00:00')
        self.assertEqual(item['coleta_status_origem'], 'proxy_interface')
        self.assertEqual(item['status'], 'online')

    def test_configuration_alone_does_not_reuse_old_true_marker_as_new_evidence(self):
        self.ns['_load_regional_interfaces'].return_value.update(
            interfaces=[{'name': 'wan1', 'status': 'online'}], runtime_coletado_em=None,
            source='fortimanager')
        item = self.collect(include_sdwan=False)['links'][0]
        self.assertFalse(item['coleta_status_confirmada'])
        self.assertEqual(item['coletado_em'], '2026-11-16T12:00:00Z')

    def test_sdwan_response_supplies_fresh_sla_evidence_without_interface_runtime(self):
        self.ns['_load_regional_interfaces'].return_value.update(
            interfaces=[{'name': 'wan1'}], runtime_coletado_em=None, source='fortimanager')
        client = MagicMock()
        client.proxy_sdwan_members_with_sla.return_value = {
            'success': True, 'membros': [{'sla_status': 'active', 'sla_data': {'loss': 0}, 'member_id': 1}]}
        item = self.collect(fortimanager_client=client)['links'][0]
        self.assertTrue(item['coleta_status_confirmada'])
        self.assertEqual(item['coleta_status_origem'], 'sdwan_monitor')
        self.assertIsNotNone(datetime.fromisoformat(item['coletado_em']).utcoffset())
        self.assertEqual(item['modo_verificacao'], 'monitor_zabbix_packet_loss')

    def test_sla_unknown_does_not_certify_configuration_status(self):
        self.ns['_load_regional_interfaces'].return_value.update(
            interfaces=[{'name': 'wan1'}], runtime_coletado_em=None)
        client = MagicMock()
        client.proxy_sdwan_members_with_sla.return_value = {
            'success': True, 'membros': [{'sla_status': 'unknown', 'sla_data': {}}]}
        self.assertFalse(self.collect(fortimanager_client=client)['links'][0]['coleta_status_confirmada'])

    def test_failed_or_empty_wan_collection_invalidates_fallback_before_persistence(self):
        for changes in ({'success': False}, {'interfaces': []}):
            self.ns['_load_regional_interfaces'].return_value.update(changes)
            result = self.collect(persist=True, include_sdwan=False)
            self.assertFalse(result['success'])
            saved = self.ns['_persistir_links_internet_exibicao'].call_args.args[1]
            self.assertFalse(saved[0]['coleta_status_confirmada'])
            self.assertEqual(saved[0]['coletado_em'], '2026-11-16T12:00:00Z')
            self.ns['_load_regional_interfaces'].return_value['success'] = True

    def test_interface_loader_records_clock_only_on_actual_runtime_response(self):
        self.ns['_get_gerenciador_fortigate_regional'] = lambda *args, **kwargs: {
            'device': {'name': 'FGT'}, 'adom': 'root'}
        self.ns['_obter_links_internet_exibicao'] = lambda *args: [
            {'nome': 'WAN1', 'interface_monitorada': 'wan1', 'status': 'offline'}]
        self.ns['_interface_esta_online'] = lambda item: item.get('status') == 'up'
        client = MagicMock()
        client.proxy_monitor_interfaces.return_value = {'wan1': {'status': 'up'}}
        result = self.loader('REG_A', {}, fortimanager_client=client, include_configuration=False)
        self.assertIsNotNone(datetime.fromisoformat(result['runtime_coletado_em']).utcoffset())
        self.assertEqual(result['interfaces'][0]['_link_mode_status'], 'online')
        client.proxy_monitor_interfaces.return_value = {}
        result = self.loader('REG_A', {}, fortimanager_client=client, include_configuration=False)
        self.assertIsNone(result['runtime_coletado_em'])
        self.assertNotIn('_link_mode_status', result['interfaces'][0])


if __name__ == '__main__':
    unittest.main()
