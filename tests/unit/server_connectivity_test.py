"""Shared connectivity tests without app imports, network, SQL or credentials."""

import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import sleep
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services import server_connectivity as service


class ConnectivityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = patch.object(service, 'ROOT', Path(temporary.name))
        root.start()
        self.addCleanup(root.stop)
        probe_patch = patch('vm_manager.verificar_vm_online')
        self.probe = probe_patch.start()
        self.addCleanup(probe_patch.stop)
        self.probe.side_effect = self.positive
        self.server = {'id': 'private-id', 'ip': '192.0.2.1', 'status': 'offline',
                       'senha': 'SECRET', 'ultima_verificacao': '2020-01-01T00:00:00+00:00'}

    def positive(self, ip, evidencia):
        evidencia.update(coleta_status_confirmada=True,
                         coleta_status_origem='icmp_ping', erro_coleta_codigo=None,
                         coletado_em=datetime.now(timezone.utc).isoformat())
        return True

    def test_read_never_probes_or_creates_cache(self):
        self.assertEqual(service.project(self.server), self.server)
        self.assertIsNone(service.read_observation('invalid'))
        self.probe.assert_not_called()
        self.assertEqual(list(service.ROOT.iterdir()), [])

    def test_confirmed_observation_is_shared_without_credentials_or_identity(self):
        service.collect(self.server['ip'])
        item = service.project(self.server)
        self.assertEqual(item['status'], 'online')
        self.assertTrue(item['coleta_status_confirmada'])
        self.assertFalse(item['conectividade_desatualizada'])
        self.assertEqual(self.server['status'], 'offline')
        stored = service._path(self.server['ip']).read_text()
        for secret in ('SECRET', 'private-id', '192.0.2.1'):
            self.assertNotIn(secret, stored)

    def test_repeat_click_and_checklist_share_short_lived_probe(self):
        service.collect('192.0.2.1')
        evidence = {}
        self.assertTrue(service.verificar_online('192.0.2.1', evidence))
        self.assertTrue(evidence['coleta_status_confirmada'])
        self.probe.assert_called_once()

    def test_expired_observation_is_rechecked(self):
        service.collect('192.0.2.1')
        data = service.read_observation('192.0.2.1')
        data['tentativa_em'] = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
        service._write(service._path('192.0.2.1'), data)
        service.collect('192.0.2.1')
        self.assertEqual(self.probe.call_count, 2)

    def test_simultaneous_requests_share_one_probe(self):
        def slow(ip, evidencia):
            sleep(.08)
            return self.positive(ip, evidencia)
        self.probe.side_effect = slow
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(service.collect, ['192.0.2.1'] * 3))
        self.assertEqual(results[0], results[1])
        self.probe.assert_called_once()

    def test_bounded_parallelism(self):
        guard = Lock()
        active = peak = 0
        def slow(ip, evidencia):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            sleep(.05)
            with guard:
                active -= 1
            return self.positive(ip, evidencia)
        self.probe.side_effect = slow
        jobs = [service.submit(f'192.0.2.{index}') for index in range(1, 11)]
        for job in jobs:
            job.result()
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 5)

    def test_failed_attempt_does_not_become_confirmed_offline_or_move_measurement_time(self):
        first = service.collect('192.0.2.1')
        first['tentativa_em'] = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
        service._write(service._path('192.0.2.1'), first)
        def fail(ip, evidencia):
            evidencia.update(coleta_status_confirmada=False, coletado_em=None,
                             coleta_status_origem='icmp_ping', erro_coleta_codigo='erro_execucao_ping')
            return False
        self.probe.side_effect = fail
        service.collect('192.0.2.1')
        item = service.project(self.server)
        self.assertEqual(item['status'], 'online')
        self.assertEqual(item['ultima_verificacao'], first['ultima_verificacao'])
        self.assertFalse(item['coleta_status_confirmada'])
        self.assertIsNone(item['coletado_em'])
        self.assertFalse(service.verificar_online('192.0.2.1'))

    def test_maintenance_inactive_and_newer_records_are_preserved(self):
        service.collect('192.0.2.1')
        for status in ('maintenance', 'inativo', 'disabled'):
            self.assertEqual(service.project(dict(self.server, status=status))['status'], status)
        item = dict(self.server, ultima_verificacao='2099-01-01T00:00:00+00:00')
        self.assertEqual(service.project(item), item)

    def test_ip_change_never_reuses_old_target(self):
        service.collect('192.0.2.1')
        changed = dict(self.server, ip='192.0.2.2')
        self.assertEqual(service.project(changed), changed)

    def test_corrupt_cache_is_ignored(self):
        path = service._path('192.0.2.1')
        path.write_text('[]')
        self.assertEqual(service.project(self.server), self.server)
        service.collect('192.0.2.1')
        self.assertEqual(service.project(self.server)['status'], 'online')

    def test_map_and_card_projection_read_without_probe(self):
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse((root / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'_mapa_servidor_tempo_real', '_servidor_para_exibicao'}
        code = compile(ast.Module(body=[node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[]),
                       'isolated-projection', 'exec')
        namespace = {'server_connectivity': service}
        exec(code, namespace)
        service.collect('192.0.2.1')
        self.probe.reset_mock()
        for name in names:
            item = namespace[name](self.server)
            self.assertEqual(item['status'], 'online')
        self.assertNotIn('senha', namespace['_servidor_para_exibicao'](self.server))
        self.probe.assert_not_called()

    def test_regional_buttons_share_results_without_writing_catalog(self):
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse((root / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'api_testar_todos_servidores', 'api_testar_servidor_regional', 'api_verificar_regional'}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        for node in nodes:
            node.decorator_list = []
        manager = SimpleNamespace(
            obter_regional=lambda code: {'servidores': [self.server]},
            obter_servidor=lambda code, identifier: self.server,
        )
        namespace = {'server_connectivity': service, 'gerenciador_regionais': manager,
                     'jsonify': lambda value: value}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'isolated-routes', 'exec'), namespace)
        result = namespace['api_testar_todos_servidores']('PRIVATE')
        self.assertTrue(result['success'])
        self.assertEqual(result['resumo']['online'], 1)
        single = namespace['api_testar_servidor_regional']('PRIVATE', 'private-id')
        self.assertEqual(single['timestamp'], result['resultados'][0]['timestamp'])
        self.assertTrue(namespace['api_verificar_regional']('PRIVATE')['success'])
        self.probe.assert_called_once()
        self.assertEqual(self.server['status'], 'offline')

    def test_map_overlay_preserves_other_groups_and_cache_clock(self):
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse((root / 'web_config.py').read_text(encoding='utf-8-sig'))
        names = {'_mapa_sincronizar_servidores_payload', '_mapa_servidor_tempo_real'}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        namespace = {'server_connectivity': service, '_mapa_recalcular_regionais': lambda regions: {'updated': True}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'isolated-map', 'exec'), namespace)
        service.collect('192.0.2.1')
        self.probe.reset_mock()
        payload = {'cache_atualizado_em': 'OLD', 'regionais': [
            {'codigo': 'PRIVATE', 'servidores': [self.server], 'links': [{'status': 'offline'}]},
        ]}
        namespace['_mapa_sincronizar_servidores_payload'](payload)
        self.assertEqual(payload['cache_atualizado_em'], 'OLD')
        self.assertEqual(payload['regionais'][0]['links'], [{'status': 'offline'}])
        self.assertEqual(payload['regionais'][0]['servidores'][0]['status'], 'online')
        self.probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
