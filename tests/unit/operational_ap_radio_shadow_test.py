import ast
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services import operational_ap_radios as module
from scripts.database import sync_ap_radio_catalog as cli
from tests.unit.operational_ap_radio_capture_test import payload, NOW
from tests.unit.operational_ap_radio_sync_test import build


class ApRadioShadowTests(unittest.TestCase):
    def test_disabled_invalid_bom_config_and_wrong_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            flag = Path(directory) / 'flag.json'
            for machine, content in (('RIGEL', None), ('RIGEL', 'PRIVATE'), ('RIGEL', '{}'),
                                     ('RIGEL', '{"enabled":"true"}'), ('RIGEL', '{"enabled":false}'),
                                     ('OTHER', '{"enabled":true}')):
                if content is not None:
                    flag.write_text(content)
                with patch.dict(os.environ, {'COMPUTERNAME': machine}), patch.object(module, 'CONFIG_PATH', flag), patch.object(
                        module, 'read_current_catalog') as read, patch.object(module, 'connect_collector') as connect:
                    self.assertFalse(module.poll_ap_radios(MagicMock()))
                    read.assert_not_called()
                    connect.assert_not_called()
            flag.write_text('{"enabled":true}', encoding='utf-8-sig')
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(module, 'CONFIG_PATH', flag):
                self.assertTrue(module.automatic_enabled())

    def test_current_catalog_preserves_whitelist_nulls_zeros_naive_publication_and_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'unifi.json'
            raw = json.dumps(payload()).encode()
            path.write_bytes(raw)
            with patch.object(module, 'SOURCE_PATH', path), patch.object(module, 'connect_collector') as connect:
                catalog = module.read_current_catalog(NOW)
                connect.assert_not_called()
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(catalog.rows, build().rows)
            self.assertNotIn('SECRET_MARKER', repr(catalog.rows))
            self.assertEqual(module.summary(catalog.payload)['publicacao_fonte'], 'sem_fuso')

    def test_source_changed_or_missing_native_response_does_not_connect(self):
        raw = json.dumps(payload()).encode()
        with patch.object(Path, 'read_bytes', side_effect=[raw, b'changed']), self.assertRaises(module.ImportErrorSafe):
            module.read_current_catalog(NOW)
        original = payload()
        del original['aps'][0]['radios_nativos']
        for data in (b'{}', b'invalid', json.dumps(original).encode()):
            with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), patch.object(
                    Path, 'read_bytes', return_value=data), patch.object(module, 'connect_collector') as connect, patch.object(
                    module, 'save_status') as save:
                self.assertFalse(module.poll_ap_radios(MagicMock()))
                connect.assert_not_called()
                save.assert_not_called()

    def test_success_status_only_after_commit(self):
        catalog, events = build(), []
        with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock'), patch.object(
                module, 'read_current_catalog', return_value=catalog), patch.object(module, 'connect_collector') as connect, patch.object(
                module, 'write_catalog', return_value='sincronizado') as write, patch.object(
                module, 'save_status', side_effect=lambda *args: events.append('save')) as save:
            connect.return_value.__exit__.side_effect = lambda *args: events.append('commit')
            self.assertTrue(module.poll_ap_radios(MagicMock()))
            write.assert_called_once_with(connect.return_value.__enter__.return_value, catalog)
            save.assert_called_once_with(catalog, 'sincronizado')
        self.assertEqual(events, ['commit', 'save'])

    def test_write_commit_or_lock_failure_does_not_publish_or_leak_exception(self):
        for failure in ('write', 'commit', 'lock'):
            logger = MagicMock()
            with patch.object(module, 'automatic_enabled', return_value=True), patch.object(module, '_InterprocessFileLock') as lock, patch.object(
                    module, 'read_current_catalog', return_value=build()), patch.object(module, 'connect_collector') as connect, patch.object(
                    module, 'write_catalog') as write, patch.object(module, 'save_status') as save:
                if failure == 'write':
                    write.side_effect = RuntimeError('SECRET_PRIVATE')
                elif failure == 'commit':
                    connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                else:
                    lock.side_effect = TimeoutError('SECRET_PRIVATE')
                self.assertFalse(module.poll_ap_radios(logger))
                save.assert_not_called()
                if failure == 'lock':
                    connect.assert_not_called()
            self.assertNotIn('SECRET_PRIVATE', str(logger.warning.call_args_list))
            self.assertIn('falha_sincronizacao_radios_unifi', str(logger.warning.call_args_list))

    def test_disable_after_lock_capture_or_write_prevents_commit_success(self):
        for flags, connected in (([True, False], False), ([True, True, False], False), ([True, True, True, False], True)):
            with patch.object(module, 'automatic_enabled', side_effect=flags), patch.object(module, '_InterprocessFileLock'), patch.object(
                    module, 'read_current_catalog', return_value=build()), patch.object(module, 'connect_collector') as connect, patch.object(
                    module, 'write_catalog'), patch.object(module, 'save_status') as save:
                self.assertFalse(module.poll_ap_radios(MagicMock()))
                self.assertEqual(connect.called, connected)
                save.assert_not_called()
                if connected:
                    self.assertIsNotNone(connect.return_value.__exit__.call_args.args[0])

    def test_status_atomic_safe_summary_and_replace_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            module.save_status(build(), 'sincronizado', path)
            raw = path.read_bytes()
            status = json.loads(raw)
            self.assertTrue(status['sincronizacao_automatica_radios'])
            self.assertTrue(status['vinculos_sql_conferidos'])
            self.assertEqual(status['aps'], 1)
            self.assertEqual(status['estatisticas_radio'], 1)
            self.assertEqual(status['sem_data_de_medicao'], 1)
            for forbidden in (b'PRIVATE', b'SECRET', b'00:11:22:33:44:55', b'192.0.2.1'):
                self.assertNotIn(forbidden, raw)
            with patch.object(module.os, 'replace', side_effect=OSError('PRIVATE')), self.assertRaises(OSError):
                module.save_status(build(), 'sincronizado', path)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(path.parent.glob('.ap-radios-*')), [])

    def test_current_cli_readonly_reports_flag_without_writing_or_starting_worker(self):
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(module, 'read_current_catalog', return_value=build()), patch.object(
                module, 'automatic_enabled', return_value=True), patch('services.operational_postgres.connect_collector') as connect, patch.object(
                cli, 'inspect_catalog', return_value={'conteudo_atual_confere': True}), patch.object(cli, 'write_catalog') as write, patch.object(
                module, 'start_ap_radio_sync_worker') as start, redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(['--current']), 0)
            connect.assert_called_once_with(read_only=True)
            write.assert_not_called()
            start.assert_not_called()
        status = json.loads(out.getvalue())
        self.assertTrue(status['conteudo_atual_confere'])
        self.assertTrue(status['sincronizacao_automatica_radios'])

    def test_current_apply_and_wrong_machine_rejected_before_read_or_connect(self):
        for machine, flags in (('RIGEL', ['--apply']), ('OTHER', [])):
            with patch.dict(os.environ, {'COMPUTERNAME': machine}), patch.object(module, 'read_current_catalog') as read, patch(
                    'services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(cli.main(['--current', *flags]), 1)
                read.assert_not_called()
                connect.assert_not_called()

    def test_worker_singleton_retry_interval_and_daemon(self):
        worker = MagicMock()
        worker.is_alive.return_value = True
        with patch.object(module, '_worker', worker):
            self.assertIs(module.start_ap_radio_sync_worker(), worker)
        with patch.object(module, '_worker', None), patch.object(module.threading, 'Thread') as thread, patch.object(
                module, 'poll_ap_radios', side_effect=[False, StopIteration]) as poll, patch.object(module.threading, 'Event') as event:
            self.assertIs(module.start_ap_radio_sync_worker(), thread.return_value)
            thread.return_value.start.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])
            with self.assertRaises(StopIteration):
                thread.call_args.kwargs['target']()
            self.assertEqual(poll.call_count, 2)
            event.return_value.wait.assert_called_once_with(300)

    def test_startup_integration_no_collector_requests_web_config_or_equipment_imports(self):
        startup = (module.PROJECT_ROOT / 'run_web_service.py').read_text(encoding='utf-8')
        self.assertIn('start_ap_radio_sync_worker(app.logger)', startup)
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'requests', 'subprocess', 'Unifi', 'gerenciador_atualizacoes'})


if __name__ == '__main__':
    unittest.main()
