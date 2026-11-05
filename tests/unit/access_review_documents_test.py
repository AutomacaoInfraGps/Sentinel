import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from filelock import FileLock, Timeout
from services.access_review_v1.documents import approve_documents, build_documents_zip, list_document_executions


class DocumentsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'dados' / 'execucoes' / 'Linux'
        self.folder.mkdir(parents=True)
        self.execution_id = '550e8400-e29b-41d4-a716-446655440000'

    def test_zip_contains_only_approved_final_document(self):
        final = self.folder / 'Revisao-linux-20261020-123456-789.docx'
        final.write_bytes(b'approved-synthetic-document')
        for name in ('teste.docx', 'parcial.docx', 'print.png', 'log.txt'):
            (self.folder / name).write_bytes(b'excluded')
        other = self.folder / 'Revisao-linux-20261019-123456789.docx'
        other.write_bytes(b'not-approved')
        approve_documents(self.root, 'linux', [final], self.execution_id)
        with build_documents_zip(self.root, execution_id=self.execution_id) as stream, ZipFile(stream) as archive:
            self.assertEqual(archive.namelist(), [f'Linux/{final.name}'])
        final.write_bytes(b'changed-after-approval')
        with build_documents_zip(self.root, execution_id=self.execution_id) as stream, ZipFile(stream) as archive:
            self.assertEqual(archive.read(f'Linux/{final.name}'), b'approved-synthetic-document')
        snapshot = self.root / 'dados' / 'documentos' / self.execution_id / 'Linux' / final.name
        snapshot.write_bytes(b'modified-snapshot')
        with self.assertRaises(ValueError):
            build_documents_zip(self.root, execution_id=self.execution_id)

    def test_download_is_blocked_while_review_is_running(self):
        with FileLock(str(self.root / 'execution.lock')):
            with self.assertRaises(Timeout):
                build_documents_zip(self.root, execution_id=self.execution_id)

    def test_zip_exports_only_selected_approved_areas(self):
        linux = self.folder / 'Revisao-linux-20261020-123456-789.docx'
        linux.write_bytes(b'linux-final')
        folder = self.root / 'dados/execucoes/ADManager'
        folder.mkdir()
        admanager = folder / 'Revisao-admanager-20261020-123456-789.docx'
        admanager.write_bytes(b'admanager-final')
        approve_documents(self.root, 'linux', [linux], self.execution_id)
        approve_documents(self.root, 'admanager', [admanager], self.execution_id)
        with build_documents_zip(self.root, execution_id=self.execution_id, audit_ids=['linux']) as stream, ZipFile(stream) as archive:
            self.assertEqual(archive.namelist(), [f'Linux/{linux.name}'])
        options = list_document_executions(self.root)[0]['area_options']
        self.assertEqual({item['id'] for item in options}, {'linux', 'admanager'})
        with self.assertRaises(FileNotFoundError):
            build_documents_zip(self.root, execution_id=self.execution_id, audit_ids=['windows'])
        for areas in ([], ['linux', 'linux'], ['../config']):
            with self.assertRaises(ValueError):
                build_documents_zip(self.root, execution_id=self.execution_id, audit_ids=areas)

    def test_unrecognized_output_never_creates_empty_approval(self):
        final = self.folder / 'partial.docx'
        final.write_bytes(b'unapproved')
        with self.assertRaises(ValueError):
            approve_documents(self.root, 'linux', [final], self.execution_id)
        self.assertFalse((self.root / 'dados' / 'documentos' / self.execution_id).exists())

    def test_separate_executions_preserve_windows_and_never_mix_documents(self):
        folder = self.root / 'dados' / 'execucoes' / 'ServidoresWindows'
        folder.mkdir()
        final = folder / 'Auditoria Galaxia Servidores Windows - Teste Completo.docx'
        final.write_bytes(b'first-run')
        approve_documents(self.root, 'windows', [final], self.execution_id)
        second = '550e8400-e29b-41d4-a716-446655440001'
        final.write_bytes(b'second-run')
        approve_documents(self.root, 'windows', [final], second)
        for execution, expected in [(self.execution_id, b'first-run'), (second, b'second-run')]:
            with build_documents_zip(self.root, execution_id=execution) as stream, ZipFile(stream) as archive:
                self.assertEqual(archive.read(f'ServidoresWindows/{final.name}'), expected)
        self.assertEqual(len(list_document_executions(self.root)), 2)
        with self.assertRaises(ValueError):
            build_documents_zip(self.root, execution_id='../outside')
