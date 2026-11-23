"""Exercise canonical link discovery and cached map reconciliation without Flask/DPAPI."""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[2]


class LinkSdwanCanonicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'_is_wan_interface', '_is_legacy_named_wan_candidate', '_should_keep_synced_link',
                 '_is_forti_non_public_wan_candidate', '_is_meaningful_provider_text',
                 '_extract_provider_name', '_normalizar_link_texto', '_is_excluded_wan_name',
                 '_is_public_ip', '_extract_interface_ip', '_normalizar_link_ip',
                 '_normalizar_estado_operacional', '_interface_esta_online',
                 '_normalize_synced_link', '_coletar_links_regional', '_load_regional_interfaces',
                 '_resolve_link_operational_status',
                 '_sdwan_member_keys', '_registrar_sdwan_member', '_buscar_sdwan_member',
                 '_mapa_links_regionais', '_mapa_sincronizar_links_payload', '_mapa_carregar_cache',
                 '_mapa_recalcular_regionais', '_mapa_adicionar_alerta',
                 '_is_internet_link_candidate', '_filtrar_links_internet',
                 '_obter_links_internet_exibicao', '_obter_links_detalhe_regional',
                 '_coletar_links_multiregional', '_ordenar_regionais_links'}
        cls.code = compile(ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                                           and node.name in names], type_ignores=[]), 'isolated-links', 'exec')

    def setUp(self):
        self.ns = {'datetime': datetime, 'timezone': timezone, 're': re, 'ipaddress': ipaddress, 'json': json,
                   '_compact_identifier': lambda value: re.sub('[^A-Z0-9]', '', str(value or '').upper()),
                   '_REGIONAL_LINK_INTERFACE_INCLUDE_OVERRIDE': {}, 'current_app': MagicMock(),
                   '_extract_interface_addressing_mode': lambda value: '',
                   '_extract_interface_mask': lambda value: '', '_format_prefix_mask': str,
                   '_format_bandwidth_from_interface': lambda value: 'Banda nao registrada',
                   '_selecionar_interface_lan': lambda value: None,
                   '_selecionar_links_internet_canonicos': lambda value: value,
                   '_obter_links_internet_fallback_local': lambda info: deepcopy(info.get('links_internet_auto', [])),
                   '_device_fortimanager_desconectado': lambda value: False,
                   '_find_link_for_interface': lambda values, new: None,
                   '_build_auto_link_id': lambda code, name, values: name,
                   '_preparar_link_para_template': dict,
                   '_extract_monitor_zabbix_packet_loss': lambda value: None,
                   '_persistir_links_internet_exibicao': MagicMock(),
                   '_mapa_status': lambda value: value,
                   '_mapa_sincronizar_servidores_payload': lambda value: value,
                   '_formatar_nome_link_dashboard': lambda value: value['nome'],
                   '_ordenar_links_internet': lambda value: value}
        exec(self.code, self.ns)
        self.interfaces = [
            {'name': 'wan1', 'ip': '0.0.0.0', 'role': 'wan', 'status': 'down'},
            {'name': 'wan2', 'ip': '0.0.0.0', 'role': 'wan', 'status': 'down'},
            {'name': 'dmz', 'alias': 'VIVO', 'ip': '8.8.8.8', 'role': 'wan', 'type': 'physical', 'status': 'up'},
            {'name': 'ha1', 'alias': 'ALGAR', 'ip': '1.1.1.1', 'role': 'wan', 'type': 'physical', 'status': 'up'},
            {'name': 'T_VPN', 'ip': '10.0.0.1', 'type': 'tunnel', 'status': 'up'}]

    def collect(self, *, members=True):
        interfaces = deepcopy(self.interfaces)
        for item in interfaces:
            item['_link_mode_status'] = 'online' if item['status'] == 'up' else 'offline'
        self.ns['_load_regional_interfaces'] = MagicMock(return_value={
            'success': True, 'interfaces': interfaces, 'device': {'name': 'FGT'},
            'adom': 'root', 'source': 'fortimanager_config+proxy_monitor',
            'runtime_coletado_em': '2026-11-19T19:00:00+00:00'})
        client = MagicMock()
        client.proxy_sdwan_members_with_sla.return_value = {
            'success': members, 'membros': [{'interface': name, 'sla_status': 'active'}
                                          for name in ('dmz', 'ha1', 'T_VPN')] if members else []}
        return self.ns['_coletar_links_regional']('REG_TESTE', {}, fortimanager_client=client)

    def test_sdwan_members_discovered_before_port_filter_and_survive_canonical_read(self):
        result = self.collect()
        self.assertTrue(result['success'])
        self.assertEqual([link['interface_monitorada'] for link in result['links']], ['dmz', 'ha1'])
        self.assertTrue(all(link['sdwan_member_confirmado'] for link in result['links']))
        self.assertTrue(all(link['coleta_status_confirmada'] for link in result['links']))
        self.assertEqual(self.ns['_obter_links_internet_exibicao']({'links_internet_auto': result['links']}), result['links'])
        self.assertTrue(all('sdwan_member_confirmado' not in item for item in self.interfaces))

    def test_no_membership_does_not_admit_dmz_ha_lan_or_tunnels(self):
        self.assertFalse(self.collect(members=False)['success'])
        for name, ip, kind in (('dmz', '10.0.0.1', 'physical'), ('ha1', '10.0.0.2', 'physical'),
                               ('T_VPN', '8.8.8.8', 'tunnel'), ('internal', '8.8.8.8', 'physical')):
            interface = {'name': name, 'ip': ip, 'alias': 'VIVO', 'type': kind, 'status': 'up',
                         'sdwan_member_confirmado': True}
            self.assertFalse(self.ns['_is_wan_interface'](interface))

    def test_existing_legacy_wan_alias_still_works_without_sdwan(self):
        interface = {'name': 'dmz', 'alias': '(WAN_VIVO)', 'ip': '8.8.8.8', 'role': 1, 'status': True}
        self.assertTrue(self.ns['_is_wan_interface'](interface))

    def test_down_member_keeps_offline_not_invented_admin_disabled_state(self):
        self.interfaces[2]['status'] = 'down'
        self.assertEqual(self.collect()['links'][0]['status'], 'offline')
        self.assertTrue(self.collect()['links'][0]['ativo'])

    def test_fast_refresh_discovers_runtime_ports_missing_from_previous_cache(self):
        loader = self.ns['_load_regional_interfaces']
        self.ns['_get_gerenciador_fortigate_regional'] = lambda *args, **kwargs: {'device': {'name': 'FGT'}, 'adom': 'root'}
        client = MagicMock()
        client.proxy_monitor_interfaces.return_value = {item['name']: item for item in self.interfaces}
        old = {'links_internet_auto': [{'nome': 'WAN1', 'interface_monitorada': 'wan1',
                                       'ip': '8.8.4.4', 'provedor': 'ANTIGO', 'status': 'offline'}]}
        result = loader('REG_TESTE', old, fortimanager_client=client, include_configuration=False)
        self.assertEqual({item['name'] for item in result['interfaces']}, {item['name'] for item in self.interfaces})
        self.assertEqual(result['interfaces'][0]['ip'], '0.0.0.0')
        client.list_device_interfaces.assert_not_called()

    def test_links_page_details_and_map_share_new_canonical_ports(self):
        links = self.collect()['links']
        info = {'nome': 'REG_TESTE', 'links_internet_auto': links}
        self.ns['gerenciador_regionais'] = SimpleNamespace(recarregar_regionais=lambda: {'regionais': {'REG_TESTE': info}})
        page = self.ns['_coletar_links_multiregional']()['links']
        details = self.ns['_obter_links_detalhe_regional']('REG_TESTE', info)
        mapped = self.ns['_mapa_links_regionais'](info)
        self.assertEqual([item['interface_monitorada'] for item in page], ['dmz', 'ha1'])
        self.assertEqual([item['interface_monitorada'] for item in details], ['dmz', 'ha1'])
        self.assertEqual([item['interface_monitorada'] for item in mapped], ['dmz', 'ha1'])

    def test_cached_map_replaces_only_links_and_preserves_other_measurements_and_cache_age(self):
        info = {'links_internet_auto': self.collect()['links']}
        self.ns['gerenciador_regionais'] = SimpleNamespace(recarregar_regionais=lambda: {'regionais': {'REG_TESTE': info}})
        self.ns['_mapa_recalcular_regionais'] = MagicMock(return_value={'links_total': 2})
        cached = {'cache_atualizado_em': '2026-11-19T10:00:00', 'regionais': [
            {'codigo': 'REG_TESTE', 'links': [{'nome': 'WAN1', 'status': 'offline'}],
             'servidores': [{'status': 'online', 'ultima_verificacao': 'old'}], 'aps': [{'status': 'offline'}]},
            {'codigo': 'REG_OUTRA', 'links': [{'nome': 'ORIGINAL'}]}]}
        source = MagicMock()
        source.read_text.return_value = json.dumps(cached)
        self.ns['_MAPA_CACHE_FILE'] = source
        result, age = self.ns['_mapa_carregar_cache']()
        self.assertGreater(age, 0)
        self.assertEqual(result['cache_atualizado_em'], cached['cache_atualizado_em'])
        self.assertEqual(result['regionais'][0]['servidores'], cached['regionais'][0]['servidores'])
        self.assertEqual(result['regionais'][0]['aps'], cached['regionais'][0]['aps'])
        self.assertEqual(result['regionais'][1], cached['regionais'][1])
        self.assertEqual([link['interface_monitorada'] for link in result['regionais'][0]['links']], ['dmz', 'ha1'])
        source.write_text.assert_not_called()

    def test_real_map_totals_and_alerts_drop_removed_wans(self):
        info = {'links_internet_auto': self.collect()['links']}
        self.ns['gerenciador_regionais'] = SimpleNamespace(recarregar_regionais=lambda: {'regionais': {'REG_TESTE': info}})
        regional = {key: [] for key in ('servidores', 'switches', 'links', 'aps', 'vpns', 'firewalls', 'admins', 'redes_wifi')}
        regional.update(codigo='REG_TESTE', totais={}, links=[{'nome': 'WAN1', 'status': 'offline'}])
        cached = {'regionais': [regional]}
        self.ns['_mapa_sincronizar_links_payload'](cached)
        self.assertEqual(cached['resumo']['links_offline'], 0)
        self.assertEqual(cached['resumo']['links_online'], 2)
        self.assertEqual(regional['totais']['links_offline'], 0)
        self.assertFalse(any(alert['tipo'] == 'links' for alert in regional['alertas']))

    def test_canonical_empty_list_removes_stale_map_links_not_other_regions(self):
        self.ns['gerenciador_regionais'] = SimpleNamespace(recarregar_regionais=lambda: {'regionais': {'REG_TESTE': {'links_internet_auto': []}}})
        self.ns['_mapa_recalcular_regionais'] = MagicMock(return_value={})
        cached = {'regionais': [{'codigo': 'REG_TESTE', 'links': [{'nome': 'OLD'}]}]}
        self.ns['_mapa_sincronizar_links_payload'](cached)
        self.assertEqual(cached['regionais'][0]['links'], [])

    def test_saved_inactive_state_remains_inactive_not_offline(self):
        links = self.collect()['links']
        links[0].update(status='inativo', ativo=False)
        mapped = self.ns['_mapa_links_regionais']({'links_internet_auto': links})
        self.assertEqual(mapped[0]['status'], 'inativo')
        self.assertFalse(mapped[0]['ativo'])


if __name__ == '__main__':
    unittest.main()
