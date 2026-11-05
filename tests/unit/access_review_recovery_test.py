import json
from pathlib import Path
import tempfile
import unittest
from services.access_review_v1.recovery import preserve_evidence, prepare_recovery, recovery_available
from services.access_review_v1.runner import run_access_review
from services.access_review_v1.settings import MODELS
from services.access_review_v1.setup import initialize
from services.access_review_v1.notifications import load_access_review_notifications
from tests.unit.access_review_runner_test import document


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = '550e8400-e29b-41d4-a716-446655440000'
        self.destination = '550e8400-e29b-41d4-a716-446655440001'
        initialize(self.root)
        config = self.root / 'config' / 'auditorias.json'
        values = json.loads(config.read_text())
        values.update(tentativas=1, intervalo_segundos=0)
        config.write_text(json.dumps(values))
        (self.root / 'config' / 'admanager.json').write_text('{"admanager_url":"https://example.invalid"}')
        document(self.root / 'modelos' / MODELS['admanager'])
        self.evidence = self.root / 'dados' / 'evidencias' / 'ADManager'
        self.evidence.mkdir(parents=True)
        for name in ('p003_1.png', 'p005_1.png'):
            (self.evidence / name).write_bytes(b'synthetic-image')

    def test_snapshot_is_bound_to_execution_and_cannot_follow_changed_evidence(self):
        preserve_evidence(self.root, self.source, 'admanager')
        (self.evidence / 'p003_1.png').write_bytes(b'newer-collection')
        work = prepare_recovery(self.root, self.source, 'admanager', self.destination)
        self.assertEqual((work / 'dados/evidencias/ADManager/p003_1.png').read_bytes(), b'synthetic-image')
        self.assertFalse(recovery_available(self.root, self.destination, 'admanager'))
        snapshot = self.root / 'dados/recuperacao' / self.source / 'admanager/home/dados/evidencias/ADManager/p003_1.png'
        snapshot.write_bytes(b'different-bytes')
        self.assertFalse(recovery_available(self.root, self.source, 'admanager', verify_hash=True))

    def test_document_failure_can_be_recovered_without_new_collection(self):
        root = self.root
        class Failure:
            def wait(self, timeout):
                return 1
        def failing_spawn(command, **options):
            Path(options['env']['SENTINEL_ACCESS_REVIEW_PROGRESS_FILE'] + '.collected').touch()
            return Failure()
        result = run_access_review('completa', audit_ids=['admanager'], root=root,
                                  execution_id=self.source, popen_factory=failing_spawn)
        self.assertFalse(result['success'])
        items = load_access_review_notifications(authorized=True, path=root / 'executions.sqlite3')
        self.assertEqual(items[0]['reviews'][0]['state'], 'document')
        self.assertTrue(items[0]['reviews'][0]['can_regenerate'])
        class Success:
            def wait(self, timeout):
                return 0
        def recovery_spawn(command, **options):
            self.assertIn('-SomenteMontagem', command)
            work = Path(options['env']['SENTINEL_ACCESS_REVIEW_HOME'])
            self.assertNotEqual(work, root)
            document(work / 'dados/execucoes/ADManager/Revisao-admanager-20261020-123456-789.docx')
            return Success()
        recovered = run_access_review('somente_montagem', audit_ids=['admanager'], root=root,
            execution_id=self.destination, source_execution_id=self.source, popen_factory=recovery_spawn)
        self.assertTrue(recovered['success'])
        self.assertTrue((root / 'dados/documentos' / self.destination / 'manifest.json').exists())
        self.assertFalse(recovery_available(root, self.source, 'admanager'))

    def test_collection_failure_never_enables_regeneration(self):
        class Process:
            def wait(self, timeout):
                return 1
        run_access_review('completa', audit_ids=['admanager'], root=self.root,
            execution_id=self.source, popen_factory=lambda *args, **kwargs: Process())
        item = load_access_review_notifications(authorized=True, path=self.root / 'executions.sqlite3')[0]
        self.assertEqual(item['reviews'][0]['state'], 'collection')
        self.assertFalse(item['reviews'][0]['can_regenerate'])
