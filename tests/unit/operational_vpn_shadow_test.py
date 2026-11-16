from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import operational_state
from scripts.database.sync_vpn_catalog import main
from services.operational_postgres import SnapshotError
from services import operational_vpn_postgres as vpn


REGIONS = {'regionais': {'REG_A': {'nome': 'PRIVATE_REGION', 'password': 'PRIVATE_SECRET'}}}


def record(**changes):
    return {'tunel': 'T1', 'firewall_serial': 'FGT_TEST', 'device': 'HUB',
            'device_namespace': 'fortigate_ssh:192.0.2.1', 'vdom': 'root',
            'vdom_origem': 'vdom_desabilitado', 'vpn_source': 'fortigate_ssh',
            'coletado_em': '2026-11-16T18:00:00+00:00', 'ultima_verificacao': '15:00:00',
            'regional': 'REG_A', 'status': 'online', 'interface': 'N/A',
            'password': 'PRIVATE_PASSWORD', 'comentario': 'PRIVATE_COMMENT', **changes}


def snapshot(**changes):
    return vpn.prepare_vpn_snapshot([record(**changes)], REGIONS)


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class VPNShadowTest(unittest.TestCase):
    def test_projection_is_detached_and_contains_no_comments_secrets_or_regional_names(self):
        item = record()
        original = vpn.prepare_vpn_snapshot([item], REGIONS)
        item['status'] = 'offline'
        self.assertEqual(original.rows[0][8], 'online')
        self.assertNotIn('PRIVATE', original.artifact.decode())
        self.assertNotIn('HUB', repr(original))
        self.assertNotIn('FGT_TEST', json.dumps(original.summary()))

    def test_collection_clock_is_not_map_publication_clock(self):
        item = record(updated_at='2026-11-17T20:00:00', changed_at='2026-11-17T20:00:00')
        original = vpn.prepare_vpn_snapshot([item], REGIONS)
        self.assertEqual(original.published_at, datetime(2026, 11, 16, 18, tzinfo=timezone.utc))
        self.assertEqual(original.digest, snapshot().digest)

    def test_digest_canonicalizes_typed_values_and_record_order(self):
        self.assertEqual(snapshot().digest, snapshot(coletado_em='2026-11-16T15:00:00-03:00',
                                                    interface=None).digest)
        first = vpn.prepare_vpn_snapshot([record(), record(tunel='T2')], REGIONS)
        second = vpn.prepare_vpn_snapshot([record(tunel='T2'), record()], REGIONS)
        self.assertEqual(first.digest, second.digest)

    def test_fallback_empty_missing_vdom_mixed_time_or_hub_fail_without_guessing(self):
        for records in ([], [record(vpn_source='fortimanager_proxy')], [record(vdom=None)],
                        [record(), record(tunel='T2', firewall_serial='OTHER')],
                        [record(), record(tunel='T2', coletado_em='2026-11-16T18:01:00Z')]):
            with self.subTest(records=records), self.assertRaises((SnapshotError, ValueError)):
                vpn.prepare_vpn_snapshot(records, REGIONS)

    def test_roundtrip_and_older_checkpoint_never_overwrites_newer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'vpn.json'
            original = snapshot()
            self.assertTrue(vpn.save_vpn_publication(original, path))
            self.assertEqual(vpn.load_vpn_publication(path).digest, original.digest)
            older = snapshot(coletado_em='2026-11-16T17:00:00Z')
            self.assertFalse(vpn.save_vpn_publication(older, path))
            self.assertEqual(vpn.load_vpn_publication(path).digest, original.digest)
            with self.assertRaises(SnapshotError):
                vpn.save_vpn_publication(snapshot(status='offline'), path)
            with self.assertRaises(SnapshotError):
                vpn.save_vpn_publication(snapshot(firewall_serial='OTHER'), path)

    def test_corrupt_checkpoint_does_not_become_empty_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'vpn.json'
            path.write_text('{}', encoding='utf-8')
            with self.assertRaises(SnapshotError):
                vpn.save_vpn_publication(snapshot(), path)
            self.assertEqual(path.read_text(), '{}')

    def test_writer_orders_locks_upserts_newer_only_and_marker_last(self):
        item = snapshot()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), None, (1,)],
                                  [[('REG_A',)], [('FGT_TEST', 'root')]])
        self.assertEqual(vpn.write_vpn_snapshot(conn, item), 'sincronizado')
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('operacional.regionais,operacional.vpns', statements[4])
        self.assertIn('INSERT INTO operacional.sincronizacoes_vpns', statements[-1])
        insertion = next(c for c in cursor.execute.call_args_list if 'INSERT INTO operacional.vpns AS' in c.args[0])
        self.assertEqual(insertion.args[0].count('%s'), len(insertion.args[1]))
        self.assertIn('WHERE EXCLUDED.coletado_em >= v.coletado_em', insertion.args[0])
        self.assertNotIn('PRIVATE', repr(cursor.execute.call_args_list))
        self.assertFalse(any(word in sql for sql in statements for word in ('DELETE ', 'TRUNCATE ', 'presente_no_snapshot=false')))
        conn.commit.assert_not_called()

    def test_same_digest_or_older_collection_skip_inserts(self):
        item = snapshot()
        for marker, mode in (((item.published_at, item.digest), 'sem_alteracoes'),
                             ((datetime(2027, 1, 1, tzinfo=timezone.utc), 'other'), 'coleta_antiga_ignorada')):
            conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), marker])
            self.assertEqual(vpn.write_vpn_snapshot(conn, item), mode)
            self.assertFalse(any('INSERT' in c.args[0] for c in cursor.execute.call_args_list))

    def test_same_time_conflict_wrong_database_missing_regional_or_changed_hub_fail(self):
        item = snapshot()
        for ones, lists in (
            ([('aegis', 'sentinel_collector', 5432)], []),
            ([('sentinel', 'sentinel_collector', 5433), (item.published_at, 'other')], []),
            ([('sentinel', 'sentinel_collector', 5433), None], [[]]),
            ([('sentinel', 'sentinel_collector', 5433), None], [[('REG_A',)], [('OTHER', 'root')]])):
            conn, cursor = connection(ones, lists)
            with self.assertRaises(SnapshotError):
                vpn.write_vpn_snapshot(conn, item)
            self.assertFalse(any('INSERT' in c.args[0] for c in cursor.execute.call_args_list))

    def test_bad_final_count_does_not_write_marker(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), None, (0,)],
                                  [[('REG_A',)], [('FGT_TEST', 'root')]])
        with self.assertRaises(SnapshotError):
            vpn.write_vpn_snapshot(conn, snapshot())
        self.assertFalse(any('INSERT INTO operacional.sincronizacoes' in c.args[0]
                             for c in cursor.execute.call_args_list))

    def test_inspection_is_read_only(self):
        item = snapshot()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433),
                                   (item.published_at, item.digest), (1, 0)])
        report = vpn.inspect_vpn_snapshot(conn, item)
        self.assertTrue(report['conteudo_ja_sincronizado'])
        self.assertIn('READ ONLY', cursor.execute.call_args_list[0].args[0])

    def test_flag_disabled_still_checkpoints_but_never_connects_or_enqueues(self):
        with patch.object(vpn, '_load', return_value=REGIONS), \
                patch.object(vpn, 'save_vpn_publication', return_value=True) as save, \
                patch.object(vpn, 'shadow_enabled', return_value=False), \
                patch.object(vpn._worker, 'submit') as submit, \
                patch.object(vpn, 'connect_collector') as connect:
            self.assertTrue(vpn.publish_vpn_records([record()], vpn.STATE_PATH, MagicMock()))
            save.assert_called_once()
            submit.assert_not_called()
            connect.assert_not_called()

    def test_enabled_enqueues_only_global_valid_publications_and_safe_logs(self):
        logger = MagicMock()
        with patch.object(vpn, '_load', return_value=REGIONS), \
                patch.object(vpn, 'save_vpn_publication', return_value=True), \
                patch.object(vpn, 'shadow_enabled', return_value=True), \
                patch.object(vpn._worker, 'submit') as submit:
            self.assertTrue(vpn.publish_vpn_records([record()], vpn.STATE_PATH, logger))
            submit.assert_called_once()
            self.assertFalse(vpn.publish_vpn_records([record()], Path('user-filtered.json'), logger))
            self.assertFalse(vpn.publish_vpn_records([record(vdom=None)], vpn.STATE_PATH, logger))
            self.assertNotIn('PRIVATE', repr(logger.warning.call_args_list))
            self.assertEqual(submit.call_count, 1)

    def test_native_group_and_map_hooks_run_after_successful_write_only(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(operational_state, '_publish_vpn_shadow') as hook:
            path = Path(folder) / 'state.json'
            def verify(records, target):
                self.assertEqual(json.loads(target.read_text())['groups']['vpns']['records'], records)
            hook.side_effect = verify
            operational_state.publish_group_records('vpns', [record()], source='vpn_manual', path=path)
            self.assertEqual(hook.call_count, 1)
            operational_state.publish_group_records('switches', [], path=path)
            self.assertEqual(hook.call_count, 1)
            operational_state.publish_map_snapshot({'regionais': [{'codigo': 'REG_A', 'vpns': [record()]}]}, path=path)
            self.assertEqual(hook.call_count, 2)
            with patch.object(operational_state, '_write_atomic', side_effect=OSError()):
                with self.assertRaises(OSError):
                    operational_state.publish_group_records('vpns', [record()], path=path)
            self.assertEqual(hook.call_count, 2)

    def test_hook_failure_does_not_undo_native_cache(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(vpn, 'publish_vpn_records', side_effect=RuntimeError('PRIVATE')):
            path = Path(folder) / 'state.json'
            result = operational_state.publish_group_records('vpns', [record()], path=path)
            self.assertEqual(result['records'][0]['tunel'], 'T1')
            self.assertTrue(path.exists())

    def test_worker_checks_flag_again_and_logs_no_driver_details(self):
        for enabled in (False, True):
            worker = vpn.VPNShadowWorker()
            logger = MagicMock()
            worker.pending = MagicMock()
            worker.pending.get.side_effect = [(snapshot(), logger), StopIteration()]
            with patch.object(vpn, 'shadow_enabled', return_value=enabled), \
                    patch.object(vpn, 'connect_collector', side_effect=RuntimeError('PRIVATE_PASSWORD')) as connect:
                with self.assertRaises(StopIteration):
                    worker._run()
                self.assertEqual(connect.call_count, int(enabled))
                self.assertNotIn('PRIVATE', repr(logger.warning.call_args_list))
                worker.pending.task_done.assert_called_once()

    def test_cli_default_is_readonly_and_digest_guard_precedes_connection(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}):
            path = Path(folder) / 'vpn.json'
            vpn.save_vpn_publication(snapshot(), path)
            with patch('scripts.database.sync_vpn_catalog.connect_collector') as connect, \
                    patch('scripts.database.sync_vpn_catalog.inspect_vpn_snapshot', return_value={}), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--publication', str(path)]), 0)
                connect.assert_called_once_with(read_only=True)
                connect.reset_mock()
                self.assertEqual(main(['--publication', str(path), '--apply', '--expected-digest', 'wrong']), 1)
                connect.assert_not_called()

    def test_cli_apply_uses_write_connection_and_reviewed_digest(self):
        item = snapshot()
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}):
            path = Path(folder) / 'vpn.json'
            vpn.save_vpn_publication(item, path)
            with patch('scripts.database.sync_vpn_catalog.connect_collector') as connect, \
                    patch('scripts.database.sync_vpn_catalog.write_vpn_snapshot', return_value='sincronizado') as write, \
                    redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--publication', str(path), '--apply',
                                       '--expected-digest', item.digest]), 0)
                connect.assert_called_once_with(read_only=False)
                write.assert_called_once()
                self.assertEqual(json.loads(output.getvalue())['modo'], 'sincronizado')

    def test_migration_keeps_reader_readonly_and_scopes_marker_by_hub_vdom(self):
        sql = (Path(__file__).resolve().parents[2] / 'scripts/database/sql/007_vpn_shadow_sync.sql').read_text()
        self.assertIn('PRIMARY KEY (firewall_serial, vdom)', sql)
        self.assertIn('GRANT UPDATE ON operacional.vpns TO sentinel_collector', sql)
        self.assertNotIn('GRANT ALL', sql)
        self.assertNotIn('DELETE', sql)


if __name__ == '__main__':
    unittest.main()
