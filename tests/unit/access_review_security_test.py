"""Controles reais do Sentinel com dependencias operacionais isoladas."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from queue import Full
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request, send_file, current_app
from flask_login import LoginManager, UserMixin, current_user, login_required
from security_hardening import configure_security
from services.access_review_v1.automation.src.access_review_credentials import load_credentials
from services.access_review_v1.persistence import JobStore
from services.access_review_v1.queue import AccessReviewStorageError
from services.access_review_v1.process_guard import ProcessGuard
from services.access_review_v1.runner import _child_environment
from services.access_review_v1.settings import configuration_issues
from services.access_review_v1.setup import initialize

ROOT = Path(__file__).parents[2]


def extract(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
             or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)


class Identity(UserMixin):
    def __init__(self, groups):
        self.id = 'same-owner'
        self.groups = groups


class AccessReviewHttpSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.environment = patch.dict(os.environ, {'SECRET_KEY': 'synthetic-test-key', 'SENTINEL_TRUSTED_HOSTS': ''})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        manager = LoginManager(self.app)
        self.user = Identity(['SENTINEL_ADMINISTRATIVE_OU'])
        manager.user_loader(lambda _id: self.user)
        configure_security(self.app, Path(self.temp.name))
        self.enqueue = Mock(return_value=1)
        self.queue = Mock()
        self.queue.root = Path(self.temp.name)
        self.job = {'id':'job-1', 'kind':'revisao_acessos', 'owner':'same-owner', 'status':'running',
                    'meta':{'_persisted':True, 'events':[{'message':'Linux iniciada'}]},
                    'result':{'private_path':'MUST_NOT_REACH_BROWSER'}}
        namespace = dict(app=self.app, jsonify=jsonify, request=request, current_user=current_user,
                         send_file=send_file, current_app=current_app,
                         login_required=login_required, re=re, unicodedata=unicodedata,
                         Full=Full, AccessReviewStorageError=AccessReviewStorageError, render_template=lambda *a, **k: jsonify(success=True),
                         access_review_queue=self.queue, load_access_review_notifications=Mock(return_value=[]),
                         access_review_runner_status=Mock(return_value={'available':True, 'issues':[]}),
                         _current_user_groups=lambda:self.user.groups, _get_background_job=lambda _id:self.job,
                         _create_background_job=Mock(return_value='job-1'), _update_background_job=Mock(),
                         _enqueue_access_review=self.enqueue, _append_background_job_event=Mock(),
                         _fail_background_job=Mock(), _run_access_review_job=Mock(), _restore_access_review_job=Mock())
        extract(ROOT / 'regional_access.py', {'CORPORATE_GROUP','ADMINISTRATIVE_OU_MARKER','ACCESS_ADMIN_GROUPS',
                'OPERATOR_GROUPS','normalize_group_name','can_operate_sentinel'}, namespace)
        extract(ROOT / 'web_config.py', {'_forbidden_response','_OPERATOR_ONLY_ENDPOINTS',
                '_SELF_SERVICE_UNSAFE_ENDPOINTS','_REGIONAL_OPERATION_ENDPOINTS','enforce_operation_permissions',
                'revisao_acessos','api_executar_revisao_acessos','api_interromper_revisao_acessos','api_download_revisao_acessos','api_documentos_revisao_acessos','api_logs_revisao_acessos','api_background_job_status'}, namespace)
        self.client = self.app.test_client()

    def login(self, groups=None):
        self.user.groups = groups if groups is not None else ['SENTINEL_ADMINISTRATIVE_OU']
        with self.client.session_transaction() as session:
            session['_user_id'] = 'same-owner'
            session['_fresh'] = True
            session['_csrf_token'] = 'synthetic-csrf'

    def submit(self, csrf=True):
        return self.client.post('/api/revisao-acessos/executions',
            json={'mode':'completa','audits':['linux']}, headers={'X-CSRF-Token':'synthetic-csrf'} if csrf else {})

    def test_anonymous_cannot_execute_or_read_jobs(self):
        self.assertEqual(self.submit().status_code, 401)
        self.assertEqual(self.client.get('/api/background-jobs/job-1').status_code, 401)
        self.enqueue.assert_not_called()

    def test_regional_user_cannot_open_page_or_execute(self):
        self.login(['GGS_SUPORTE_BAHIA'])
        self.assertEqual(self.client.get('/revisao-acessos').status_code, 403)
        self.assertEqual(self.submit().status_code, 403)
        self.queue.start.assert_not_called()
        self.enqueue.assert_not_called()

    def test_owner_losing_operator_role_cannot_read_prior_job(self):
        self.login(['GGS_SUPORTE_BAHIA'])
        self.assertEqual(self.client.get('/api/background-jobs/job-1').status_code, 404)

    def test_operator_requires_csrf_and_receives_security_headers(self):
        self.login()
        self.assertEqual(self.submit(csrf=False).status_code, 400)
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_operator_job_response_is_minimal(self):
        self.login()
        response = self.client.get('/api/background-jobs/job-1')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'MUST_NOT_REACH_BROWSER', response.data)
        self.assertNotIn(b'_persisted', response.data)
        self.assertNotIn('owner', response.get_json()['job'])

    def test_cancel_requires_operator_and_csrf_and_marks_only_requested_execution(self):
        from services.access_review_v1.runner import cancellation_path
        job_id = '550e8400-e29b-41d4-a716-446655440000'
        self.job['id'] = job_id
        url = f'/api/revisao-acessos/executions/{job_id}/cancel'
        self.assertEqual(self.client.post(url).status_code, 401)
        self.login(['GGS_SUPORTE_BAHIA'])
        self.assertEqual(self.client.post(url, headers={'X-CSRF-Token':'synthetic-csrf'}).status_code, 403)
        self.login()
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(self.client.post(url, headers={'X-CSRF-Token':'synthetic-csrf'}).status_code, 202)
        self.assertTrue(cancellation_path(self.queue.root, job_id).exists())

    def test_document_export_requires_operator(self):
        with patch('services.access_review_v1.documents.build_documents_zip', side_effect=FileNotFoundError) as build:
            url = '/api/revisao-acessos/documents.zip?execution_id=550e8400-e29b-41d4-a716-446655440000'
            self.assertEqual(self.client.get(url).status_code, 401)
            self.login(['GGS_SUPORTE_BAHIA'])
            self.assertEqual(self.client.get(url).status_code, 403)
            build.assert_not_called()
            self.login()
            self.assertEqual(self.client.get(url).status_code, 404)
            build.assert_called_once()

    def test_recent_logs_refresh_is_operator_only(self):
        url = '/api/revisao-acessos/logs'
        self.assertEqual(self.client.get(url).status_code, 401)
        self.login(['GGS_SUPORTE_BAHIA'])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'success': True, 'logs': []})
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_operator_download_receives_actual_zip_attachment(self):
        from io import BytesIO
        from zipfile import ZipFile
        archive = BytesIO()
        with ZipFile(archive, 'w') as bundle:
            bundle.writestr('ADManager/Revisao-admanager-20261020-120834-859.docx', b'synthetic-final')
        archive.seek(0)
        self.login()
        execution_id = '550e8400-e29b-41d4-a716-446655440000'
        with patch('services.access_review_v1.documents.build_documents_zip', return_value=archive) as build:
            response = self.client.get(f'/api/revisao-acessos/documents.zip?execution_id={execution_id}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/zip')
            self.assertIn('attachment', response.headers['Content-Disposition'])
            with ZipFile(BytesIO(response.data)) as bundle:
                self.assertEqual(len(bundle.namelist()), 1)
            build.assert_called_once_with(execution_id=execution_id)
            response.close()


class AccessReviewLocalSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        initialize(self.root)

    def test_only_references_are_accepted_and_vault_errors_are_generic(self):
        manifest = self.root / 'credentials' / 'credentials.json'
        vault = Mock()
        vault.get_many.return_value = {'access-review/zabbix/password':'synthetic-value'}
        result = load_credentials(manifest, ['ZABBIX_SENHA'], store=vault)
        self.assertEqual(result['ZABBIX_SENHA'], 'synthetic-value')
        manifest.write_text('{"ZABBIX_SENHA":"DO_NOT_EXPOSE"}')
        with self.assertRaises(ValueError) as error:
            load_credentials(manifest, ['ZABBIX_SENHA'], store=vault)
        self.assertNotIn('DO_NOT_EXPOSE', str(error.exception))

    def test_child_does_not_inherit_other_service_secrets(self):
        with patch.dict(os.environ, {'SENTINEL_N8N_HMAC_SECRET':'DO_NOT_PASS','SECRET_KEY':'DO_NOT_PASS'}):
            environment = _child_environment(self.root)
        self.assertNotIn('SENTINEL_N8N_HMAC_SECRET', environment)
        self.assertNotIn('SECRET_KEY', environment)

    def test_http_and_embedded_url_credentials_require_rejection(self):
        from services.access_review_v1.settings import MODELS
        (self.root / 'modelos' / MODELS['linux']).touch()
        config = self.root / 'config' / 'linux.json'
        values = {'zabbix_url':'http://example.invalid','grafana_url':'https://example.invalid'}
        config.write_text(json.dumps(values))
        self.assertTrue(configuration_issues(self.root, ['linux']))
        values['allow_http'] = True
        config.write_text(json.dumps(values))
        self.assertEqual(configuration_issues(self.root, ['linux']), [])
        values['zabbix_url'] = 'https://user:secret@example.invalid'
        config.write_text(json.dumps(values))
        self.assertTrue(configuration_issues(self.root, ['linux']))

    def test_admanager_example_limits_the_http_exception_to_its_area(self):
        example = json.loads((ROOT / 'services' / 'access_review_v1' / 'config' / 'admanager.example.json').read_text())
        linux = json.loads((ROOT / 'services' / 'access_review_v1' / 'config' / 'linux.example.json').read_text())
        firewalls = json.loads((ROOT / 'services' / 'access_review_v1' / 'config' / 'firewalls.example.json').read_text())
        self.assertIs(example['allow_http'], True)
        self.assertIs(linux['allow_http'], False)
        self.assertIs(firewalls['allow_http'], False)

    def test_queue_limit_is_atomic_between_independent_stores(self):
        def attempt(index):
            job = {'id':str(index),'created_at':time.time(),'status':'queued'}
            try:
                JobStore(self.root).enqueue(job, limit=1)
                return True
            except Full:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            accepted = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(accepted), 1)

    @unittest.skipUnless(os.name == 'nt', 'Protecao nativa do Windows')
    def test_windows_guard_terminates_process_without_touching_services(self):
        process = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            guard = ProcessGuard(process)
            guard.close()
            process.wait(timeout=5)
            self.assertIsNotNone(process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    @unittest.skipUnless(os.name == 'nt', 'Protecao nativa do Windows')
    def test_windows_guard_terminates_descendant(self):
        import psutil
        script = ('import subprocess,sys,time; '
                  'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]); '
                  'print(p.pid,flush=True);time.sleep(30)')
        process = subprocess.Popen([sys.executable,'-c',script], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)
        child = None
        try:
            guard = ProcessGuard(process)
            child_pid = int(process.stdout.readline().strip())
            child = psutil.Process(child_pid)
            guard.close()
            process.wait(timeout=5)
            child.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout:
                process.stdout.close()
            if child and child.is_running():
                child.kill()


if __name__ == '__main__':
    unittest.main()
