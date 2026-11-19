import ast
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services import operational_regional_metadata as module
from scripts.database import sync_regional_metadata_catalog as cli
from tests.unit.operational_regional_metadata_sync_test import catalog
from tests.unit.operational_regional_metadata_sources_audit_test import payload

NOW = datetime(2026, 11, 19, 14, tzinfo=timezone.utc)


class RegionalMetadataShadowTests(unittest.TestCase):
    def test_disabled_missing_malformed_or_wrong_host_never_reads_source_or_connects(self):
        with tempfile.TemporaryDirectory() as directory:
            flag = Path(directory) / 'flag.json'
            for machine, content in (('RIGEL', None), ('RIGEL', 'PRIVATE'), ('RIGEL', '{}'),
                                     ('RIGEL', '{"enabled":"true"}'), ('RIGEL', '{"enabled":false}'),
                                     ('OTHER', '{"enabled":true}')):
                if content is not None:
                    flag.write_text(content)
                with patch.dict(os.environ, {'COMPUTERNAME': machine}), patch.object(module, 'CONFIG_PATH', flag), \
                        patch.object(module, 'read_current_catalog') as read, patch.object(module, 'connect_collector') as connect:
                    self.assertFalse(module.poll_regional_metadata(MagicMock()))
                    read.assert_not_called()
                    connect.assert_not_called()

    def test_stable_capture_preserves_naive_publication_without_modifying_source(self):
        original = payload()
        original['configuracao']['ultima_atualizacao'] = '2026-11-19T10:00:00'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'regional.json'
            raw = json.dumps(original).encode()
            source.write_bytes(raw)
            with patch.object(module, 'SOURCE_PATH', source), patch.object(module, 'connect_collector') as connect:
                snap = module.read_current_catalog(NOW)
                connect.assert_not_called()
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(snap.summary()['publicacao_cadastro'], 'sem_fuso')
            self.assertEqual(snap.source[3], '2026-11-19T10:00:00')
            self.assertNotIn('PRIVATE', json.dumps(snap.summary()))

    def test_changing_or_invalid_catalog_preserves_sql(self):
        raw = json.dumps(payload()).encode()
        with patch.object(Path, 'read_bytes', side_effect=[raw, b'changed']), self.assertRaises(module.ImportErrorSafe):
            module.read_current_catalog(NOW)
        logger = MagicMock()
        with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), \
                patch.object(module, 'read_current_catalog', side_effect=ValueError('SECRET_PRIVATE')), \
                patch.object(module, 'connect_collector') as connect, patch.object(module, 'save_status') as save:
            self.assertFalse(module.poll_regional_metadata(logger))
            connect.assert_not_called()
            save.assert_not_called()
        self.assertNotIn('PRIVATE', str(logger.warning.call_args_list))

    def test_success_publishes_only_after_commit(self):
        snap = catalog()
        events = []
        with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), \
                patch.object(module, 'read_current_catalog', return_value=snap), \
                patch.object(module, 'connect_collector') as connect, \
                patch.object(module, 'write_catalog', return_value='sincronizado') as write, \
                patch.object(module, 'save_status', side_effect=lambda *args: events.append('save')) as save:
            connect.return_value.__exit__.side_effect = lambda *args: events.append('commit')
            self.assertTrue(module.poll_regional_metadata(MagicMock()))
            write.assert_called_once_with(connect.return_value.__enter__.return_value, snap)
            save.assert_called_once_with(snap, 'sincronizado')
        self.assertEqual(events, ['commit', 'save'])

    def test_write_or_commit_failure_never_publishes_success(self):
        for failure in ('write', 'commit'):
            logger = MagicMock()
            with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), \
                    patch.object(module, 'read_current_catalog', return_value=catalog()), \
                    patch.object(module, 'connect_collector') as connect, patch.object(module, 'write_catalog') as write, \
                    patch.object(module, 'save_status') as save:
                if failure == 'write':
                    write.side_effect = RuntimeError('SECRET_PRIVATE')
                else:
                    connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                self.assertFalse(module.poll_regional_metadata(logger))
                save.assert_not_called()
            self.assertNotIn('SECRET_PRIVATE', str(logger.warning.call_args_list))

    def test_disable_during_capture_prevents_sql_and_before_commit_rolls_back(self):
        for effects, connects in (([True, True, False], False), ([True, True, True, False], True)):
            with patch.object(module, 'automatic_enabled', side_effect=effects), patch.object(module, '_InterprocessFileLock'), \
                    patch.object(module, 'read_current_catalog', return_value=catalog()), \
                    patch.object(module, 'connect_collector') as connect, patch.object(module, 'write_catalog'), \
                    patch.object(module, 'save_status') as save:
                self.assertFalse(module.poll_regional_metadata(MagicMock()))
                self.assertEqual(connect.called, connects)
                save.assert_not_called()
                if connects:
                    self.assertIsNotNone(connect.return_value.__exit__.call_args.args[0])

    def test_safe_atomic_status_has_no_codes_names_descriptions_or_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            module.save_status(catalog(), 'sincronizado', path)
            raw = path.read_bytes()
            self.assertNotIn(b'PRIVATE', raw)
            status = json.loads(raw)
            self.assertTrue(status['sincronizacao_automatica_metadados'])
            self.assertEqual(status['regionais'], 1)
            with patch.object(module.os, 'replace', side_effect=OSError('SECRET_PRIVATE')), self.assertRaises(OSError):
                module.save_status(catalog(), 'sincronizado', path)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(path.parent.glob('.regional-metadata-*')), [])

    def test_current_cli_readonly_reports_flag_not_worker_liveness(self):
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                patch.object(module, 'read_current_catalog', return_value=catalog()), \
                patch.object(module, 'automatic_enabled', return_value=True), \
                patch('services.operational_postgres.connect_collector') as connect, \
                patch.object(cli, 'inspect_catalog', return_value={'conteudo_atual_confere': True}), \
                patch.object(cli, 'write_catalog') as write, redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(['--current']), 0)
            connect.assert_called_once_with(read_only=True)
            write.assert_not_called()
        status = json.loads(out.getvalue())
        self.assertTrue(status['conteudo_atual_confere'])
        self.assertTrue(status['sincronizacao_automatica_metadados'])
        self.assertNotIn('PRIVATE', out.getvalue())

    def test_current_apply_wrong_machine_and_busy_file_lock_do_not_connect(self):
        for machine, flags in (('RIGEL', ['--apply']), ('OTHER', [])):
            with patch.dict(os.environ, {'COMPUTERNAME': machine}), \
                    patch.object(module, 'read_current_catalog') as read, \
                    patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(cli.main(['--current', *flags]), 1)
                read.assert_not_called()
                connect.assert_not_called()
        with patch.object(module, 'automatic_enabled', return_value=True), \
                patch.object(module, '_InterprocessFileLock', side_effect=TimeoutError('PRIVATE')), \
                patch.object(module, 'connect_collector') as connect:
            self.assertFalse(module.poll_regional_metadata(MagicMock()))
            connect.assert_not_called()

    def test_worker_singleton_daemon_interval_and_retry_after_failed_cycle(self):
        worker = MagicMock()
        worker.is_alive.return_value = True
        with patch.object(module, '_worker', worker):
            self.assertIs(module.start_regional_metadata_sync_worker(), worker)
        with patch.object(module, '_worker', None), patch.object(module.threading, 'Thread') as thread, \
                patch.object(module, 'poll_regional_metadata', side_effect=[False, StopIteration]) as poll, \
                patch.object(module.threading, 'Event') as event:
            self.assertIs(module.start_regional_metadata_sync_worker(), thread.return_value)
            thread.return_value.start.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])
            with self.assertRaises(StopIteration):
                thread.call_args.kwargs['target']()
            self.assertEqual(poll.call_count, 2)
            event.return_value.wait.assert_called_once_with(300)

    def test_service_startup_no_request_dependency_or_manager_imports(self):
        startup = (module.PROJECT_ROOT / 'run_web_service.py').read_text(encoding='utf-8')
        self.assertIn('start_regional_metadata_sync_worker(app.logger)', startup)
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'gerenciar_regionais', 'requests', 'subprocess',
                                    'services.operational_server_postgres', 'gerenciar_contatos_email'})


if __name__ == '__main__':
    unittest.main()
