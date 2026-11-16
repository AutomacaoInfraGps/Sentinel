"""Execute production collector methods with isolated SSH/FM transports."""

import ast
from datetime import datetime, timezone
from pathlib import Path
import re
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]


class VPNCollectionContextTest(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / 'gerenciar_fortigate.py').read_text(encoding='utf-8-sig'))
        helper_names = {'_parse_vpn_system_context', '_parse_vpn_phase1_comments'}
        nodes = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in helper_names]
        cls = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == 'GerenciadorFortigate')
        methods = {'obter_vpn_ipsec', 'obter_vpn_ipsec_fortimanager', '_nomes_vpn_ativas'}
        cls.body = [node for node in cls.body
                    if isinstance(node, ast.FunctionDef) and node.name in methods]
        nodes.append(cls)
        self.ssh = MagicMock()
        self.paramiko = MagicMock()
        self.paramiko.SSHClient.return_value = self.ssh
        self.client = MagicMock()
        self.client.__enter__.return_value = self.client
        self.namespace = {'datetime': datetime, 'timezone': timezone, 're': re,
                          'paramiko': self.paramiko, 'ENV_CONFIG': {},
                          'FortiManagerClient': MagicMock(return_value=self.client)}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'gerenciar_fortigate.py', 'exec'),
             self.namespace)
        self.manager = self.namespace['GerenciadorFortigate']()
        self.manager.host = '192.0.2.1'
        self.manager.username = 'TEST_USER'
        self.manager.password = 'TEST_PASSWORD'
        self.manager._obter_comentarios_vpn_fortimanager = MagicMock(return_value={})
        self.outputs = {
            'get system status': b'Serial-Number: FGT_TEST\nHostname: HUB\nCurrent virtual domain: tenant_a\n',
            'get vpn ipsec tunnel summary': b"'T1' selectors(total,up): 1/1\n'T2' selectors(total,up): 1/0",
            'show vpn ipsec phase1-interface': b'edit "T1"\nset comments "Regional A"\nnext',
        }
        self.ssh.exec_command.side_effect = self.command

    def command(self, command, **kwargs):
        value = self.outputs[command]
        if isinstance(value, Exception):
            raise value
        stdout = MagicMock()
        stdout.read.return_value = value
        return MagicMock(), stdout, MagicMock()

    def collect(self):
        with patch('builtins.print'):
            return self.manager.obter_vpn_ipsec()

    def configure_fm(self):
        self.namespace['ENV_CONFIG'] = {'fortimanager': {
            'host': 'fmg.example.test', 'adom': 'ADOM_A', 'vpn_hub_device': 'HUB_A'}}
        self.client.get_vpn_phase1_interfaces.return_value = [
            {'name': 'T1', 'comments': 'A'}, {'name': 'T2'}]
        self.client.proxy_monitor_vpn_ipsec.return_value = {'results': [{'name': 'T1'}]}

    def test_ssh_context_is_from_same_session_and_statuses_unchanged(self):
        result = self.collect()
        self.assertTrue(result['success'])
        self.assertEqual([vpn['status'] for vpn in result['vpns']], ['up', 'down'])
        for vpn in result['vpns']:
            self.assertEqual(vpn['device'], 'HUB')
            self.assertEqual(vpn['firewall_serial'], 'FGT_TEST')
            self.assertEqual(vpn['vdom'], 'tenant_a')
            self.assertEqual(vpn['vpn_source'], 'fortigate_ssh')
            self.assertEqual(vpn['device_namespace'], 'fortigate_ssh:192.0.2.1')
            self.assertIsNotNone(datetime.fromisoformat(vpn['coletado_em']).utcoffset())
            self.assertRegex(vpn['ultima_verificacao'], r'^\d\d:\d\d:\d\d$')
            self.assertNotIn('TEST_PASSWORD', str(vpn))
            self.assertNotIn('TEST_USER', str(vpn))
        self.ssh.close.assert_called_once()

    def test_metadata_permission_failure_does_not_fail_collection_or_invent_root(self):
        self.outputs['get system status'] = PermissionError('PRIVATE_ERROR')
        result = self.collect()
        self.assertTrue(result['success'])
        for vpn in result['vpns']:
            self.assertNotIn('vdom', vpn)
            self.assertNotIn('device', vpn)
            self.assertNotIn('PRIVATE_ERROR', str(vpn))

    def test_conflicting_or_global_context_is_not_an_identity(self):
        parse = self.namespace['_parse_vpn_system_context']
        self.assertEqual(parse('Current virtual domain: global\n'), {})
        self.assertNotIn('vdom', parse('Current virtual domain: root\nCurrent virtual domain: other\n'))
        self.assertEqual(parse('Permission denied\nPassword: PRIVATE\n'), {})

    def test_system_context_accepts_cli_line_endings_and_terminal_colors(self):
        parse = self.namespace['_parse_vpn_system_context']
        lines = ['Version: FortiGate-100F v7.4.13', 'Serial-Number: FGT_TEST',
                 'Hostname: HUB_TEST', 'Current virtual domain: root',
                 'Virtual domain configuration: disable', 'Current HA mode: standalone']
        for newline in ('\n', '\r\n', '\r', '\r\r\n'):
            with self.subTest(newline=repr(newline)):
                text = newline.join(lines)
                self.assertEqual(parse(text), {'firewall_serial': 'FGT_TEST',
                                              'device': 'HUB_TEST', 'vdom': 'root'})
                self.assertEqual(parse('\x1b[32m' + text + '\x1b[0m'), parse(text))

    def test_vdom_disabled_alone_does_not_imply_root(self):
        parse = self.namespace['_parse_vpn_system_context']
        self.assertEqual(parse('Virtual domain configuration: disable\r'), {})

    def test_summary_failure_still_closes_connection(self):
        self.outputs['get vpn ipsec tunnel summary'] = RuntimeError('failure')
        self.assertFalse(self.collect()['success'])
        self.ssh.close.assert_called_once()

    def test_fm_records_exact_existing_request_context(self):
        self.configure_fm()
        result = self.manager.obter_vpn_ipsec_fortimanager()
        self.assertTrue(result['success'])
        self.client.get_vpn_phase1_interfaces.assert_called_once_with('HUB_A', vdom='root')
        self.client.proxy_monitor_vpn_ipsec.assert_called_once_with('ADOM_A', 'HUB_A', vdom='root')
        self.assertEqual([vpn['status'] for vpn in result['vpns']], ['up', 'down'])
        for vpn in result['vpns']:
            self.assertEqual(vpn['device'], 'HUB_A')
            self.assertEqual(vpn['vdom'], 'root')
            self.assertEqual(vpn['device_namespace'], 'fortimanager:fmg.example.test:ADOM_A')
            self.assertEqual(vpn['vpn_source'], 'fortimanager_proxy')
            self.assertNotIn('firewall_serial', vpn)
            self.assertIsNotNone(datetime.fromisoformat(vpn['coletado_em']).utcoffset())

    def test_fm_missing_hub_still_fails_closed(self):
        self.configure_fm()
        self.namespace['ENV_CONFIG']['fortimanager'].pop('vpn_hub_device')
        self.client.list_devices.return_value = {'result': [{'data': []}]}
        self.assertFalse(self.manager.obter_vpn_ipsec_fortimanager()['success'])
        self.client.get_vpn_phase1_interfaces.assert_not_called()

    def test_web_preparation_keeps_metadata_without_changing_regional_scope(self):
        tree = ast.parse((ROOT / 'web_config.py').read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_prepare_vpn_operational_records')
        raw = self.collect()['vpns']
        namespace = {'datetime': datetime,
                     '_carregar_indice_regionais_vpn': lambda: [{'chave': 'REG_A'}],
                     '_agrupar_vpns_por_regional': lambda *args: {
                         'vpns_por_regional': {'REG_A': {'tunels': raw}}}}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'web_config.py', 'exec'), namespace)
        records = namespace['_prepare_vpn_operational_records'](raw)
        self.assertEqual([r['status'] for r in records], ['online', 'offline'])
        for record in records:
            self.assertEqual(record['regional'], 'REG_A')
            self.assertEqual(record['vdom'], 'tenant_a')
            self.assertEqual(record['coletado_em'], raw[0]['coletado_em'])


if __name__ == '__main__':
    unittest.main()
