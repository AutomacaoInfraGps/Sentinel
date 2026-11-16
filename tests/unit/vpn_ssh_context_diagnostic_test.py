import json
from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import MagicMock, patch

from scripts.database.check_vpn_ssh_context import diagnose_output, query_context, main


class VPNContextDiagnosticTest(unittest.TestCase):
    def test_root_is_observed_not_inferred_from_disabled_vdoms(self):
        result = diagnose_output('Current virtual domain: root\rVirtual domain configuration: disable')
        self.assertEqual(result['vdom'], 'root')
        self.assertEqual(result['situacao_vdom'], 'identificado')
        self.assertIsNone(diagnose_output('Virtual domain configuration: disable')['vdom'])

    def test_missing_global_invalid_and_conflict_are_distinct(self):
        for text, expected in (
            ('', 'campo_ausente'),
            ('Current virtual domain: global', 'contexto_global'),
            ('Current virtual domain: ', 'valor_vazio_ou_invalido'),
            ('Current virtual domain: N/A', 'valor_vazio_ou_invalido'),
            ('Current virtual domain: root\rCurrent virtual domain: other', 'valores_conflitantes')):
            with self.subTest(expected=expected):
                self.assertEqual(diagnose_output(text)['situacao_vdom'], expected)

    def test_never_exports_raw_response_identity_or_unknown_settings(self):
        output = 'Hostname: PRIVATE\rSerial-Number: PRIVATE\rPassword: PRIVATE\rVirtual domain configuration: PRIVATE'
        result = diagnose_output(output)
        self.assertTrue(result['hostname_presente'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_uses_one_read_only_command_without_pty_or_key_changes(self):
        ssh = MagicMock()
        stream = MagicMock()
        stream.read.return_value = b'Current virtual domain: root'
        ssh.exec_command.return_value = (None, stream, None)
        result = query_context(ssh, {'host': '192.0.2.1', 'username': 'u', 'password': 'SECRET'})
        self.assertEqual(result['vdom'], 'root')
        ssh.exec_command.assert_called_once_with('get system status', timeout=10)
        self.assertFalse(ssh.connect.call_args.kwargs['allow_agent'])
        ssh.save_host_keys.assert_not_called()
        ssh.invoke_shell.assert_not_called()
        ssh.close.assert_called_once()
        self.assertNotIn('SECRET', json.dumps(result))

    def test_closes_on_failure_or_oversized_output(self):
        for oversized in (False, True):
            ssh = MagicMock()
            if oversized:
                stream = MagicMock()
                stream.read.return_value = b'x' * 65537
                ssh.exec_command.return_value = (None, stream, None)
            else:
                ssh.connect.side_effect = RuntimeError('SECRET')
            with self.assertRaises((RuntimeError, ValueError)):
                query_context(ssh, {'host': '192.0.2.1', 'username': 'u', 'password': 'SECRET'})
            ssh.close.assert_called_once()

    def test_filtered_query_is_fixed_and_reads_only_the_vdom_line(self):
        ssh = MagicMock()
        stream = MagicMock()
        stream.read.return_value = b'Current virtual domain: root\r\n'
        ssh.exec_command.return_value = (None, stream, None)
        result = query_context(ssh, {'host': '192.0.2.1', 'username': 'u', 'password': 'SECRET'},
                               filtered_vdom=True)
        ssh.exec_command.assert_called_once_with(
            'get system status | grep "Current virtual domain"', timeout=10)
        self.assertEqual(result['vdom'], 'root')
        self.assertTrue(result['consulta_filtrada_vdom'])
        self.assertFalse(result['marcador_paginacao_detectado'])
        ssh.close.assert_called_once()

    def test_pagination_is_reported_without_exporting_raw_output(self):
        ssh = MagicMock()
        stream = MagicMock()
        stream.read.return_value = b'Hostname: PRIVATE\r\n--More--'
        ssh.exec_command.return_value = (None, stream, None)
        result = query_context(ssh, {'host': '192.0.2.1', 'username': 'u', 'password': 'SECRET'})
        self.assertTrue(result['marcador_paginacao_detectado'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_main_resolves_only_selected_credentials_and_rejects_unknown_keys(self):
        config = {'fortigate': {'SP': {'host': '192.0.2.1', 'username': 'u',
                                     'password': {'credential_ref': 'test'},
                                     'other': 'PRIVATE'}}}
        store = MagicMock()
        store.get.return_value = 'SECRET'
        ssh = MagicMock()
        stream = MagicMock()
        stream.read.return_value = b'Current virtual domain: root'
        ssh.exec_command.return_value = (None, stream, None)
        with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), \
                patch('core.environment_loader.load_environment_file', return_value=config), \
                patch('core.secret_store.JsonSecretStore', return_value=store), \
                patch('paramiko.SSHClient', return_value=ssh), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 0)
        self.assertEqual(ssh.connect.call_args.kwargs['password'], 'SECRET')
        ssh.set_missing_host_key_policy.assert_called_once()
        self.assertEqual(type(ssh.set_missing_host_key_policy.call_args.args[0]).__name__, 'RejectPolicy')
        self.assertNotIn('SECRET', output.getvalue())


if __name__ == '__main__':
    unittest.main()
