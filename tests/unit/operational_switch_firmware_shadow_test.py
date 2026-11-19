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

from services import operational_switch_firmware as module
from scripts.database import sync_switch_firmware_catalog as cli
from tests.unit.operational_switch_firmware_capture_test import capture, NOW
from tests.unit.operational_switch_firmware_sync_test import catalog


class FirmwareShadowTests(unittest.TestCase):
    def test_disabled_by_default_and_outside_rigel_without_source_or_sql(self):
        for computer, enabled in (('OTHER', True), ('RIGEL', False)):
            with patch.dict(os.environ, {'COMPUTERNAME': computer}), \
                    patch.object(module, 'shadow_enabled', return_value=enabled), \
                    patch.object(module, 'read_current_catalog') as read, patch.object(module, 'connect_collector') as connect:
                self.assertFalse(module.poll_firmware_catalog(MagicMock()))
                read.assert_not_called()
                connect.assert_not_called()

    def test_current_capture_reuses_validated_projection_without_sql(self):
        payload = capture()
        with patch.object(module, 'capture', return_value=payload) as read, patch.object(module, 'connect_collector') as connect:
            snap = module.read_current_catalog(NOW)
            self.assertEqual(snap.digest, payload['digest_carga'])
            read.assert_called_once_with(module.DATABASE_PATH, module.CACHE_PATH, now=NOW)
            connect.assert_not_called()

    def test_future_consultation_and_invalid_inventory_block(self):
        with patch.object(module, 'capture', return_value=capture()), self.assertRaises(module.ImportErrorSafe):
            module.read_current_catalog(datetime(2020, 1, 1, tzinfo=timezone.utc))
        logger = MagicMock()
        with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), \
                patch.object(module, 'read_current_catalog', side_effect=ValueError('SECRET_PRIVATE')), \
                patch.object(module, 'connect_collector') as connect, patch.object(module, 'save_status') as save:
            self.assertFalse(module.poll_firmware_catalog(logger))
            connect.assert_not_called()
            save.assert_not_called()
        self.assertNotIn('SECRET_PRIVATE', str(logger.warning.call_args_list))

    def test_success_saves_safe_status_only_after_commit(self):
        snap = catalog()
        events = []
        with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), \
                patch.object(module, 'read_current_catalog', return_value=snap), \
                patch.object(module, 'connect_collector') as connect, \
                patch.object(module, 'write_catalog', return_value='sincronizado') as write, \
                patch.object(module, 'save_status', side_effect=lambda *args: events.append('save')) as save:
            connect.return_value.__exit__.side_effect = lambda *args: events.append('commit')
            self.assertTrue(module.poll_firmware_catalog(MagicMock()))
            write.assert_called_once()
            save.assert_called_once_with(snap, 'sincronizado')
        self.assertEqual(events, ['commit', 'save'])

    def test_commit_error_never_publishes_success_or_raw_details(self):
        logger = MagicMock()
        with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), \
                patch.object(module, 'read_current_catalog', return_value=catalog()), \
                patch.object(module, 'connect_collector') as connect, patch.object(module, 'write_catalog'), \
                patch.object(module, 'save_status') as save:
            connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
            self.assertFalse(module.poll_firmware_catalog(logger))
            save.assert_not_called()
        self.assertNotIn('SECRET_PRIVATE', str(logger.warning.call_args_list))

    def test_disable_during_capture_prevents_sql_and_during_write_rolls_back(self):
        for effects, connects in (([True, True, False], False), ([True, True, True, False], True)):
            with patch.object(module, 'automatic_enabled', side_effect=effects), patch.object(module, '_InterprocessFileLock'), \
                    patch.object(module, 'read_current_catalog', return_value=catalog()), \
                    patch.object(module, 'connect_collector') as connect, patch.object(module, 'write_catalog'), \
                    patch.object(module, 'save_status') as save:
                self.assertFalse(module.poll_firmware_catalog(MagicMock()))
                self.assertEqual(connect.called, connects)
                save.assert_not_called()
                if connects:
                    self.assertIsNotNone(connect.return_value.__exit__.call_args.args[0])

    def test_safe_atomic_status_no_inventory_or_secrets_and_failed_replace_keeps_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            module.save_status(catalog(), 'sincronizado', path)
            original = path.read_bytes()
            self.assertNotIn(b'PRIVATE', original)
            self.assertNotIn(b'192.0.2.1', original)
            self.assertTrue(json.loads(original)['sincronizacao_automatica_firmware'])
            with patch.object(module.os, 'replace', side_effect=OSError('SECRET_PRIVATE')), self.assertRaises(OSError):
                module.save_status(catalog(), 'sincronizado', path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob('.firmware-*')), [])

    def test_current_cli_is_read_only_even_when_enabled(self):
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                patch.object(module, 'read_current_catalog', return_value=catalog()), \
                patch.object(module, 'automatic_enabled', return_value=True), \
                patch('services.operational_postgres.connect_collector') as connect, \
                patch.object(cli, 'inspect_catalog', return_value={'conteudo_atual_confere': True}), \
                patch.object(cli, 'write_catalog') as write, redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(['--current']), 0)
            connect.assert_called_once_with(read_only=True)
            write.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertTrue(result['conteudo_atual_confere'])
        self.assertTrue(result['sincronizacao_automatica_firmware'])
        self.assertNotIn('PRIVATE', out.getvalue())

    def test_current_apply_and_wrong_machine_rejected_without_capture_or_connection(self):
        for machine, flags in (('RIGEL', ['--apply']), ('OTHER', [])):
            with patch.dict(os.environ, {'COMPUTERNAME': machine}), \
                    patch.object(module, 'read_current_catalog') as read, \
                    patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(cli.main(['--current', *flags]), 1)
                connect.assert_not_called()
                read.assert_not_called()

    def test_worker_singleton_and_startup_independent_of_requests(self):
        worker = MagicMock()
        worker.is_alive.return_value = True
        with patch.object(module, '_worker', worker):
            self.assertIs(module.start_firmware_sync_worker(), worker)
        with patch.object(module, '_worker', None), patch.object(module.threading, 'Thread') as thread:
            self.assertIs(module.start_firmware_sync_worker(), thread.return_value)
            thread.return_value.start.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])
        startup = (module.PROJECT_ROOT / 'run_web_service.py').read_text(encoding='utf-8')
        self.assertIn('start_firmware_sync_worker(app.logger)', startup)
        self.assertEqual(module.POLL_SECONDS, 300)

    def test_worker_imports_no_scheduler_network_or_runtime_config(self):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'subprocess', 'requests', 'socket',
                                    'services.switch_update_v01.scheduler', 'gerenciar_switches'})


if __name__ == '__main__':
    unittest.main()
