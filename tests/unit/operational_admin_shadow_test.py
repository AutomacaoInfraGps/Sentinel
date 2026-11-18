import ast
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import sync_admin_catalog as cli
from scripts.database.import_admin_catalog import build_admin_catalog
from tests.unit.operational_admin_catalog_test import sources
import services.operational_admins as module

NOW = datetime(2026, 11, 18, 10, 5, tzinfo=timezone.utc)
ZONE = 'America/Sao_Paulo'


def snapshot(root, values=None, at=NOW):
    values = values or sources()
    catalog = build_admin_catalog(*(json.dumps(value).encode() for value in values), ZONE)
    return module.prepare_admin_snapshot(catalog, root / 'baseline.json', at)


def files(root, values=None):
    values = values or sources()
    (root / 'output').mkdir(exist_ok=True)
    for path, value in zip(('output/dashboard_admins_cache.json', 'baseline.json',
                            'output/dashboard_firewalls_cache.json', 'estrutura_regionais.json'), values):
        (root / path).write_text(json.dumps(value), encoding='utf-8')
    (root / 'environment.json').write_text(json.dumps({'fortianalyzer': {
        'admin_baseline_file': 'baseline.json'}, 'password': 'SECRET_PRIVATE'}), encoding='utf-8')


def connection(snap, marker=None, *, previous=None, source=None, actual=None):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433), (True,),
                                   source or (ZONE, snap.catalog.published_at, snap.catalog.hashes[0]), marker]
    changed = not marker or marker[1] != snap.digest
    lists = [[(code,) for code in snap.catalog.regional_codes]]
    if changed:
        lists.append(previous or [])
    lists += [[(row[0],) for row in snap.catalog.devices], list(snap.catalog.approved),
              list(snap.catalog.differences), list(snap.catalog.observed if actual is None else actual)]
    cursor.fetchall.side_effect = lists
    return conn, cursor


class AdminShadowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        files(self.root)
        self.snap = snapshot(self.root)

    def test_receipts_summary_and_repr_have_no_accounts_secrets_or_paths(self):
        encoded = json.dumps(self.snap.receipt()) + json.dumps(self.snap.summary()) + repr(self.snap)
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn('FGT_TEST', encoded)
        self.assertFalse(self.snap.summary()['contas_aprovadas_automaticamente'])

    def test_digest_ignores_capture_and_unrelated_monitoring_but_pins_baseline(self):
        self.assertEqual(self.snap.digest, snapshot(self.root, at=NOW + timedelta(minutes=5)).digest)
        values = sources()
        values[3]['regionais']['REG_TEST']['status'] = 'offline'
        values[2]['firewalls_por_regional']['REG_TEST'][0]['status'] = 'offline'
        self.assertEqual(self.snap.digest, snapshot(self.root, values).digest)
        other = module.prepare_admin_snapshot(self.snap.catalog, self.root / 'other.json', NOW)
        self.assertNotEqual(other.config_hash, self.snap.config_hash)

    def test_account_baseline_or_regional_binding_change_alters_digest(self):
        for index in range(3):
            values = sources()
            if index == 0:
                values[0]['dispositivos']['FGT_TEST']['admins'].append('OTHER_PRIVATE')
            elif index == 1:
                values[1]['FGT_TEST'].append('OTHER_PRIVATE')
            else:
                values[2]['firewalls_por_regional']['REG_TEST'][0]['nome'] = 'OTHER'
            self.assertNotEqual(snapshot(self.root, values).digest, self.snap.digest)

    def test_read_verify_and_receipt_never_write_sources_or_connect_sql(self):
        originals = {path: path.read_bytes() for path in self.root.rglob('*.json')}
        with patch.object(module, 'PROJECT_ROOT', self.root), patch.object(module, 'connect_collector') as connect:
            snap = module.read_current_snapshot(ZONE, NOW)
            module.verify_current(snap)
            connect.assert_not_called()
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    def test_explicit_timezone_required_or_read_from_config(self):
        with patch.object(module, 'PROJECT_ROOT', self.root), patch.object(module, 'CONFIG_PATH', self.root / 'flag.json'):
            (self.root / 'flag.json').write_text('{}')
            with self.assertRaises(module.SnapshotError):
                module.read_current_snapshot()
            (self.root / 'flag.json').write_text(json.dumps({'source_timezone': ZONE}))
            self.assertEqual(module.read_current_snapshot(captured_at=NOW).digest, self.snap.digest)

    def test_receipt_accepts_unrelated_catalog_changes_without_rewriting_frozen_receipt(self):
        path = self.root / 'receipt.json'
        module.save_admin_publication(self.snap, path)
        before = path.read_bytes()
        values = sources()
        values[3]['atualizado_em'] = '2026-11-18T07:02:00'
        files(self.root, values)
        with patch.object(module, 'PROJECT_ROOT', self.root):
            loaded = module.load_admin_publication(path)
            module.verify_current(self.snap)
        self.assertEqual(loaded.digest, self.snap.digest)
        self.assertNotEqual(loaded.catalog.hashes[3], self.snap.catalog.hashes[3])
        self.assertEqual(path.read_bytes(), before)

    def test_receipt_rejects_changed_baseline_cache_and_binding(self):
        path = self.root / 'receipt.json'
        module.save_admin_publication(self.snap, path)
        for index in range(3):
            values = sources()
            if index == 0:
                values[1]['FGT_TEST'].append('OTHER_PRIVATE')
            elif index == 1:
                values[0]['dispositivos']['FGT_TEST']['admins'].append('OTHER_PRIVATE')
            else:
                values[2]['firewalls_por_regional']['REG_TEST'][0]['nome'] = 'OTHER'
            files(self.root, values)
            with patch.object(module, 'PROJECT_ROOT', self.root), self.assertRaises(module.SnapshotError):
                module.load_admin_publication(path)

    def test_strict_receipt_shape_hashes_and_clock(self):
        path = self.root / 'receipt.json'
        for change in ('version', 'extra', 'hash', 'future'):
            receipt = self.snap.receipt()
            if change == 'version':
                receipt['version'] = True
            elif change == 'extra':
                receipt['admins'] = ['PRIVATE']
            elif change == 'hash':
                receipt['sha256_baseline'] = 'invalid'
            else:
                receipt['capturado_em'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            path.write_text(json.dumps(receipt))
            with self.subTest(change=change), self.assertRaises(module.SnapshotError):
                module.load_admin_publication(path)
        with self.assertRaises(module.SnapshotError):
            module.prepare_admin_snapshot(self.snap.catalog, 'source', NOW.replace(tzinfo=None))

    def test_atomic_receipt_failure_keeps_previous(self):
        path = self.root / 'receipt.json'
        module.save_admin_publication(self.snap, path)
        original = path.read_bytes()
        with patch.object(module.os, 'replace', side_effect=OSError), self.assertRaises(OSError):
            module.save_admin_publication(self.snap, path)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_writer_keeps_observations_baseline_separate_and_writes_marker_last(self):
        conn, cur = connection(self.snap)
        validate = MagicMock()
        self.assertEqual(module.write_admin_snapshot(conn, self.snap, validate_source=validate), 'sincronizado')
        self.assertEqual(validate.call_count, 2)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any(sql.startswith(('DELETE', 'TRUNCATE')) for sql in statements))
        self.assertTrue(statements[-1].startswith('INSERT INTO operacional.sincronizacoes_monitor_admins'))
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any('SHARE ROW EXCLUSIVE' in sql for sql in statements))
        approved_calls = [call.args[1] for call in cur.execute.call_args_list
                          if call.args[0].startswith('INSERT INTO operacional.baseline_admins_aprovada')]
        self.assertNotIn((module.SOURCE_ID, 'FGT_TEST', 'ACCOUNT_PRIVATE'), approved_calls)
        conn.commit.assert_not_called()

    def test_only_valid_timestamped_devices_can_mark_observed_accounts_absent(self):
        values = sources()
        for state in ({'consulta_valida': False, 'consulta_indisponivel': True},
                      {'consulta_valida': None}, {'ultima_coleta_valida': None}):
            current = deepcopy(values)
            current[0]['dispositivos']['FGT_TEST'].update(state)
            snap = snapshot(self.root, current)
            conn, cur = connection(snap)
            module.write_admin_snapshot(conn, snap, validate_source=lambda _: None)
            self.assertFalse(any(call.args[0].startswith('UPDATE operacional.contas_admins_observadas SET presente_na_fonte=false')
                                 for call in cur.execute.call_args_list))
        conn, cur = connection(self.snap)
        module.write_admin_snapshot(conn, self.snap, validate_source=lambda _: None)
        absences = [call for call in cur.execute.call_args_list if call.args[0].startswith(
            'UPDATE operacional.contas_admins_observadas SET presente_na_fonte=false')]
        self.assertEqual(len(absences), 1)
        self.assertEqual(absences[0].args[1], (module.SOURCE_ID, 'FGT_TEST'))

    def test_failed_query_preserves_extra_previously_known_accounts(self):
        values = sources()
        values[0]['dispositivos']['FGT_TEST'].update(consulta_valida=False, consulta_indisponivel=True, admins=[])
        snap = snapshot(self.root, values)
        actual = sorted((*snap.catalog.observed, ('FGT_TEST', 'OLD_PRIVATE', 'cache_sem_confirmacao_atual')))
        conn, _ = connection(snap, actual=actual)
        self.assertEqual(module.write_admin_snapshot(conn, snap, validate_source=lambda _: None), 'sincronizado')

    def test_valid_query_does_not_keep_extra_active_accounts(self):
        actual = sorted((*self.snap.catalog.observed, ('FGT_TEST', 'OLD_PRIVATE', 'cache_sem_confirmacao_atual')))
        conn, _ = connection(self.snap, actual=actual)
        with self.assertRaises(module.SnapshotError):
            module.write_admin_snapshot(conn, self.snap, validate_source=lambda _: None)

    def test_device_collection_cannot_regress(self):
        conn, _ = connection(self.snap, previous=[('FGT_TEST', NOW)])
        with self.assertRaises(module.SnapshotError):
            module.write_admin_snapshot(conn, self.snap, validate_source=lambda _: None)

    def test_unchanged_snapshot_advances_marker_without_rewriting_accounts(self):
        conn, cur = connection(self.snap, (NOW - timedelta(minutes=1), self.snap.digest, self.snap.config_hash))
        self.assertEqual(module.write_admin_snapshot(conn, self.snap, validate_source=lambda _: None), 'sem_alteracoes')
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any(sql.startswith('INSERT INTO operacional.baseline_admins_aprovada') for sql in statements))
        self.assertTrue(statements[-1].startswith('INSERT INTO operacional.sincronizacoes_monitor_admins'))

    def test_source_and_marker_monotonicity_and_path_pin(self):
        source = (ZONE, self.snap.catalog.published_at + timedelta(seconds=1), self.snap.catalog.hashes[0])
        conn, _ = connection(self.snap, source=source)
        self.assertEqual(module.write_admin_snapshot(conn, self.snap), 'cache_mais_antigo_ignorado')
        marker = (NOW + timedelta(seconds=1), self.snap.digest, self.snap.config_hash)
        conn, _ = connection(self.snap, marker)
        self.assertEqual(module.write_admin_snapshot(conn, self.snap), 'publicacao_mais_antiga_ignorada')
        for marker, source in (((NOW, 'other', self.snap.config_hash), None),
                               ((NOW, self.snap.digest, 'other'), None),
                               (None, (ZONE, self.snap.catalog.published_at, 'other')),
                               (None, ('UTC', self.snap.catalog.published_at, self.snap.catalog.hashes[0]))):
            conn, _ = connection(self.snap, marker, source=source)
            with self.assertRaises(module.SnapshotError):
                module.write_admin_snapshot(conn, self.snap)

    def test_second_validation_failure_does_not_write_success_marker(self):
        conn, cur = connection(self.snap)
        validate = MagicMock(side_effect=[None, module.SnapshotError('Changed')])
        with self.assertRaises(module.SnapshotError):
            module.write_admin_snapshot(conn, self.snap, validate_source=validate)
        self.assertFalse(any('INSERT INTO operacional.sincronizacoes_monitor_admins' in call.args[0]
                             for call in cur.execute.call_args_list))

    def test_identity_and_lock_failure_block(self):
        for responses in ([('other', 'user', 5432)], [('sentinel', 'sentinel_collector', 5433), (False,)]):
            conn, cur = connection(self.snap)
            cur.fetchone.side_effect = responses
            with self.assertRaises(ValueError):
                module.write_admin_snapshot(conn, self.snap)

    def test_read_only_inspection_does_not_write(self):
        conn, cur = connection(self.snap)
        cur.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433),
                                    (NOW, self.snap.digest, self.snap.config_hash), (3,), (2,), (2,), (1,)]
        result = module.inspect_admin_snapshot(conn, self.snap)
        self.assertTrue(result['conteudo_ja_sincronizado'])
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cur.execute.call_args_list))

    def test_disabled_or_wrong_machine_poll_does_not_read_sources_or_sql(self):
        for computer, enabled in (('OTHER', True), ('RIGEL', False)):
            with patch.dict(os.environ, {'COMPUTERNAME': computer}), patch.object(module, 'shadow_enabled', return_value=enabled), \
                    patch.object(module, 'read_current_snapshot') as read, patch.object(module, 'connect_collector') as connect:
                self.assertFalse(module.poll_admin_catalog(MagicMock()))
                read.assert_not_called()
                connect.assert_not_called()

    def test_poll_failure_is_safe_and_receipt_survives(self):
        logger = MagicMock()
        path = self.root / 'receipt.json'
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                patch.object(module, 'shadow_enabled', return_value=True), \
                patch.object(module, 'LOCK_PATH', self.root / 'lock'), patch.object(module, 'PUBLICATION_PATH', path), \
                patch.object(module, 'read_current_snapshot', return_value=self.snap), \
                patch.object(module, 'connect_collector', side_effect=RuntimeError('SECRET_PRIVATE')):
            self.assertFalse(module.poll_admin_catalog(logger))
        self.assertEqual(json.loads(path.read_text())['sha256_normalizado'], self.snap.digest)
        self.assertNotIn('PRIVATE', str(logger.mock_calls))

    def test_poll_success_commits_before_return(self):
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                patch.object(module, 'shadow_enabled', return_value=True), \
                patch.object(module, '_InterprocessFileLock'), patch.object(module, 'save_admin_publication'), \
                patch.object(module, 'read_current_snapshot', return_value=self.snap), \
                patch.object(module, 'write_admin_snapshot') as write, patch.object(module, 'connect_collector') as connect:
            self.assertTrue(module.poll_admin_catalog(MagicMock()))
            write.assert_called_once_with(connect.return_value.__enter__.return_value, self.snap)
            connect.return_value.__exit__.assert_called_once()

    def test_cli_capture_never_connects_and_default_only_inspects(self):
        path = self.root / 'receipt.json'
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                patch.object(cli, 'LOCK_PATH', self.root / 'lock'), \
                patch.object(cli, 'read_current_snapshot', return_value=self.snap), \
                patch.object(cli, 'load_admin_publication', return_value=self.snap), \
                patch.object(cli, 'connect_collector') as connect, \
                patch.object(cli, 'inspect_admin_snapshot', return_value={'modo': 'conferencia_sem_gravacao'}), \
                redirect_stdout(StringIO()):
            self.assertEqual(cli.main(['--capture', '--source-timezone', ZONE, '--publication', str(path)]), 0)
            connect.assert_not_called()
            self.assertEqual(cli.main(['--publication', str(path)]), 0)
            connect.assert_called_once_with(read_only=True)

    def test_cli_wrong_digest_wrong_host_and_fuso_override_block(self):
        path = self.root / 'receipt.json'
        module.save_admin_publication(self.snap, path)
        for computer, flags in (('OTHER', []), ('RIGEL', ['--apply', '--expected-digest', 'wrong']),
                                 ('RIGEL', ['--source-timezone', 'UTC'])):
            with patch.dict(os.environ, {'COMPUTERNAME': computer}), \
                    patch.object(cli, 'LOCK_PATH', self.root / 'lock'), \
                    patch.object(cli, 'load_admin_publication', return_value=self.snap), \
                    patch.object(cli, 'connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(cli.main(['--publication', str(path), *flags]), 1)
                connect.assert_not_called()

    def test_cli_commit_failure_has_no_success_output_or_private_error(self):
        path = self.root / 'receipt.json'
        module.save_admin_publication(self.snap, path)
        with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch.object(cli, 'LOCK_PATH', self.root / 'lock'), \
                patch.object(cli, 'load_admin_publication', return_value=self.snap), \
                patch.object(cli, 'write_admin_snapshot', return_value='sincronizado'), \
                patch.object(cli, 'connect_collector') as connect, redirect_stdout(StringIO()) as out, \
                redirect_stderr(StringIO()) as error:
            connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
            self.assertEqual(cli.main(['--publication', str(path), '--apply', '--expected-digest', self.snap.digest]), 1)
        self.assertEqual(out.getvalue(), '')
        self.assertNotIn('SECRET_PRIVATE', error.getvalue())

    def test_worker_starts_explicitly_only_once_and_runner_hook_is_in_main(self):
        with patch.object(module, '_worker', None), patch.object(module.threading, 'Thread') as thread:
            worker = module.start_admin_sync_worker(MagicMock())
            worker.is_alive.return_value = True
            self.assertIs(module.start_admin_sync_worker(MagicMock()), worker)
            thread.assert_called_once()
            worker.start.assert_called_once()
            self.assertEqual(module.POLL_SECONDS, 300)
        root = Path(__file__).resolve().parents[2]
        runner = ast.parse((root / 'run_web_service.py').read_text(encoding='utf-8-sig'))
        main = next(node for node in runner.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        self.assertTrue(any(isinstance(node, ast.Name) and node.id == 'start_admin_sync_worker' for node in ast.walk(main)))
        sql = (root / 'scripts/database/sql/017_admin_monitor_shadow_sync.sql').read_text()
        self.assertIn('FROM PUBLIC, sentinel_reader, sentinel_api', sql)
        self.assertNotIn('GRANT DELETE', sql)
        self.assertNotIn('TO sentinel_api', sql)


if __name__ == '__main__':
    unittest.main()
