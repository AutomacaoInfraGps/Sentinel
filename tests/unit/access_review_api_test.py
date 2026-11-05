"""Testa a rota real isolando a inicializacao operacional do web_config."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from queue import Full
from flask import Flask, jsonify, request
from services.access_review_v1.queue import AccessReviewStorageError


class AccessReviewApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.enqueue = Mock(return_value=1)
        self.status = Mock(return_value={'available': True, 'issues': []})
        namespace = {
            'app': self.app, 'login_required': lambda f: f, 'request': request, 'jsonify': jsonify,
            'Full': Full, 'AccessReviewStorageError': AccessReviewStorageError, 'access_review_runner_status': self.status,
            '_create_background_job': Mock(return_value='job-1'), '_update_background_job': Mock(),
            '_enqueue_access_review': self.enqueue, '_append_background_job_event': Mock(),
            '_fail_background_job': Mock(),
        }
        source = Path(__file__).parents[2] / 'web_config.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        route = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'api_executar_revisao_acessos')
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(source), 'exec'), namespace)
        self.client = self.app.test_client()

    def test_enqueues_selected_areas(self):
        response = self.client.post('/api/revisao-acessos/executions', json={'mode':'completa', 'audits':['linux','firewalls']})
        self.assertEqual(response.status_code, 202)
        self.enqueue.assert_called_once_with('job-1', 'completa', ['linux','firewalls'])

    def test_rejects_duplicates_and_arbitrary_names(self):
        for areas in ([], ['linux','linux'], ['arbitrary'], [123]):
            with self.subTest(areas=areas):
                response = self.client.post('/api/revisao-acessos/executions', json={'mode':'completa', 'audits':areas})
                self.assertEqual(response.status_code, 400)
        self.enqueue.assert_not_called()

    def test_regeneration_requires_original_execution_and_verified_evidence(self):
        response = self.client.post('/api/revisao-acessos/executions', json={
            'mode':'somente_montagem', 'audits':['linux']})
        self.assertEqual(response.status_code, 400)
        source = '550e8400-e29b-41d4-a716-446655440000'
        with patch('services.access_review_v1.recovery.recovery_available', return_value=False):
            response = self.client.post('/api/revisao-acessos/executions', json={
                'mode':'somente_montagem', 'audits':['linux'], 'source_execution_id': source})
        self.assertEqual(response.status_code, 409)
        self.enqueue.assert_not_called()
        with patch('services.access_review_v1.recovery.recovery_available', return_value=True):
            response = self.client.post('/api/revisao-acessos/executions', json={
                'mode':'somente_montagem', 'audits':['linux'], 'source_execution_id': source})
        self.assertEqual(response.status_code, 202)
        self.enqueue.assert_called_once_with('job-1', 'somente_montagem', ['linux'])

    def test_returns_configuration_issue_without_starting(self):
        self.status.return_value = {
            'available': False,
            'issues': ['Linux precisa de configuração.'],
            'diagnostics': [{'code':'area_config_invalid', 'area':'linux',
                             'message':'Linux precisa de configuração.',
                             'action':'Revise config/linux.json.'}],
        }
        response = self.client.post('/api/revisao-acessos/executions', json={'mode':'completa','audits':['linux']})
        self.assertEqual(response.status_code, 503)
        self.assertIn('config/linux.json', response.get_json()['issues'][0]['action'])
        self.enqueue.assert_not_called()

    def test_queue_limit_is_friendly(self):
        self.enqueue.side_effect = Full()
        response = self.client.post('/api/revisao-acessos/executions', json={'mode':'completa','audits':['linux']})
        self.assertEqual(response.status_code, 429)

    def test_rejects_unknown_fields_and_excessive_request_size(self):
        response = self.client.post('/api/revisao-acessos/executions', json={
            'mode':'completa','audits':['linux'],'command':'arbitrary-command'})
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/revisao-acessos/executions', data=b' ' * 8193,
                                    content_type='application/json')
        self.assertEqual(response.status_code, 413)
        response = self.client.post('/api/revisao-acessos/executions',
                                    data=b'{"mode":"' + b' ' * 8193 + b'completa","audits":["linux"]}',
                                    content_type='application/json',
                                    environ_overrides={'CONTENT_LENGTH':'', 'wsgi.input_terminated':True})
        self.assertEqual(response.status_code, 413)
        self.enqueue.assert_not_called()

    def test_page_moves_document_recovery_to_execution_history(self):
        source = (Path(__file__).parents[2] / 'templates' / 'revisao_acessos.html').read_text(encoding='utf-8')
        self.assertIn('id="statusHelpButton"', source)
        self.assertNotIn('name="executionMode"', source)
        self.assertIn('Gerar documentos novamente', source)
        self.assertIn('source_execution_id:sourceId', source)
        self.assertEqual(source.count('class="review-state-legend"'), 1)
        self.assertIn('class="execution-actions"', source)
        self.assertIn('id="selectedAuditCount"', source)
        self.assertNotIn('<select id="executionMode"', source)
        self.assertNotIn('auditoria', source.casefold())
        self.assertIn('.execution-event.retry', source)
        self.assertIn('.execution-event.completed', source)


if __name__ == '__main__':
    unittest.main()
