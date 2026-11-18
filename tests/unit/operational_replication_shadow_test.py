import ast
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import sync_replication_catalog as cli
from tests.unit.operational_replication_catalog_test import build, payload, row, IDENTITY
import services.operational_replication as module

NOW = datetime(2026, 11, 18, 14, tzinfo=timezone.utc)
ZONE = 'America/Sao_Paulo'


def connection(snapshot, *, source=None, marker=None, actual=None, errors=None):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [IDENTITY, (True,), source if source is not None else
                                   (ZONE, snapshot.catalog.publication, snapshot.catalog.source_sha256), marker]
    cursor.fetchall.side_effect = [list(snapshot.catalog.rows if actual is None else actual),
                                    list(snapshot.catalog.errors if errors is None else errors)]
    return conn, cursor


class ReplicationShadowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'replicacao.json'
        self.source.write_text(json.dumps(payload()), encoding='utf-8')
        self.snapshot = module.prepare_replication_snapshot(build(), self.source, NOW)

    def test_summary_receipt_repr_never_expose_names_errors_paths(self):
        value = json.dumps(self.snapshot.receipt()) + json.dumps(self.snapshot.summary()) + repr(self.snapshot)
        self.assertNotIn('PRIVATE', value)
        self.assertNotIn(str(self.root), value)
        self.assertTrue(self.snapshot.summary()['publicacao_nao_comprova_coleta_ad'])

    def test_capture_time_does_not_change_digest_but_zone_path_or_content_does(self):
        later = module.prepare_replication_snapshot(build(), self.source, NOW + timedelta(minutes=5))
        self.assertEqual(self.snapshot.digest, later.digest)
        other = module.prepare_replication_snapshot(build(), self.root / 'other.json', NOW)
        self.assertNotEqual(self.snapshot.config_hash, other.config_hash)
        other = module.prepare_replication_snapshot(build(zone='UTC'), self.source, NOW)
        self.assertNotEqual(self.snapshot.digest, other.digest)
        other = module.prepare_replication_snapshot(build(payload(erros_operacionais=[])), self.source, NOW)
        self.assertNotEqual(self.snapshot.digest, other.digest)

    def test_capture_requires_aware_time_and_rejects_future_source_dates(self):
        for at in (NOW.replace(tzinfo=None), None, NOW - timedelta(days=1)):
            with self.assertRaises(module.SnapshotError):
                module.prepare_replication_snapshot(build(), self.source, at)
        catalog = build(payload(servidores=[row(ultima_replicacao='2026-11-19T10:00:00')]))
        with self.assertRaises(module.SnapshotError):
            module.prepare_replication_snapshot(catalog, self.source, NOW)

    def test_stable_read_and_verify_never_write_source_or_connect_sql(self):
        original = self.source.read_bytes()
        with patch.object(module, 'SOURCE_PATH', self.source), patch.object(module, 'connect_collector') as connect:
            snapshot = module.read_current_snapshot(ZONE, NOW)
            module.verify_current(snapshot)
            connect.assert_not_called()
        self.assertEqual(original, self.source.read_bytes())

    def test_config_requires_explicit_zone(self):
        flag = self.root / 'flag.json'
        with patch.object(module, 'SOURCE_PATH', self.source), patch.object(module, 'CONFIG_PATH', flag):
            flag.write_text('{}')
            with self.assertRaises(module.SnapshotError):
                module.read_current_snapshot(captured_at=NOW)
            flag.write_text(json.dumps({'source_timezone': ZONE}))
            self.assertEqual(module.read_current_snapshot(captured_at=NOW).digest, self.snapshot.digest)

    def test_source_changed_during_read_blocks(self):
        path = MagicMock()
        path.read_bytes.side_effect = [self.source.read_bytes(), b'changed']
        with patch.object(module, 'SOURCE_PATH', path), self.assertRaises(module.SnapshotError):
            module.read_current_snapshot(ZONE, NOW)

    def test_atomic_receipt_round_trip_and_source_change_blocks(self):
        receipt = self.root / 'receipt.json'
        module.save_replication_publication(self.snapshot, receipt)
        self.assertEqual(json.loads(receipt.read_text()), self.snapshot.receipt())
        self.assertEqual(len(list(self.root.glob('.replication-*'))), 0)
        with patch.object(module, 'SOURCE_PATH', self.source):
            loaded = module.load_replication_publication(receipt)
            self.assertEqual(loaded.digest, self.snapshot.digest)
            self.source.write_text(json.dumps(payload(erros_operacionais=[])))
            with self.assertRaises(module.SnapshotError):
                module.load_replication_publication(receipt)

    def test_invalid_receipts_future_time_extra_fields_and_hashes_block(self):
        receipt = self.root / 'receipt.json'
        for changes in ({'version': True}, {'password': 'PRIVATE'}, {'sha256_arquivo': 'PRIVATE'},
                        {'capturado_em': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
                        {'capturado_em': '2026-11-18T14:00:00'}):
            receipt.write_text(json.dumps({**self.snapshot.receipt(), **changes}))
            with self.assertRaises((module.SnapshotError, ValueError)):
                module.load_replication_publication(receipt)

    def test_new_publication_after_receipt_is_reported_as_changed_not_future(self):
        receipt = self.root / 'receipt.json'
        module.save_replication_publication(self.snapshot, receipt)
        changed = payload(timestamp='2026-11-18T11:05:00',
                          servidores=[row(ultima_replicacao='2026-11-18T11:05:00')])
        self.source.write_text(json.dumps(changed), encoding='utf-8')
        with patch.object(module, 'SOURCE_PATH', self.source), patch.object(module, 'connect_collector') as connect:
            with self.assertRaisesRegex(module.SnapshotError, 'Fonte mudou desde a captura'):
                module.load_replication_publication(receipt)
            with self.assertRaisesRegex(module.SnapshotError, 'Fonte mudou desde a captura'):
                module.verify_current(self.snapshot)
            connect.assert_not_called()

    def test_unchanged_future_source_still_blocked(self):
        raw = json.dumps(payload(timestamp='2026-11-19T11:00:00')).encode()
        self.source.write_bytes(raw)
        with patch.object(module, 'SOURCE_PATH', self.source):
            with self.assertRaisesRegex(module.SnapshotError, 'horario declarado futuro'):
                module.read_current_snapshot(ZONE, NOW, expected_sha256=hashlib.sha256(raw).hexdigest())

    def test_inspection_read_only_and_reports_marker_counts(self):
        conn, cur = MagicMock(), MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        marker = (NOW, self.snapshot.digest, self.snapshot.config_hash)
        cur.fetchone.side_effect = [IDENTITY, marker, (ZONE, self.snapshot.catalog.publication,
                                   self.snapshot.catalog.source_sha256), (2,), (1,)]
        report = module.inspect_replication_snapshot(conn, self.snapshot)
        self.assertTrue(report['conteudo_ja_sincronizado'])
        self.assertTrue(report['fonte_inicial_compativel'])
        self.assertFalse(any(call.args[0].startswith(('UPDATE', 'INSERT', 'DELETE')) for call in cur.execute.call_args_list))

    def test_write_parameterized_soft_absence_and_exact_readback(self):
        conn, cur = connection(self.snapshot)
        validate = MagicMock()
        self.assertEqual(module.write_replication_snapshot(conn, self.snapshot, validate_source=validate), 'sincronizado')
        self.assertEqual(validate.call_count, 2)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('presente_na_fonte=false' in sql for sql in statements))
        self.assertTrue(any('ON CONFLICT(fonte_id,nome_identidade,secao)' in sql for sql in statements))
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('DELETE', 'TRUNCATE')) for sql in statements))
        conn.commit.assert_not_called()

    def test_unchanged_content_only_refreshes_source_and_marker(self):
        marker = (NOW - timedelta(minutes=1), self.snapshot.digest, self.snapshot.config_hash)
        conn, cur = connection(self.snapshot, marker=marker)
        self.assertEqual(module.write_replication_snapshot(conn, self.snapshot, validate_source=lambda _: None), 'sem_alteracoes')
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any('SET presente_na_fonte=false' in sql for sql in statements))
        self.assertTrue(any('INSERT INTO operacional.sincronizacoes_replicacao_ad' in sql for sql in statements))

    def test_older_publication_or_capture_does_not_mutate_database(self):
        for source, marker, expected in (
                ((ZONE, self.snapshot.catalog.publication + timedelta(seconds=1), 'f' * 64), None,
                 'publicacao_mais_antiga_ignorada'),
                (None, (NOW + timedelta(seconds=1), self.snapshot.digest, self.snapshot.config_hash),
                 'captura_mais_antiga_ignorada')):
            conn, cur = connection(self.snapshot, source=source, marker=marker)
            self.assertEqual(module.write_replication_snapshot(conn, self.snapshot), expected)
            self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'DELETE')) for call in cur.execute.call_args_list))

    def test_same_timestamp_conflicts_and_config_change_block(self):
        for source, marker in (
                ((ZONE, self.snapshot.catalog.publication, 'f' * 64), None),
                ((None, self.snapshot.catalog.publication, self.snapshot.catalog.source_sha256), None),
                (None, (NOW, 'f' * 64, self.snapshot.config_hash)),
                (None, (NOW, self.snapshot.digest, 'f' * 64))):
            conn, cur = connection(self.snapshot, source=source, marker=marker)
            with self.assertRaises(module.SnapshotError):
                module.write_replication_snapshot(conn, self.snapshot)
            self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cur.execute.call_args_list))

    def test_row_or_error_readback_mismatch_blocks(self):
        for actual, errors in (([], None), (None, [])):
            conn, _ = connection(self.snapshot, actual=actual, errors=errors)
            with self.assertRaises(module.SnapshotError):
                module.write_replication_snapshot(conn, self.snapshot, validate_source=lambda _: None)
            conn.commit.assert_not_called()

    def test_source_change_before_or_after_write_blocks_marker(self):
        for effects in ([module.SnapshotError('Fonte mudou.')], [None, module.SnapshotError('Fonte mudou.')]):
            conn, cur = connection(self.snapshot)
            with self.assertRaises(module.SnapshotError):
                module.write_replication_snapshot(conn, self.snapshot, validate_source=MagicMock(side_effect=effects))
            self.assertFalse(any('INSERT INTO operacional.sincronizacoes_replicacao_ad' in call.args[0]
                                 for call in cur.execute.call_args_list))

    def test_wrong_identity_lock_busy_or_missing_bootstrap_blocks(self):
        for values in ([('other', 'other', 5432)], [IDENTITY, (False,)], [IDENTITY, (True,), None]):
            conn, cur = connection(self.snapshot)
            cur.fetchone.side_effect = values
            with self.assertRaises(module.SnapshotError):
                module.write_replication_snapshot(conn, self.snapshot)

    def test_reordered_rows_keep_identity_not_position(self):
        catalog = build(payload(servidores=[row(tipo='Destino'), row()]))
        snap = module.prepare_replication_snapshot(catalog, self.source, NOW)
        conn, cur = connection(snap)
        module.write_replication_snapshot(conn, snap, validate_source=lambda _: None)
        insertions = [call.args for call in cur.execute.call_args_list if call.args[0].startswith(
            'INSERT INTO operacional.observacoes_replicacao_ad')]
        self.assertEqual(insertions[0][1][4], 'Destino')
        self.assertTrue(all('ON CONFLICT(fonte_id,nome_identidade,secao)' in sql for sql, _ in insertions))

    def test_poller_is_disabled_by_default_and_outside_rigel(self):
        for computer, enabled in (('OTHER', True), ('RIGEL', False)):
            with patch.dict(os.environ, {'COMPUTERNAME': computer}), patch.object(module, 'shadow_enabled', return_value=enabled), \
                    patch.object(module, 'read_current_snapshot') as read:
                self.assertFalse(module.poll_replication_catalog(MagicMock()))
                read.assert_not_called()

    def test_poller_sql_failure_is_safe_and_never_changes_source(self):
        logger = MagicMock()
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                patch.object(module, 'shadow_enabled', return_value=True), \
                patch.object(module, '_InterprocessFileLock'), \
                patch.object(module, 'read_current_snapshot', return_value=self.snapshot), \
                patch.object(module, 'save_replication_publication'), \
                patch.object(module, 'connect_collector', side_effect=RuntimeError('SECRET_PRIVATE')):
            self.assertFalse(module.poll_replication_catalog(logger))
        self.assertNotIn('PRIVATE', str(logger.warning.call_args_list))

    def test_cli_capture_no_sql_and_digest_guard_before_connection(self):
        receipt = self.root / 'receipt.json'
        receipt.write_text('{}')
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(cli, '_InterprocessFileLock'), \
                patch.object(cli, 'read_current_snapshot', return_value=self.snapshot), \
                patch.object(cli, 'save_replication_publication'), patch.object(cli, 'connect_collector') as connect, \
                redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(['--capture', '--source-timezone', ZONE]), 0)
            connect.assert_not_called()
        self.assertNotIn('PRIVATE', out.getvalue())
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(cli, '_InterprocessFileLock'), \
                patch.object(cli, 'load_replication_publication', return_value=self.snapshot), \
                patch.object(cli, 'connect_collector') as connect, redirect_stderr(StringIO()):
            self.assertEqual(cli.main(['--publication', str(receipt), '--apply', '--expected-digest', 'wrong']), 1)
            connect.assert_not_called()

    def test_cli_wrong_host_or_timezone_override_fails_without_source_read(self):
        for computer, args in (('OTHER', ['--capture']), ('RIGEL', ['--source-timezone', ZONE])):
            with patch.dict(os.environ, {'COMPUTERNAME': computer}), patch.object(cli, 'read_current_snapshot') as read, \
                    redirect_stderr(StringIO()):
                self.assertEqual(cli.main(args), 1)
                read.assert_not_called()

    def test_cli_commit_failure_has_no_success_output(self):
        receipt = self.root / 'receipt.json'
        receipt.write_text('{}')
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(cli, '_InterprocessFileLock'), \
                patch.object(cli, 'load_replication_publication', return_value=self.snapshot), \
                patch.object(cli, 'write_replication_snapshot', return_value='sincronizado'), \
                patch.object(cli, 'connect_collector') as connect, \
                redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
            connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
            self.assertEqual(cli.main(['--publication', str(receipt), '--apply', '--expected-digest', self.snapshot.digest]), 1)
        self.assertEqual(out.getvalue(), '')
        self.assertNotIn('SECRET_PRIVATE', err.getvalue())

    def test_worker_singleton_no_request_path_dependency_or_network_commands(self):
        worker = MagicMock()
        worker.is_alive.return_value = True
        with patch.object(module, '_worker', worker):
            self.assertIs(module.start_replication_sync_worker(), worker)
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'subprocess', 'requests', 'socket', 'data_store'})
        startup = (module.PROJECT_ROOT / 'run_web_service.py').read_text(encoding='utf-8')
        self.assertIn('start_replication_sync_worker(app.logger)', startup)

    def test_migration_preserves_rows_and_restricted_access(self):
        sql = (module.PROJECT_ROOT / 'scripts/database/sql/020_replication_shadow_sync.sql').read_text()
        self.assertIn('ADD PRIMARY KEY (fonte_id,nome_identidade,secao)', sql)
        self.assertIn('TO sentinel_replicacao_reader', sql)
        self.assertNotIn('TO sentinel_reader', sql)
        self.assertNotIn('GRANT DELETE', sql)
        self.assertNotIn('TRUNCATE', sql)
        self.assertNotIn('DROP TABLE', sql)


if __name__ == '__main__':
    unittest.main()
