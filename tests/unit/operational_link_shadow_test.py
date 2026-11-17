from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gerenciar_regionais import GerenciadorRegionais
from scripts.database.sync_link_catalog import main
from services import operational_link_postgres as links
from services.operational_postgres import SnapshotError


CAPTURE = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def record(**changes):
    return {'id': '1', 'nome': 'WAN', 'interface_monitorada': 'wan1',
            'fortigate_host': '192.0.2.1', 'status': 'online',
            'origem_sync': 'fortimanager_config+proxy_monitor',
            'modo_verificacao': 'monitor_zabbix_packet_loss', 'packet_loss_percent': 0,
            'ultima_verificacao': '2026-11-18T12:00:00',
            'coletado_em': '2026-11-17T11:00:00Z', 'coleta_status_confirmada': True,
            'coleta_status_origem': 'sdwan_monitor', 'password': 'PRIVATE',
            'sla_data': {'token': 'PRIVATE'}, **changes}


def payload(records=None, code='REG_A'):
    return {'regionais': {code: {'nome': 'PRIVATE', 'links': [{'password': 'PRIVATE'}],
                                 'links_internet_auto': [record()] if records is None else records}}}


def snapshot(**changes):
    return links.prepare_link_snapshot(payload([record(**changes)]), CAPTURE)


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class LinkShadowTest(unittest.TestCase):
    def test_typed_whitelist_clock_and_detachment(self):
        source = payload()
        item = links.prepare_link_snapshot(source, CAPTURE)
        source['regionais']['REG_A']['links_internet_auto'][0]['status'] = 'offline'
        self.assertNotIn('PRIVATE', item.artifact.decode())
        self.assertEqual(item.rows[0][12], 'online')
        self.assertEqual(item.rows[0][21], item.rows[0][22])
        self.assertEqual(item.rows[0][22].isoformat(), '2026-11-17T11:00:00+00:00')
        self.assertFalse(item.rows[0][23])
        self.assertNotIn('192.0.2.1', repr(item))

    def test_no_new_observation_from_legacy_fallback_or_missing_flags(self):
        for changes in ({'coleta_status_confirmada': False}, {'coleta_status_confirmada': None},
                        {'origem_sync': 'fallback_local'}, {'coletado_em': None},
                        {'coleta_status_origem': 'guess'}):
            with self.assertRaises(ValueError):
                snapshot(**changes)
        mixed = links.prepare_link_snapshot(payload([record(), record(id='2', coleta_status_confirmada=False)]), CAPTURE)
        self.assertEqual(len(mixed.rows), 1)

    def test_stale_sla_metric_not_carried_into_interface_observation(self):
        item = snapshot(modo_verificacao='interface', coleta_status_origem='proxy_interface',
                        link_mode_status='online', packet_loss_percent=100)
        self.assertIsNone(item.rows[0][20])

    def test_atomic_roundtrip_merge_regions_and_do_not_drop_absent_links(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.json'
            first = snapshot()
            links.save_link_publication(first, path)
            other = links.prepare_link_snapshot(payload(code='REG_B'), CAPTURE)
            merged = links.save_link_publication(other, path)
            self.assertEqual(len(merged.rows), 2)
            self.assertEqual(links.load_link_publication(path).digest, merged.digest)
            self.assertEqual(set(merged.regional_codes), {'REG_A', 'REG_B'})
            older = snapshot(coletado_em='2026-11-16T11:00:00Z', status='offline')
            self.assertEqual(links.save_link_publication(older, path).rows[0][12], 'online')
            with self.assertRaises(SnapshotError):
                links.save_link_publication(snapshot(status='offline'), path)

    def test_corrupt_checkpoint_and_bad_source_path_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.json'
            path.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                links.save_link_publication(snapshot(), path)
        with patch.object(links, 'save_link_publication') as save:
            self.assertFalse(links.publish_link_catalog(payload(), Path('filtered-user.json'), MagicMock()))
            save.assert_not_called()

    def test_disabled_still_checkpoints_without_sql_and_enabled_enqueues(self):
        for enabled in (False, True):
            with patch.object(links, 'save_link_publication', side_effect=lambda item: item) as save, \
                    patch.object(links, 'shadow_enabled', return_value=enabled), \
                    patch.object(links._worker, 'submit') as submit, \
                    patch.object(links, 'connect_collector') as connect:
                self.assertTrue(links.publish_link_catalog(payload(), links.CATALOG_PATH, MagicMock()))
                self.assertEqual(submit.call_count, int(enabled))
                save.assert_called_once()
                connect.assert_not_called()

    def test_writer_bound_values_order_and_marker_after_link(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), None, (1,)], [[('REG_A',)]])
        self.assertEqual(links.write_link_snapshot(conn, snapshot()), 'sincronizado')
        sql = [c.args[0] for c in cursor.execute.call_args_list]
        self.assertIn('operacional.regionais,operacional.links_internet', sql[4])
        self.assertIn('INSERT INTO operacional.sincronizacoes_links', sql[-1])
        insertion = next(c for c in cursor.execute.call_args_list if 'INSERT INTO operacional.links_internet AS' in c.args[0])
        self.assertEqual(insertion.args[0].count('%s'), len(insertion.args[1]))
        self.assertIn('EXCLUDED.coletado_em >= l.coletado_em', insertion.args[0])
        self.assertNotIn('PRIVATE', repr(cursor.execute.call_args_list))
        self.assertFalse(any(word in s for s in sql for word in ('DELETE ', 'TRUNCATE ', 'presente_no_snapshot=false')))
        conn.commit.assert_not_called()

    def test_same_marker_or_newer_observation_skips_link(self):
        item = snapshot()
        for marker in ((item.rows[0][22], links._row_digest(item.rows[0])),
                       (datetime(2027, 1, 1, tzinfo=timezone.utc), 'other')):
            conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), marker], [[('REG_A',)]])
            self.assertEqual(links.write_link_snapshot(conn, item), 'sem_alteracoes')
            self.assertFalse(any('INSERT' in c.args[0] for c in cursor.execute.call_args_list))

    def test_conflicting_marker_missing_region_bad_count_or_wrong_instance_fails(self):
        item = snapshot()
        for ones, lists in (([('aegis', 'sentinel_collector', 5432)], []),
                            ([('sentinel', 'sentinel_collector', 5433)], [[]]),
                            ([('sentinel', 'sentinel_collector', 5433), (item.rows[0][22], 'other')], [[('REG_A',)]]),
                            ([('sentinel', 'sentinel_collector', 5433), None, (0,)], [[('REG_A',)]])):
            conn, cursor = connection(ones, lists)
            with self.assertRaises(ValueError):
                links.write_link_snapshot(conn, item)
            self.assertFalse(any('INSERT INTO operacional.sincronizacoes_links' in c.args[0]
                                 for c in cursor.execute.call_args_list))

    def test_inspection_reports_per_link_coverage_not_global_freshness(self):
        item = snapshot()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433),
                                   (item.rows[0][22], links._row_digest(item.rows[0])), (88, 1)])
        report = links.inspect_link_snapshot(conn, item)
        self.assertTrue(report['conteudo_ja_sincronizado'])
        self.assertEqual(report['banco_links_com_coleta_explicita'], 1)
        self.assertEqual(report['links_processados_desta_publicacao'], 1)
        self.assertIn('READ ONLY', cursor.execute.call_args_list[0].args[0])

    def test_native_hook_after_successful_replace_and_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'regionais.json'
            manager = GerenciadorRegionais(str(target))
            manager.regionais = payload()
            def fail_after_save(data, path, logger):
                self.assertEqual(json.loads(target.read_text())['regionais']['REG_A']['links_internet_auto'][0]['id'], '1')
                raise RuntimeError('PRIVATE')
            with patch.object(links, 'publish_link_catalog', side_effect=fail_after_save), \
                    self.assertLogs('gerenciar_regionais', level='WARNING') as logs:
                manager.salvar_regionais()
            self.assertNotIn('PRIVATE', str(logs.output))
            with patch('gerenciar_regionais.os.replace', side_effect=OSError()), \
                    patch.object(links, 'publish_link_catalog') as publish:
                with self.assertRaises(OSError):
                    manager.salvar_regionais()
                publish.assert_not_called()

    def test_worker_flag_and_safe_failure_logging(self):
        for enabled in (False, True):
            worker, logger = links.LinkShadowWorker(), MagicMock()
            worker.pending = MagicMock()
            worker.pending.get.side_effect = [(snapshot(), logger), StopIteration()]
            with patch.object(links, 'shadow_enabled', return_value=enabled), \
                    patch.object(links, 'connect_collector', side_effect=RuntimeError('PRIVATE')) as connect:
                with self.assertRaises(StopIteration):
                    worker._run()
                self.assertEqual(connect.call_count, int(enabled))
                self.assertNotIn('PRIVATE', repr(logger.warning.call_args_list))

    def test_bounded_queue_merges_regions_and_never_loses_pending_newer_observations(self):
        worker = links.LinkShadowWorker()
        worker.started = True
        worker.submit(snapshot(), MagicMock())
        other = links.prepare_link_snapshot(payload(code='REG_B'), CAPTURE)
        worker.submit(other, MagicMock())
        worker.submit(snapshot(coletado_em='2026-11-16T12:00:00Z', status='offline'), MagicMock())
        self.assertEqual(worker.pending.qsize(), 1)
        pending, _ = worker.pending.get_nowait()
        worker.pending.task_done()
        self.assertEqual(len(pending.rows), 2)
        self.assertTrue(all(row[12] == 'online' for row in pending.rows))

    def test_cli_default_readonly_and_hash_guard_precedes_connection(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}):
            path = Path(folder) / 'links.json'
            links.save_link_publication(snapshot(), path)
            with patch('scripts.database.sync_link_catalog.connect_collector') as connect, \
                    patch('scripts.database.sync_link_catalog.inspect_link_snapshot', return_value={}), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--publication', str(path)]), 0)
                connect.assert_called_once_with(read_only=True)
                connect.reset_mock()
                self.assertEqual(main(['--publication', str(path), '--apply', '--expected-digest', 'wrong']), 1)
                connect.assert_not_called()

    def test_migration_is_least_privilege_and_marker_is_per_link(self):
        sql = (Path(__file__).resolve().parents[2] / 'scripts/database/sql/009_link_shadow_sync.sql').read_text()
        self.assertIn('PRIMARY KEY (codigo_regional, id_origem)', sql)
        self.assertIn('GRANT UPDATE ON operacional.links_internet TO sentinel_collector', sql)
        self.assertNotIn('GRANT ALL', sql)
        self.assertNotIn('GRANT DELETE', sql)


if __name__ == '__main__':
    unittest.main()
