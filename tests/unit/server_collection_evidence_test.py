"""Connectivity collection evidence with mocked ping, no app/credentials/network."""

import ast
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import vm_manager
from scripts.database import audit_server_sources as audit
from services import server_connectivity


ROOT = Path(__file__).resolve().parents[2]
AT = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)


class ServerCollectionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'_mapa_status_servidor_tempo_real', '_mapa_servidor_tempo_real'}
        cls.code = compile(ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                                           and node.name in names], type_ignores=[]), 'isolated-server', 'exec')

    def setUp(self):
        clock = patch.object(vm_manager, 'datetime', wraps=datetime)
        self.clock = clock.start()
        self.clock.now.return_value = AT
        self.addCleanup(clock.stop)
        ping = patch.object(vm_manager.subprocess, 'run')
        self.ping = ping.start()
        self.addCleanup(ping.stop)
        self.ns = {'datetime': datetime, '_mapa_status': lambda value: value or 'unknown',
                   'verificar_vm_online': vm_manager.verificar_vm_online, 'current_app': MagicMock()}
        exec(self.code, self.ns)
        self.ns['server_connectivity'] = server_connectivity
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = patch.object(server_connectivity, 'ROOT', Path(temporary.name))
        root.start()
        self.addCleanup(root.stop)
        self.record = {'id': 'PRIVATE', 'ip': '192.0.2.1', 'status': 'offline', 'funcao': 'PRIVATE',
                       'ultima_verificacao': '2026-11-18T10:00:00', 'coletado_em': 'OLD',
                       'coleta_status_confirmada': True}

    def project_after_collection(self, record):
        server_connectivity.collect(record['ip'])
        return self.ns['_mapa_servidor_tempo_real'](record)

    def ping_result(self, output):
        return SimpleNamespace(stdout=output, returncode=0)

    def probe(self, output):
        self.ping.return_value = self.ping_result(output)
        evidence = {}
        with redirect_stdout(StringIO()):
            result = vm_manager.verificar_vm_online('192.0.2.1', evidencia=evidence)
        return result, evidence

    def test_positive_response_records_utc_time_and_one_attempt(self):
        result, evidence = self.probe('Reply from 192.0.2.1: bytes=32 time=1ms TTL=64')
        self.assertTrue(result)
        self.assertTrue(evidence['coleta_status_confirmada'])
        self.assertEqual(evidence['coletado_em'], AT.isoformat())
        self.assertEqual(evidence['coleta_status_origem'], 'icmp_ping')
        self.ping.assert_called_once()
        self.assertEqual(self.ping.call_args.args[0], ['ping', '-n', '1', '-w', '3000', '192.0.2.1'])

    def test_three_negative_responses_confirm_failed_reachability_not_hardware_state(self):
        for output in ('Request timed out.', 'Esgotado o tempo limite do pedido.', 'Destination host unreachable.', '100% de perda'):
            with self.subTest(output=output):
                self.ping.reset_mock()
                result, evidence = self.probe(output)
                self.assertFalse(result)
                self.assertTrue(evidence['coleta_status_confirmada'])
                self.assertEqual(evidence['coletado_em'], AT.isoformat())
                self.assertEqual(self.ping.call_count, 3)

    def test_unrecognized_output_never_gets_measurement_clock(self):
        result, evidence = self.probe('PRIVATE unknown response')
        self.assertFalse(result)
        self.assertFalse(evidence['coleta_status_confirmada'])
        self.assertIsNone(evidence['coletado_em'])
        self.assertEqual(evidence['erro_coleta_codigo'], 'resposta_ping_nao_reconhecida')
        self.assertNotIn('PRIVATE', repr(evidence))

    def test_exception_is_not_confirmed_offline_and_legacy_still_returns_false(self):
        self.ping.side_effect = OSError('SECRET_PRIVATE')
        evidence = {}
        with redirect_stdout(StringIO()):
            self.assertFalse(vm_manager.verificar_vm_online('192.0.2.1', evidencia=evidence))
            self.assertFalse(vm_manager.verificar_vm_online('192.0.2.1'))
        self.assertFalse(evidence['coleta_status_confirmada'])
        self.assertIsNone(evidence['coletado_em'])
        self.assertNotIn('SECRET', repr(evidence))

    def test_mixed_unknown_and_negative_responses_do_not_confirm_offline(self):
        self.ping.side_effect = [self.ping_result('unknown'), self.ping_result('Request timed out.'), self.ping_result('Request timed out.')]
        evidence = {}
        with redirect_stdout(StringIO()):
            self.assertFalse(vm_manager.verificar_vm_online('192.0.2.1', evidencia=evidence))
        self.assertFalse(evidence['coleta_status_confirmada'])

    def test_legacy_positive_bool_contract_and_retry_count_unchanged(self):
        self.ping.side_effect = [self.ping_result('Request timed out.'), self.ping_result('TTL=64')]
        with redirect_stdout(StringIO()):
            self.assertIs(vm_manager.verificar_vm_online('192.0.2.1'), True)
        self.assertEqual(self.ping.call_count, 2)

    def test_map_projection_sets_real_check_clock_without_mutating_catalog(self):
        original = dict(self.record)
        self.ping.return_value = self.ping_result('TTL=64')
        with redirect_stdout(StringIO()):
            item = self.project_after_collection(self.record)
        self.assertEqual(self.record, original)
        self.assertEqual(item['status'], 'online')
        self.assertEqual(datetime.fromisoformat(item['ultima_verificacao']), AT)
        self.assertEqual(item['coletado_em'], AT.isoformat())
        self.assertTrue(item['coleta_status_confirmada'])
        self.assertEqual(item['descricao'], self.record['funcao'])
        self.assertIsNone(item['erro'])
        self.assertNotIn('hardware', item)

    def test_execution_failure_keeps_previous_state_and_clock_and_clears_old_evidence(self):
        self.record['status'] = 'online'
        self.ping.side_effect = OSError('SECRET')
        with redirect_stdout(StringIO()):
            item = self.project_after_collection(self.record)
        self.assertEqual(item['status'], 'online')
        self.assertEqual(item['ultima_verificacao'], self.record['ultima_verificacao'])
        self.assertFalse(item['coleta_status_confirmada'])
        self.assertIsNone(item['coletado_em'])
        self.assertIsNone(item['tempo_resposta'])
        self.assertEqual(item['erro_coleta_codigo'], 'erro_execucao_ping')
        self.assertNotIn('SECRET', item['erro'])

    def test_missing_ip_never_invokes_probe_or_promotes_old_timestamp(self):
        self.record['ip'] = ''
        item = self.ns['_mapa_servidor_tempo_real'](self.record)
        self.ping.assert_not_called()
        self.assertEqual(item['ultima_verificacao'], self.record['ultima_verificacao'])
        self.assertNotIn('erro_coleta_codigo', item)

    def test_confirmed_negative_response_sets_offline_with_current_clock(self):
        self.record['status'] = 'online'
        self.ping.return_value = self.ping_result('Request timed out.')
        with redirect_stdout(StringIO()):
            item = self.project_after_collection(self.record)
        self.assertEqual(item['status'], 'offline')
        self.assertTrue(item['coleta_status_confirmada'])
        self.assertEqual(datetime.fromisoformat(item['ultima_verificacao']), AT)

    def test_audit_reports_confirmed_marker_and_clock_without_identifiers(self):
        self.ping.return_value = self.ping_result('TTL=64')
        with redirect_stdout(StringIO()):
            item = self.project_after_collection(self.record)
        report = audit.audit_records([('PRIVATE', item)])
        self.assertEqual(report['horarios_coleta_explicita'], {'com_fuso': 1})
        self.assertEqual(report['tipos_campos_fora_da_projecao_sql']['coleta_status_confirmada'], {'booleano_true': 1})
        self.assertNotIn('PRIVATE', repr(report))


if __name__ == '__main__':
    unittest.main()
