import ast
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone, timedelta
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from openpyxl import Workbook
import services.operational_sla_contacts as module
from scripts.database.import_sla_contacts import build_contact_catalog, CONTACT_COLUMNS
from scripts.database.sync_sla_contacts import main

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def files(root):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Contacts'
    sheet.append(list(CONTACT_COLUMNS))
    row = {'NOME_REGIONAL': 'V021_BAHIA', 'NOME_REG_FORTI': 'REPORT_BAHIA',
           'NOME_DIRETOR_1': 'PERSON_PRIVATE', 'EMAIL_DIRETOR': 'EMAIL_PRIVATE@example.test'}
    sheet.append([row.get(column) for column in CONTACT_COLUMNS])
    stream = BytesIO()
    book.save(stream)
    book.close()
    (root / 'source.xlsx').write_bytes(stream.getvalue())
    (root / 'estrutura_regionais.json').write_text(json.dumps({'regionais': {'REG_BAHIA': {'nome': 'Bahia', 'password': 'SECRET_PRIVATE'}}}), encoding='utf-8')
    (root / 'environment.json').write_text(json.dumps({'email_contatos': {'xlsx_path': str(root / 'source.xlsx'), 'sheet_name': 'Contacts'}, 'password': 'SECRET_PRIVATE'}), encoding='utf-8')


def snapshot(root, at=NOW):
    catalog = build_contact_catalog((root / 'source.xlsx').read_bytes(), (root / 'estrutura_regionais.json').read_bytes(), 'Contacts')
    return module.prepare_contact_snapshot(catalog, root / 'source.xlsx', at)


def connection(snap, marker=None, *, acquired=True):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433), (acquired,), ('Contacts',), marker, (len(snap.catalog.assignments),)]
    cursor.fetchall.side_effect = [[(code,) for code in snap.catalog.regional_codes], list(snap.catalog.contacts)]
    return conn, cursor


class ContactShadowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        files(self.root)
        self.snap = snapshot(self.root)

    def test_receipt_and_summary_have_no_personal_data_or_paths(self):
        encoded = json.dumps(self.snap.receipt()) + json.dumps(self.snap.summary()) + repr(self.snap)
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn('Contacts', encoded)
        self.assertFalse(self.snap.summary()['planilha_modificada'])

    def test_digest_ignores_capture_but_pins_source_location(self):
        self.assertEqual(self.snap.digest, snapshot(self.root, NOW + timedelta(minutes=5)).digest)
        other = module.prepare_contact_snapshot(self.snap.catalog, self.root / 'different.xlsx', NOW)
        self.assertNotEqual(self.snap.digest, other.digest)
        self.assertNotEqual(self.snap.config_hash, other.config_hash)

    def test_read_and_validation_never_change_original_sources(self):
        originals = {name: (self.root / name).read_bytes() for name in ('source.xlsx', 'estrutura_regionais.json', 'environment.json')}
        with patch.object(module, 'PROJECT_ROOT', self.root):
            current = module.read_current_snapshot(NOW)
            module.verify_current(current)
        self.assertEqual(originals, {name: (self.root / name).read_bytes() for name in originals})

    def test_source_change_rejects_receipt_and_validation(self):
        path = self.root / 'receipt.json'
        module.save_contact_publication(self.snap, path)
        with patch.object(module, 'PROJECT_ROOT', self.root):
            self.assertEqual(module.load_contact_publication(path).digest, self.snap.digest)
            config = json.loads((self.root / 'environment.json').read_text())
            config['email_contatos']['sheet_name'] = 'Missing'
            (self.root / 'environment.json').write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                module.load_contact_publication(path)

    def test_failed_receipt_replace_preserves_previous_file(self):
        path = self.root / 'receipt.json'
        module.save_contact_publication(self.snap, path)
        before = path.read_bytes()
        with patch.object(module.os, 'replace', side_effect=OSError), self.assertRaises(OSError):
            module.save_contact_publication(snapshot(self.root, NOW + timedelta(minutes=5)), path)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_future_or_invalid_receipt_is_refused(self):
        path = self.root / 'receipt.json'
        module.save_contact_publication(snapshot(self.root, datetime.now(timezone.utc) + timedelta(days=1)), path)
        with self.assertRaises(module.SnapshotError):
            module.load_contact_publication(path)
        path.write_text('{"version":2}')
        with self.assertRaises(module.SnapshotError):
            module.load_contact_publication(path)

    def test_writer_upserts_and_soft_absence_before_marker_with_parameters(self):
        conn, cursor = connection(self.snap)
        validate = MagicMock()
        self.assertEqual(module.write_contact_snapshot(conn, self.snap, validate_source=validate), 'sincronizado')
        self.assertEqual(validate.call_count, 2)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(sum('SET presente_na_fonte=false' in statement for statement in sql), 2)
        self.assertFalse(any(statement.startswith('DELETE') for statement in sql))
        self.assertLess(next(i for i, s in enumerate(sql) if s.startswith('SELECT codigo_regional,papel')),
                        next(i for i, s in enumerate(sql) if s.startswith('INSERT INTO operacional.sincronizacoes_contatos_sla')))
        self.assertFalse(any('SHARE ROW EXCLUSIVE' in s for s in sql))
        for call in cursor.execute.call_args_list:
            self.assertNotIn('PRIVATE', call.args[0])
            if len(call.args) == 2:
                self.assertEqual(call.args[0].count('%s'), len(call.args[1]))
        conn.commit.assert_not_called()

    def test_same_content_only_updates_verification_metadata(self):
        conn, cursor = connection(self.snap, (NOW - timedelta(minutes=5), self.snap.digest, self.snap.config_hash))
        self.assertEqual(module.write_contact_snapshot(conn, self.snap, validate_source=lambda s: None), 'sem_alteracoes')
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any('SET presente_na_fonte=false' in s for s in sql))
        self.assertFalse(any(s.startswith('INSERT INTO operacional.contatos_regionais_sla') for s in sql))

    def test_cleared_role_is_not_upserted_and_last_value_is_not_deleted(self):
        from dataclasses import replace
        old_catalog = replace(self.snap.catalog, contacts=tuple(sorted((*self.snap.catalog.contacts,
                              ('REG_BAHIA', 'gerente', 'OTHER_PRIVATE', 'OTHER_PRIVATE@example.test')))))
        old = module.prepare_contact_snapshot(old_catalog, self.root / 'source.xlsx', NOW - timedelta(minutes=5))
        conn, cursor = connection(self.snap, (old.captured_at, old.digest, old.config_hash))
        self.assertEqual(module.write_contact_snapshot(conn, self.snap, validate_source=lambda s: None), 'sincronizado')
        inserts = [call for call in cursor.execute.call_args_list
                   if call.args[0].startswith('INSERT INTO operacional.contatos_regionais_sla')]
        self.assertEqual([call.args[1][2] for call in inserts], ['diretor'])
        absent = [call.args[0] for call in cursor.execute.call_args_list if 'SET presente_na_fonte=false' in call.args[0]]
        self.assertEqual(len(absent), 2)
        self.assertTrue(all('nome_origem' not in sql and 'email_origem' not in sql for sql in absent))

    def test_older_capture_cannot_overwrite_a_newer_marker(self):
        conn, cursor = connection(self.snap, (NOW + timedelta(seconds=1), 'new', self.snap.config_hash))
        self.assertEqual(module.write_contact_snapshot(conn, self.snap, validate_source=lambda s: None), 'publicacao_mais_antiga_ignorada')
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cursor.execute.call_args_list))

    def test_changed_source_config_same_clock_conflict_or_busy_blocks(self):
        for marker, acquired in (((NOW, 'other', self.snap.config_hash), True),
                                 ((NOW, self.snap.digest, 'other_config'), True), (None, False)):
            conn, cursor = connection(self.snap, marker, acquired=acquired)
            with self.subTest(marker=marker), self.assertRaises(module.SnapshotError):
                module.write_contact_snapshot(conn, self.snap, validate_source=lambda s: None)
            self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cursor.execute.call_args_list))

    def test_changed_source_before_commit_prevents_marker(self):
        conn, cursor = connection(self.snap)
        validate = MagicMock(side_effect=[None, module.SnapshotError('changed')])
        with self.assertRaises(module.SnapshotError):
            module.write_contact_snapshot(conn, self.snap, validate_source=validate)
        self.assertFalse(any(call.args[0].startswith('INSERT INTO operacional.sincronizacoes_contatos_sla') for call in cursor.execute.call_args_list))
        conn.commit.assert_not_called()

    def test_contact_mismatch_after_upsert_blocks_marker(self):
        conn, cursor = connection(self.snap)
        cursor.fetchall.side_effect = [[('REG_BAHIA',)], []]
        with self.assertRaises(module.SnapshotError):
            module.write_contact_snapshot(conn, self.snap, validate_source=lambda s: None)
        self.assertFalse(any(call.args[0].startswith('INSERT INTO operacional.sincronizacoes_contatos_sla') for call in cursor.execute.call_args_list))

    def test_read_only_inspection(self):
        conn, cursor = MagicMock(), MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433), (NOW, self.snap.digest, self.snap.config_hash), (38,), (127,)]
        result = module.inspect_contact_snapshot(conn, self.snap)
        self.assertTrue(result['conteudo_ja_sincronizado'])
        self.assertFalse(any(call.args[0].startswith(('LOCK', 'INSERT', 'UPDATE', 'DELETE')) for call in cursor.execute.call_args_list))

    def test_disabled_poll_or_non_rigel_never_reads_workbook_or_connects(self):
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(module, 'shadow_enabled', return_value=False), patch.object(module, 'read_current_snapshot') as read, patch.object(module, 'connect_collector') as connect:
            self.assertFalse(module.poll_contact_catalog(MagicMock()))
            read.assert_not_called()
            connect.assert_not_called()

    def test_poll_sql_failure_preserves_receipt_and_safe_logs(self):
        path = self.root / 'receipt.json'
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(module, 'shadow_enabled', return_value=True), patch.object(module, 'read_current_snapshot', return_value=self.snap), patch.object(module, 'LOCK_PATH', self.root / 'poll.lock'), patch.object(module, 'PUBLICATION_PATH', path), patch.object(module, 'connect_collector', side_effect=RuntimeError('SECRET_PRIVATE')):
            logger = MagicMock()
            self.assertFalse(module.poll_contact_catalog(logger))
            self.assertTrue(path.is_file())
            self.assertNotIn('PRIVATE', path.read_text())
            self.assertNotIn('PRIVATE', str(logger.method_calls))

    def test_enabled_poll_finishes_transaction_and_disabled_recheck_skips_connection(self):
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(module, 'shadow_enabled', side_effect=[True, True, True, False]), patch.object(module, 'read_current_snapshot', return_value=self.snap), patch.object(module, 'LOCK_PATH', self.root / 'poll.lock'), patch.object(module, 'PUBLICATION_PATH', self.root / 'receipt.json'), patch.object(module, 'connect_collector') as connect, patch.object(module, 'write_contact_snapshot') as write:
            self.assertTrue(module.poll_contact_catalog(MagicMock()))
            write.assert_called_once_with(connect.return_value.__enter__.return_value, self.snap)
            connect.return_value.__exit__.assert_called_once()
            connect.reset_mock()
            self.assertFalse(module.poll_contact_catalog(MagicMock()))
            connect.assert_not_called()

    def test_cli_capture_never_connects_and_bad_digest_blocks_apply(self):
        import scripts.database.sync_sla_contacts as cli
        path = self.root / 'receipt.json'
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(cli, 'LOCK_PATH', self.root / 'cli.lock'), patch.object(cli, 'read_current_snapshot', return_value=self.snap), patch.object(cli, 'connect_collector') as connect, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(['--capture', '--publication', str(path)]), 0)
            connect.assert_not_called()
            with patch.object(cli, 'load_contact_publication', return_value=self.snap):
                self.assertEqual(main(['--apply', '--expected-digest', 'wrong', '--publication', str(path)]), 1)
                connect.assert_not_called()

    def test_worker_singleton_starts_only_when_called(self):
        with patch.object(module, '_worker', None), patch.object(module.threading, 'Thread') as thread:
            thread.return_value.is_alive.return_value = True
            self.assertIs(module.start_contact_sync_worker(), module.start_contact_sync_worker())
            thread.return_value.start.assert_called_once()
            thread.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])

    def test_worker_waits_five_minutes_between_polls(self):
        with patch.object(module, '_worker', None), patch.object(module.threading, 'Thread') as thread, patch.object(module.threading, 'Event') as event, patch.object(module, 'poll_contact_catalog') as poll:
            module.start_contact_sync_worker(MagicMock())
            target = thread.call_args.kwargs['target']
            event.return_value.wait.side_effect = StopIteration
            with self.assertRaises(StopIteration):
                target()
            poll.assert_called_once()
            event.return_value.wait.assert_called_once_with(300)

    def test_cli_commit_failure_cannot_print_success(self):
        import scripts.database.sync_sla_contacts as cli
        path = self.root / 'receipt.json'
        module.save_contact_publication(self.snap, path)
        output, error = StringIO(), StringIO()
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(cli, 'LOCK_PATH', self.root / 'cli.lock'), patch.object(cli, 'load_contact_publication', return_value=self.snap), patch.object(cli, 'write_contact_snapshot', return_value='sincronizado'), patch.object(cli, 'connect_collector') as connect, redirect_stdout(output), redirect_stderr(error):
            connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
            self.assertEqual(main(['--apply', '--publication', str(path), '--expected-digest', self.snap.digest]), 1)
            self.assertEqual(output.getvalue(), '')
            self.assertNotIn('PRIVATE', error.getvalue())

    def test_startup_hook_is_inside_main_and_migration_does_not_grant_delete_or_global_read(self):
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse((root / 'run_web_service.py').read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        self.assertIn('start_contact_sync_worker', ast.unparse(function))
        self.assertNotIn('start_contact_sync_worker', '\n'.join(ast.unparse(n) for n in tree.body if n is not function))
        sql = (root / 'scripts/database/sql/015_sla_contacts_shadow_sync.sql').read_text()
        self.assertIn('FROM PUBLIC, sentinel_reader, sentinel_api', sql)
        self.assertIn('SET LOCAL ROLE sentinel_owner', sql)
        self.assertNotIn('GRANT DELETE', sql)
        self.assertNotIn(' TO sentinel_reader', sql)
        self.assertNotIn(' TO sentinel_api', sql)


if __name__ == '__main__':
    unittest.main()
