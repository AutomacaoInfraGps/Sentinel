from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gerenciar_switches import GerenciadorSwitches
from scripts.database.sync_switch_cache import main as sync_main
from services.operational_postgres import SnapshotError
from services.operational_switch_postgres import (
    CONFIG_PATH, PROJECT_ROOT, SwitchShadowWorker, inspect_switch_snapshot,
    load_switch_publication, prepare_switch_snapshot, publish_switch_cache,
    save_switch_publication, write_switch_snapshot,
)


NOW = datetime(2026, 11, 16, 15, tzinfo=timezone.utc)


def cache():
    return {'Switch A': {'hostid': '100', 'regional': 'REG_A', 'status': 'online',
                         'ultima_verificacao': '2026-11-16T11:30:00',
                         'warning_problemas': ['PRIVATE_WARNING'], 'password': 'PRIVATE_PASSWORD'}}


def regionals():
    return {'regionais': {'REG_A': {'nome': 'Regional A', 'senha': 'PRIVATE_REGION'}}}


def snapshot(full=True, moment=NOW):
    return prepare_switch_snapshot(cache(), regionals(), moment, full)


class Cursor:
    def __init__(self, current=None, counts=(1, 0), matched=1, fail=None, codes=('REG_A',)):
        self.current, self.counts, self.matched = current, counts, matched
        self.fail, self.codes, self.calls = fail, codes, []
        self.result, self.rows = None, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.fail and self.fail in sql:
            raise RuntimeError('PRIVATE_DRIVER')
        if sql.startswith('SELECT current_database'):
            self.result = ('sentinel', 'sentinel_collector', 5433)
        elif sql.startswith('SELECT publicado_em'):
            self.result = self.current
        elif sql.startswith('SELECT codigo'):
            self.rows = [(code,) for code in self.codes]
        elif 'unnest(' in sql:
            self.result = (self.matched,)
        elif sql.startswith('SELECT count(*)'):
            self.result = self.counts

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.rows


def connection(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class SwitchShadowTest(unittest.TestCase):
    def test_snapshot_and_artifact_are_detached_and_secret_free(self):
        source = cache()
        snap = prepare_switch_snapshot(source, regionals(), NOW, True)
        source['Switch A']['status'] = 'offline'
        self.assertEqual(snap.rows[0][15], 'online')
        self.assertNotIn('PRIVATE', snap.artifact.decode())
        self.assertNotIn('Switch A', repr(snap))
        self.assertEqual(snap.rows[0][22], 1)
        self.assertEqual(snap.rows[0][16].hour, 14)

    def test_unknown_regional_stays_null(self):
        source = cache()
        source['Switch A']['regional'] = 'UNMATCHED'
        snap = prepare_switch_snapshot(source, regionals(), NOW, True)
        self.assertIsNone(snap.rows[0][5])
        self.assertEqual(snap.summary()['vinculos_na_publicacao'], {'nao_encontrado': 1})

    def test_requires_aware_publication_explicit_mode_and_nonempty_cache(self):
        for moment, full in ((NOW.replace(tzinfo=None), True), (NOW, 1), (None, False)):
            with self.assertRaises(SnapshotError):
                prepare_switch_snapshot(cache(), regionals(), moment, full)
        with self.assertRaises(ValueError):
            prepare_switch_snapshot({}, regionals(), NOW, True)

    def test_round_trip_stable_and_older_checkpoint_cannot_replace_new(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'publication.json'
            newer = snapshot(moment=NOW + timedelta(seconds=1))
            self.assertTrue(save_switch_publication(newer, target))
            self.assertEqual(load_switch_publication(target).digest, newer.digest)
            self.assertFalse(save_switch_publication(snapshot(), target))
            self.assertEqual(load_switch_publication(target).digest, newer.digest)

    def test_conflicting_same_time_checkpoint_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'publication.json'
            save_switch_publication(snapshot(), target)
            changed = cache()
            changed['Switch A']['status'] = 'offline'
            with self.assertRaises(SnapshotError):
                save_switch_publication(prepare_switch_snapshot(changed, regionals(), NOW, True), target)

    def test_invalid_control_not_treated_as_empty_success(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'publication.json'
            target.write_text('{}')
            with self.assertRaises(SnapshotError):
                load_switch_publication(target)

    def test_incremental_never_marks_unobserved_switches_absent(self):
        cursor = Cursor(counts=(166, 26))
        self.assertEqual(write_switch_snapshot(connection(cursor), snapshot(full=False)), 'sincronizado')
        self.assertFalse(any('SET presente_no_snapshot=false' in sql for sql, _ in cursor.calls))
        self.assertFalse(any('DELETE' in sql or 'TRUNCATE' in sql for sql, _ in cursor.calls))

    def test_full_inventory_marks_absent_and_publishes_marker_last(self):
        cursor = Cursor()
        self.assertEqual(write_switch_snapshot(connection(cursor), snapshot()), 'sincronizado')
        statements = [sql for sql, _ in cursor.calls]
        self.assertTrue(any('SET presente_no_snapshot=false' in sql for sql in statements))
        self.assertTrue(statements[-1].startswith('INSERT INTO operacional.sincronizacoes_switches'))
        insertion = next((sql, params) for sql, params in cursor.calls if sql.startswith('INSERT INTO operacional.switches AS'))
        self.assertEqual(insertion[0].count('%s'), len(insertion[1]))
        self.assertIn('EXCLUDED.ultima_verificacao >= s.ultima_verificacao', insertion[0])
        self.assertIn('maintenance_status=CASE WHEN', insertion[0])
        self.assertNotIn('PRIVATE', repr(cursor.calls))

    def test_old_or_identical_publication_does_not_write(self):
        snap = snapshot()
        for current, expected in (((NOW, snap.digest), 'sem_alteracoes'),
                                  ((NOW + timedelta(seconds=1), 'other'), 'publicacao_antiga_ignorada')):
            cursor = Cursor(current=current)
            self.assertEqual(write_switch_snapshot(connection(cursor), snap), expected)
            self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE')) for sql, _ in cursor.calls))

    def test_conflict_bad_counts_or_regional_mismatch_cannot_publish_marker(self):
        for cursor in (Cursor(current=(NOW, 'other')), Cursor(matched=0),
                       Cursor(counts=(2, 0)), Cursor(codes=()),
                       Cursor(fail='INSERT INTO operacional.switches AS')):
            with self.assertRaises((SnapshotError, RuntimeError)):
                write_switch_snapshot(connection(cursor), snapshot())
            self.assertFalse(any(sql.startswith('INSERT INTO operacional.sincronizacoes_switches')
                                 for sql, _ in cursor.calls))

    def test_inspect_is_read_only_and_no_lock_or_write(self):
        snap = snapshot()
        cursor = Cursor(current=(NOW, snap.digest))
        result = inspect_switch_snapshot(connection(cursor), snap)
        self.assertTrue(result['conteudo_ja_sincronizado'])
        self.assertIn('READ ONLY', cursor.calls[0][0])
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'LOCK')) for sql, _ in cursor.calls))

    def test_hook_captures_real_save_even_with_sql_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'regions.json').write_text(json.dumps(regionals()))
            with patch('services.operational_switch_postgres.CACHE_PATH', root / 'cache.json'), \
                    patch('services.operational_switch_postgres.REGIONAL_PATH', root / 'regions.json'), \
                    patch('services.operational_switch_postgres.save_switch_publication', return_value=True) as save, \
                    patch('services.operational_switch_postgres.shadow_enabled', return_value=False), \
                    patch('services.operational_switch_postgres._worker') as worker:
                self.assertTrue(publish_switch_cache(cache(), root / 'cache.json', NOW, True, MagicMock()))
                self.assertNotIn('PRIVATE', save.call_args.args[0].artifact.decode())
                worker.submit.assert_not_called()

    def test_noncanonical_path_does_not_read_write_or_connect(self):
        with patch('services.operational_switch_postgres.save_switch_publication') as save:
            self.assertFalse(publish_switch_cache(cache(), PROJECT_ROOT / 'other.json', NOW, True, MagicMock()))
            save.assert_not_called()

    def test_real_cache_save_preserves_local_only_and_legacy_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = GerenciadorSwitches.__new__(GerenciadorSwitches)
            manager.status_cache_file = Path(folder) / 'cache.json'
            manager.status_cache_file.write_text(json.dumps({'Lab': {'local_only': True, 'status': 'online'}}))

            def checkpoint(data, path, moment, full, logger):
                saved = json.loads(Path(path).read_text())
                self.assertIn('Lab', saved)
                self.assertIn('Switch A', saved)
                self.assertNotIn('published_at', saved)
                self.assertTrue(data['Lab']['local_only'])
                self.assertTrue(full)
                self.assertIsNotNone(moment.utcoffset())

            with patch('services.operational_switch_postgres.publish_switch_cache', side_effect=checkpoint) as hook:
                manager._salvar_status_cache(cache(), full_inventory=True)
                hook.assert_called_once()

    def test_checkpoint_error_does_not_break_original_save(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = GerenciadorSwitches.__new__(GerenciadorSwitches)
            manager.status_cache_file = Path(folder) / 'cache.json'
            with patch('services.operational_switch_postgres.publish_switch_cache', side_effect=RuntimeError('PRIVATE')), \
                    self.assertLogs('gerenciar_switches', level='WARNING') as logs:
                manager._salvar_status_cache(cache())
            self.assertIn('Switch A', json.loads(manager.status_cache_file.read_text()))
            self.assertNotIn('PRIVATE', str(logs.output))

    def test_failed_original_replace_never_invokes_hook(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = GerenciadorSwitches.__new__(GerenciadorSwitches)
            manager.status_cache_file = Path(folder) / 'cache.json'
            with patch('gerenciar_switches.os.replace', side_effect=OSError('failure')), \
                    patch('services.operational_switch_postgres.publish_switch_cache') as hook, \
                    patch('gerenciar_switches.print'):
                manager._salvar_status_cache(cache())
                hook.assert_not_called()

    def test_worker_disabled_skips_sql_and_failure_has_safe_log(self):
        for enabled in (True, False):
            worker = SwitchShadowWorker()
            worker.pending = MagicMock()
            logger = MagicMock()
            worker.pending.get.side_effect = [(snapshot(), logger), SystemExit()]
            with patch('services.operational_switch_postgres.shadow_enabled', return_value=enabled), \
                    patch('services.operational_switch_postgres.connect_collector') as connect, \
                    patch('services.operational_switch_postgres.write_switch_snapshot', side_effect=RuntimeError('PRIVATE')):
                with self.assertRaises(SystemExit):
                    worker._run()
                if enabled:
                    self.assertNotIn('PRIVATE', repr(logger.warning.call_args))
                else:
                    connect.assert_not_called()
                worker.pending.task_done.assert_called_once()

    def test_new_flag_disabled_and_migration_grants_update_for_lock(self):
        sql = (PROJECT_ROOT / 'scripts/database/sql/005_switch_shadow_sync.sql').read_text()
        self.assertIn('GRANT UPDATE ON operacional.switches TO sentinel_collector', sql)
        self.assertNotIn('GRANT DELETE', sql)
        example = PROJECT_ROOT / 'scripts/database/operational-postgres-switches-shadow.example.json'
        self.assertIs(json.loads(example.read_text())['enabled'], False)
        self.assertNotEqual(CONFIG_PATH.name, 'operational-postgres-shadow.json')

    def test_cli_default_only_reads_database_and_apply_requires_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'publication.json'
            path.write_bytes(snapshot().artifact)
            conn = connection(Cursor())
            conn.__enter__.return_value = conn
            with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), \
                    patch('scripts.database.sync_switch_cache.connect_collector', return_value=conn) as connect:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(sync_main(['--publication', str(path)]), 0)
                self.assertEqual(json.loads(output.getvalue())['modo'], 'conferencia_sem_gravacao')
                connect.assert_called_once_with(read_only=True)
                connect.reset_mock()
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(sync_main(['--publication', str(path), '--apply',
                                                '--expected-digest', 'wrong']), 1)
                connect.assert_not_called()

    def test_cli_missing_publication_and_wrong_machine_never_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'missing.json'
            for machine in ('RIGEL', 'OTHER'):
                with patch.dict('os.environ', {'COMPUTERNAME': machine}), \
                        patch('scripts.database.sync_switch_cache.connect_collector') as connect, \
                        redirect_stderr(io.StringIO()):
                    self.assertEqual(sync_main(['--publication', str(path)]), 1)
                    connect.assert_not_called()

    def test_cli_connection_failure_sanitized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'publication.json'
            path.write_bytes(snapshot().artifact)
            with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), \
                    patch('scripts.database.sync_switch_cache.connect_collector',
                          side_effect=RuntimeError('PRIVATE_PASSWORD')):
                output = io.StringIO()
                with redirect_stderr(output):
                    self.assertEqual(sync_main(['--publication', str(path)]), 1)
                self.assertIn('conexao', output.getvalue())
                self.assertNotIn('PRIVATE', output.getvalue())


if __name__ == '__main__':
    unittest.main()
