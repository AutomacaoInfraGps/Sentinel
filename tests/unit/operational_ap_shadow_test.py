import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import services.operational_ap_postgres as module
from scripts.database.sync_ap_catalog import main

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
REGIONS = {'regionais': {'REG_BAHIA': {'nome': 'Bahia', 'password': 'SECRET_PRIVATE'}}}


def payload(at=NOW):
    return {'controller': {'ip': '192.0.2.1', 'porta': 8443, 'password': 'SECRET_PRIVATE'},
            'timestamp': '2020-01-01T00:00:00',
            'sites': [{'id': 'SITE_PRIVATE', 'nome': 'V021_BAHIA', 'coletado_em': at.isoformat(),
                       'coleta_aps_confirmada': True, 'redes_wifi': [{'psk': 'SECRET_PRIVATE'}]}],
            'aps': [{'site_id': 'SITE_PRIVATE', 'site': 'V021_BAHIA', 'nome': 'AP_PRIVATE',
                     'mac': '00:11:22:33:44:55', 'ip': '198.51.100.1', 'modelo_codigo': 'uap',
                     'modelo': 'AP', 'firmware': '1.2.3', 'status': 'online', 'clientes': 1, 'uptime': 9,
                     'coletado_em': at.isoformat(), 'coleta_status_confirmada': True,
                     'password': 'SECRET_PRIVATE', 'vap_table': [{'psk': 'SECRET_PRIVATE'}]}]}


def snapshot(at=NOW):
    return module.prepare_ap_snapshot(payload(at), REGIONS, at + timedelta(seconds=1))


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class ApShadowTests(unittest.TestCase):
    def test_native_radio_extension_does_not_change_current_sql_projection(self):
        from services.unifi_radio_collection import ap_radio_evidence
        native = payload()
        original = module.prepare_ap_snapshot(native, REGIONS, NOW)
        native['aps'][0]['radios_nativos'] = ap_radio_evidence({
            'mac': native['aps'][0]['mac'],
            'radio_table_stats': [{'name': 'wifi0', 'cu_total': 0}],
        }, native['aps'][0]['site_id'], NOW.isoformat())
        extended = module.prepare_ap_snapshot(native, REGIONS, NOW)
        self.assertEqual(extended.digest, original.digest)
        self.assertEqual(extended.artifact, original.artifact)
        self.assertNotIn('radios_nativos', extended.artifact.decode())

    def test_projection_is_detached_typed_and_has_only_confirmed_clock(self):
        native = payload()
        before = deepcopy(native)
        result = module.prepare_ap_snapshot(native, REGIONS, NOW + timedelta(seconds=1))
        self.assertEqual(before, native)
        self.assertEqual(result.catalog.aps[0][11], NOW)
        self.assertEqual(result.sites[0][5], NOW)
        self.assertNotIn('SECRET_PRIVATE', result.artifact.decode())
        self.assertNotIn('PRIVATE', json.dumps(result.summary()))
        self.assertNotIn('PRIVATE', repr(result))
        self.assertNotIn('2020-01-01', result.artifact.decode())
        native['aps'][0]['status'] = 'offline'
        self.assertEqual(result.catalog.aps[0][8], 'online')

    def test_old_cache_unconfirmed_ap_or_site_never_becomes_new_evidence(self):
        for edit in ('missing_flag', 'ap_false', 'site_false', 'no_date', 'mismatch', 'future', 'invalid_site_id'):
            native = payload()
            if edit == 'missing_flag':
                native['aps'][0].pop('coleta_status_confirmada')
            elif edit == 'ap_false':
                native['aps'][0]['coleta_status_confirmada'] = False
            elif edit == 'site_false':
                native['sites'][0]['coleta_aps_confirmada'] = False
            elif edit == 'no_date':
                native['aps'][0]['coletado_em'] = None
            elif edit == 'mismatch':
                native['aps'][0]['coletado_em'] = (NOW - timedelta(seconds=1)).isoformat()
            elif edit == 'future':
                native = payload(NOW + timedelta(days=1))
            else:
                native['aps'][0]['site_id'] = []
            with self.subTest(edit=edit), self.assertRaises((ValueError, module.SnapshotError)):
                module.prepare_ap_snapshot(native, REGIONS, NOW)

    def test_digest_ignores_save_clock_but_covers_observations_and_bindings(self):
        first = snapshot()
        replay = module.prepare_ap_snapshot(payload(), REGIONS, NOW + timedelta(hours=1))
        self.assertEqual(first.digest, replay.digest)
        self.assertNotEqual(first.digest, snapshot(NOW + timedelta(seconds=1)).digest)
        unmapped = module.prepare_ap_snapshot(payload(), {'regionais': {'REG_OTHER': {}}}, NOW)
        self.assertNotEqual(first.digest, unmapped.digest)

    def test_site_move_keeps_ap_identity_and_unconfirmed_records_are_excluded(self):
        native = payload()
        original = snapshot().catalog.aps[0][:2]
        native['sites'].append(dict(native['sites'][0], id='second', nome='Other'))
        native['aps'][0]['site_id'] = 'second'
        native['aps'][0]['site'] = 'Other'
        native['aps'].append(dict(native['aps'][0], mac='00:11:22:33:44:66', coleta_status_confirmada=False))
        moved = module.prepare_ap_snapshot(native, REGIONS, NOW + timedelta(seconds=1))
        self.assertEqual(len(moved.catalog.aps), 1)
        self.assertEqual(moved.catalog.aps[0][:2], original)
        self.assertEqual(moved.catalog.aps[0][2], 'second')
        self.assertEqual(moved.summary()['aps_sem_regional'], 1)

    def test_checkpoint_round_trip_old_and_conflicting_publications_preserve_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'publication.json'
            first = snapshot()
            module.save_ap_publication(first, path)
            self.assertEqual(module.load_ap_publication(path).digest, first.digest)
            before = path.read_bytes()
            native = payload()
            native['aps'][0]['status'] = 'offline'
            conflicting = module.prepare_ap_snapshot(native, REGIONS, NOW + timedelta(seconds=3))
            with self.assertRaises(module.SnapshotError):
                module.save_ap_publication(conflicting, path)
            self.assertEqual(before, path.read_bytes())
            stale = module.prepare_ap_snapshot(payload(NOW - timedelta(seconds=1)), REGIONS, NOW + timedelta(seconds=4))
            with self.assertRaises(module.SnapshotError):
                module.save_ap_publication(stale, path)
            self.assertEqual(before, path.read_bytes())
            fresh = snapshot(NOW + timedelta(seconds=10))
            module.save_ap_publication(fresh, path)
            self.assertEqual(module.load_ap_publication(path).digest, fresh.digest)

    def test_checkpoint_atomic_replace_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'publication.json'
            module.save_ap_publication(snapshot(), path)
            before = path.read_bytes()
            with patch.object(module.os, 'replace', side_effect=OSError('PRIVATE')):
                with self.assertRaises(OSError):
                    module.save_ap_publication(snapshot(NOW + timedelta(seconds=10)), path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_publisher_saves_checkpoint_disabled_without_sql_and_guards_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regionals = root / 'regionals.json'
            regionals.write_text(json.dumps(REGIONS), encoding='utf-8')
            source, publication = root / 'unifi.json', root / 'publication.json'
            with patch.object(module, 'SOURCE_PATH', source), patch.object(module, 'PUBLICATION_PATH', publication), patch.object(module, 'REGIONALS_PATH', regionals), patch.object(module, 'shadow_enabled', return_value=False), patch.object(module, 'connect_collector') as connect:
                self.assertFalse(module.publish_ap_catalog(payload(), root / 'other.json', MagicMock()))
                self.assertFalse(publication.exists())
                self.assertTrue(module.publish_ap_catalog(payload(), source, MagicMock()))
                self.assertTrue(publication.exists())
                connect.assert_not_called()

    def test_enabled_publisher_writes_before_return_and_db_failure_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regionals = root / 'regionals.json'
            regionals.write_text(json.dumps(REGIONS), encoding='utf-8')
            source, publication = root / 'unifi.json', root / 'publication.json'
            with patch.object(module, 'SOURCE_PATH', source), patch.object(module, 'PUBLICATION_PATH', publication), patch.object(module, 'REGIONALS_PATH', regionals), patch.object(module, 'shadow_enabled', return_value=True), patch.object(module, 'connect_collector') as connect, patch.object(module, 'write_ap_snapshot') as write:
                self.assertTrue(module.publish_ap_catalog(payload(), source, MagicMock()))
                write.assert_called_once()
                self.assertTrue(publication.exists())
                connect.side_effect = RuntimeError('SECRET_PRIVATE')
                logger = MagicMock()
                self.assertFalse(module.publish_ap_catalog(payload(), source, logger))
                self.assertTrue(publication.exists())
                self.assertNotIn('SECRET_PRIVATE', str(logger.method_calls))

    def test_sql_upserts_bound_values_and_marks_after_ap_verification(self):
        snap = snapshot()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), ('192.0.2.1', 8443),
                                   ('V021_BAHIA', 'REG_BAHIA', 'identidade_normalizada_unica', None),
                                   None, (None,), (1,)], [[('REG_BAHIA',)]])
        self.assertEqual(module.write_ap_snapshot(conn, snap), 'sincronizado')
        calls = cursor.execute.call_args_list
        sql = [call.args[0] for call in calls]
        locks = [statement for statement in sql if statement.startswith('LOCK')]
        self.assertEqual(len(locks), 5)
        self.assertIn('operacional.regionais ', locks[0])
        self.assertIn('operacional.sincronizacoes_aps ', locks[-1])
        for call in calls:
            if len(call.args) == 2:
                self.assertEqual(call.args[0].count('%s'), len(call.args[1]))
            self.assertNotIn('PRIVATE', call.args[0])
        marker = next(i for i, statement in enumerate(sql) if statement.startswith('INSERT INTO operacional.sincronizacoes_aps'))
        verify = next(i for i, statement in enumerate(sql) if statement.startswith('SELECT count(*) FROM operacional.aps_unifi'))
        self.assertGreater(marker, verify)
        self.assertNotIn('SECRET_PRIVATE', repr(calls))
        self.assertFalse(any(word in statement for statement in sql for word in ('DELETE ', 'TRUNCATE ', 'presente_no_snapshot=false')))
        conn.commit.assert_not_called()

    def test_processed_and_older_ap_are_not_overwritten(self):
        snap = snapshot()
        for at, digest in ((NOW, module._row_digest(snap, snap.catalog.aps[0])),
                           (NOW + timedelta(seconds=10), 'newer')):
            site = (*snap.sites[0][2:5], at)
            conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), ('192.0.2.1', 8443),
                                       site, (at, digest)], [[('REG_BAHIA',)]])
            self.assertEqual(module.write_ap_snapshot(conn, snap), 'sem_alteracoes')
            self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cursor.execute.call_args_list))

    def test_conflicting_ap_or_site_and_wrong_endpoint_fail(self):
        snap = snapshot()
        for ones in ([('sentinel', 'sentinel_collector', 5433), ('other', 8443)],
                     [('sentinel', 'sentinel_collector', 5433), ('192.0.2.1', 8443),
                      ('wrong', 'REG_BAHIA', 'identidade_normalizada_unica', NOW)],
                     [('sentinel', 'sentinel_collector', 5433), ('192.0.2.1', 8443),
                      (*snap.sites[0][2:5], NOW), (NOW, 'different')]):
            conn, cursor = connection(ones, [[('REG_BAHIA',)]])
            with self.assertRaises(module.SnapshotError):
                module.write_ap_snapshot(conn, snap)
            self.assertFalse(any(call.args[0].startswith('INSERT INTO operacional.sincronizacoes_aps')
                                 for call in cursor.execute.call_args_list))

    def test_read_only_inspection_reports_current_subset_not_whole_inventory_freshness(self):
        snap = snapshot()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433),
                                   (NOW, module._row_digest(snap, snap.catalog.aps[0])), (216, 1)])
        result = module.inspect_ap_snapshot(conn, snap)
        self.assertTrue(result['conteudo_ja_sincronizado'])
        self.assertEqual(result['banco_aps'], 216)
        self.assertEqual(result['banco_aps_com_coleta_explicita'], 1)
        self.assertEqual(result['aps_pendentes_desta_publicacao'], 0)
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'LOCK')) for call in cursor.execute.call_args_list))

    def test_native_json_save_hook_only_after_successful_replace(self):
        path = Path(__file__).resolve().parents[2] / 'data_store.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'save_data')
        with tempfile.TemporaryDirectory() as directory:
            namespace = dict(json=json, os=os, tempfile=tempfile, datetime=datetime, Path=Path,
                             logging=logging, DATA_DIR=Path(directory))
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
            with patch.object(module, 'publish_ap_catalog') as publish:
                self.assertTrue(namespace['save_data']('other', {}))
                publish.assert_not_called()
                def check_file(payload, source, logger):
                    self.assertTrue(Path(source).is_file())
                publish.side_effect = check_file
                self.assertTrue(namespace['save_data']('unifi', {}))
                publish.assert_called_once()
                publish.reset_mock()
                publish.side_effect = RuntimeError('SECRET_PRIVATE')
                with patch.object(logging, 'getLogger', return_value=MagicMock()) as logger:
                    self.assertTrue(namespace['save_data']('unifi', {}))
                    self.assertTrue((Path(directory) / 'unifi.json').is_file())
                    self.assertNotIn('SECRET_PRIVATE', str(logger.return_value.method_calls))
                publish.reset_mock()
                with patch.object(os, 'replace', side_effect=OSError('failure')):
                    with self.assertRaises(OSError):
                        namespace['save_data']('unifi', {})
                publish.assert_not_called()

    def test_cli_guarded_hash_and_read_only_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'publication.json'
            module.save_ap_publication(snapshot(), path)
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch('scripts.database.sync_ap_catalog.connect_collector') as connect, patch('scripts.database.sync_ap_catalog.inspect_ap_snapshot', return_value={'modo': 'readonly'}), redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--publication', str(path)]), 0)
                connect.assert_called_once_with(read_only=True)
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch('scripts.database.sync_ap_catalog.connect_collector') as connect, redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--publication', str(path), '--apply', '--expected-digest', 'bad']), 1)
                connect.assert_not_called()

    def test_migration_least_privilege_and_instance_guard(self):
        path = Path(__file__).resolve().parents[2] / 'scripts/database/sql/011_ap_shadow_sync.sql'
        sql = path.read_text(encoding='utf-8')
        self.assertIn('SET LOCAL ROLE sentinel_owner', sql)
        self.assertIn("'E:/Sentinel/PostgreSQL/data'", sql)
        self.assertIn('PRIMARY KEY(controladora_id,mac)', sql)
        self.assertIn('GRANT UPDATE ON operacional.controladoras_unifi', sql)
        for text in ('GRANT ALL', 'TO PUBLIC', 'GRANT DELETE', 'GRANT CREATE'):
            self.assertNotIn(text, sql)


if __name__ == '__main__':
    unittest.main()
