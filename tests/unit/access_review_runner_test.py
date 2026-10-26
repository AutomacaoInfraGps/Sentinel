import json
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import time
import unittest
from unittest.mock import patch
import zipfile

from services.access_review_v1.runner import (
    AccessReviewRunnerError, _drain_details, _wait_with_progress, _windows_failure_message, run_access_review, runner_status,
)
from services.access_review_v1.setup import initialize
from services.access_review_v1.settings import EVIDENCE_SLOTS, MODELS
from services.access_review_v1.notifications import load_access_review_notifications
from services.access_review_v1.queue import AccessReviewQueue


def document(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
        archive.writestr('word/_rels/document.xml.rels', '<Relationships/>')
        archive.writestr('padding', b'x' * 11000)


class AccessReviewRunnerTest(unittest.TestCase):
    def test_cancel_terminates_process_tree(self):
        from unittest.mock import Mock
        process = Mock()
        with patch('services.access_review_v1.runner._terminate_tree') as terminate:
            with self.assertRaisesRegex(AccessReviewRunnerError, 'interrompida'):
                _wait_with_progress(process, 60, Path('synthetic'), None, cancelled=lambda: True)
        terminate.assert_called_once_with(process)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize(self.root)
        config = self.root / 'config' / 'auditorias.json'
        values = json.loads(config.read_text())
        values.update(tentativas=1, intervalo_segundos=0)
        config.write_text(json.dumps(values))
        for model in MODELS.values():
            document(self.root / 'modelos' / model)
        for area in ('linux', 'admanager', 'firewalls'):
            folder = {'linux':'Linux', 'admanager':'ADManager', 'firewalls':'Firewalls'}[area]
            evidence = self.root / 'dados' / 'evidencias' / folder
            evidence.mkdir(parents=True, exist_ok=True)
            for slot in EVIDENCE_SLOTS[area]:
                (evidence / f'{slot}.png').write_bytes(b'synthetic-image')
        firewall_result = self.root / 'dados' / 'execucoes' / 'Firewalls' / 'Resultado-AuditoriaFirewalls.json'
        firewall_result.parent.mkdir(parents=True, exist_ok=True)
        firewall_result.write_text('{"regionais": []}')

    def tearDown(self):
        self.temp.cleanup()

    def test_setup_preserves_local_configuration(self):
        target = self.root / 'config' / 'linux.json'
        target.write_text('{"zabbix_url":"custom"}')
        initialize(self.root)
        self.assertEqual(json.loads(target.read_text())['zabbix_url'], 'custom')

    def test_missing_configuration_is_friendly_and_does_not_expose_values(self):
        status = runner_status(root=self.root, selected=['linux'])
        self.assertFalse(status['available'])
        self.assertIn('config/linux.json', str(status['issues']))
        self.assertNotIn(str(self.root), str(status))

    def test_remount_is_enabled_only_with_preserved_evidence(self):
        status = runner_status(root=self.root, selected=['admanager'], mode='somente_montagem')
        self.assertTrue(status['available'])
        (self.root / 'dados' / 'evidencias' / 'ADManager' / 'p003_1.png').unlink()
        status = runner_status(root=self.root, selected=['admanager'], mode='somente_montagem')
        self.assertFalse(status['available'])
        self.assertIn('revisão completa', str(status['issues']).lower())

    def test_internal_scripts_run_sequentially_and_publish_directly(self):
        commands = []
        events = []
        root = self.root
        class Process:
            def __init__(self, area):
                self.area = area
            def wait(self, timeout):
                folder = {'linux':'Linux','firewalls':'Firewalls'}[self.area]
                document(root / 'dados' / 'execucoes' / folder / f'Revisao-{self.area}-20261020-123456-789.docx')
                return 0
        def spawn(command, **options):
            commands.append(command)
            self.assertEqual(options['env']['SENTINEL_ACCESS_REVIEW_HOME'], str(root.resolve()))
            self.assertNotIn('Automacao-Auditoria', command[-1])
            return Process(command[command.index('-Area') + 1])
        result = run_access_review('somente_montagem', audit_ids=['linux','firewalls'], root=root,
                                   popen_factory=spawn, event=lambda *e: events.append(e))
        self.assertTrue(result['success'])
        self.assertEqual(len(commands), 2)
        self.assertEqual([e[0] for e in events if e[1] == 'completed'], ['linux','firewalls'])
        alerts = load_access_review_notifications(authorized=True, path=root / 'executions.sqlite3')
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['severity'], 'success')

    def test_progress_uses_real_stage_file_and_never_moves_backwards(self):
        values = []
        root = self.root
        class Process:
            def poll(self):
                return 0
        def spawn(command, **options):
            progress_file = Path(options['env']['SENTINEL_ACCESS_REVIEW_PROGRESS_FILE'])
            progress_file.write_text('{"stage":"assembled","percent":96}')
            document(root / 'dados' / 'execucoes' / 'Linux' / 'Revisao-linux-20261020-123456-789.docx')
            return Process()
        result = run_access_review(
            'somente_montagem', audit_ids=['linux'], root=root, popen_factory=spawn,
            progress=lambda percent, message: values.append((percent, message)),
        )
        self.assertTrue(result['success'])
        self.assertEqual([value[0] for value in values], sorted(value[0] for value in values))
        self.assertTrue(any('validação' in message for _, message in values))

    def test_windows_final_failure_explains_incomplete_capture(self):
        result = self.root / 'dados' / 'execucoes' / 'ServidoresWindows' / 'Resultado-Teste-Completo.json'
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({'etapas': {
            'Server Manager': 'OK', 'Bloco inicial': 'FALHA (1)', 'Regional sintetica': 'FALHA (1)'
        }}))
        message = _windows_failure_message(self.root, 0, True)
        self.assertIn('documento chegou a ser montado', message)
        self.assertIn('bloco inicial', message)
        self.assertIn('1 seção(ões)', message)
        self.assertNotIn('Regional sintetica', message)

    def test_five_regional_failures_skip_whole_area_retry(self):
        config_path = self.root / 'config' / 'auditorias.json'
        config = json.loads(config_path.read_text())
        config['tentativas'] = 2
        config_path.write_text(json.dumps(config))
        calls = []
        class Process:
            def poll(self):
                return 1
        def spawn(command, **options):
            calls.append(command)
            Path(options['env']['SENTINEL_ACCESS_REVIEW_PROGRESS_FILE']).write_text(
                '{"stage":"windows_aborted","percent":60}')
            return Process()
        events = []
        result = run_access_review('completa', audit_ids=['windows'], root=self.root,
                                   popen_factory=spawn, event=lambda *args: events.append(args))
        self.assertFalse(result['success'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(any('cinco regionais' in event[2] for event in events))

    def test_detailed_events_keep_target_and_error_without_raw_exception(self):
        path = self.root / 'runtime' / 'synthetic.events.jsonl'
        path.write_text(json.dumps(dict(stage='Abrir janela', target='OU Exemplo',
            status='warning', error_type='TimeoutError', raw_error='SECRET_NEVER_DISPLAY')) + '\n')
        events = []
        offset = _drain_details(path, 0, lambda *args: events.append(args), 'windows')
        self.assertEqual(len(events), 1)
        self.assertIn('OU Exemplo', events[0][2])
        self.assertIn('TimeoutError', events[0][2])
        self.assertNotIn('SECRET_NEVER_DISPLAY', events[0][2])
        _drain_details(path, offset, lambda *args: events.append(args), 'windows')
        self.assertEqual(len(events), 1)

    def test_failure_continues_next_area_and_does_not_accept_old_document(self):
        root = self.root
        document(root / 'dados' / 'execucoes' / 'Linux' / 'old.docx')
        called = []
        class Process:
            def wait(self, timeout):
                return 0
        def spawn(command, **options):
            called.append(command)
            return Process()
        result = run_access_review('somente_montagem', audit_ids=['linux','firewalls'], root=root, popen_factory=spawn)
        self.assertFalse(result['success'])
        self.assertEqual(len(called), 2)
        alerts = load_access_review_notifications(authorized=True, path=root / 'executions.sqlite3')
        self.assertEqual(alerts[0]['severity'], 'critical')
        self.assertTrue((root / 'dados' / 'evidencias' / 'Linux' / 'p005_1.png').exists())

    def test_successful_batch_cleans_pngs_only_after_final_validation(self):
        root = self.root
        class Process:
            def wait(self, timeout):
                document(root / 'dados' / 'execucoes' / 'Linux' / 'Revisao-linux-20261020-123456789.docx')
                return 0
        result = run_access_review('somente_montagem', audit_ids=['linux'], root=root,
                                  popen_factory=lambda *args, **kwargs: Process())
        self.assertTrue(result['success'])
        self.assertFalse((root / 'dados' / 'evidencias' / 'Linux' / 'p005_1.png').exists())
        self.assertTrue((root / 'dados' / 'documentos' / result['execution_id'] / 'manifest.json').exists())

    def test_rejects_invalid_area(self):
        with self.assertRaises(AccessReviewRunnerError):
            run_access_review('completa', audit_ids=['../arbitrary'], root=self.root)

    def test_timeout_terminates_capture_and_records_failure(self):
        class Process:
            def wait(self, timeout):
                raise subprocess.TimeoutExpired('synthetic', timeout)
        with patch('services.access_review_v1.runner._terminate_tree') as terminate:
            result = run_access_review('somente_montagem', audit_ids=['linux'], root=self.root,
                                       popen_factory=lambda *a, **k: Process())
        self.assertFalse(result['success'])
        terminate.assert_called_once()

    def test_queue_restores_pending_and_marks_interrupted_running(self):
        queue = AccessReviewQueue(root=self.root)
        from services.access_review_v1.persistence import JobStore
        store = JobStore(self.root)
        for job_id, state in [('interrupted', 'running'), ('pending', 'queued')]:
            store.save({'id': job_id, 'status': state, 'created_at': time.time(),
                        'meta': {'mode':'completa', 'audits':['linux']}})
        done = threading.Event()
        restored = []
        queue.start(lambda *args: done.set(), restore=lambda job: restored.append(job['id']))
        self.assertTrue(done.wait(5))
        queue.close()
        self.assertEqual(restored, ['pending'])
        self.assertEqual(store.get('interrupted')['status'], 'failed')
        self.assertEqual(store.get('pending')['status'], 'completed')

    def test_queue_is_fifo_and_never_overlaps(self):
        queue = AccessReviewQueue(root=self.root)
        order = []
        active = 0
        guard = threading.Lock()
        finished = threading.Event()
        def handler(job, mode, areas):
            nonlocal active
            with guard:
                active += 1
                self.assertEqual(active, 1)
                order.append(job)
                active -= 1
            if job == '3':
                finished.set()
        for job in ('1','2','3'):
            queue.enqueue(job, 'completa', ['linux'], handler)
        self.assertTrue(finished.wait(5))
        self.assertEqual(order, ['1','2','3'])
        queue.close()


if __name__ == '__main__':
    unittest.main()
