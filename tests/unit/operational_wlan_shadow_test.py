import ast
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import services.operational_wlan_postgres as module
from scripts.database.sync_wlan_catalog import main

NOW = datetime(2026, 11, 17, 15, tzinfo=timezone.utc)
REGIONS = {'regionais': {'REG_BAHIA': {'nome': 'Bahia', 'password': 'SECRET_PRIVATE'}}}


def payload(at=NOW):
    return {'controller': {'ip': '192.0.2.1', 'porta': 8443, 'password': 'SECRET_PRIVATE'},
            'sites': [{'id': 'site1', 'nome': 'V021_BAHIA', 'coleta_wlans_confirmada': True,
                       'wlans_situacao': 'confirmada', 'wlans_coletadas_em': at.isoformat(),
                       'wlans_configuradas': [{'wlan_id': 'wlan1', 'nome': 'SSID_PRIVATE',
                           'networkconf_id': 'net1', 'ativo': True, 'bandas': ['2g', '5g'],
                           'coletado_em': at.isoformat(), 'origem': 'configuracao_unifi',
                           'x_passphrase': 'SECRET_PRIVATE'}]}]}


def snapshot(at=NOW):
    return module.prepare_wlan_snapshot(payload(at), REGIONS, at + timedelta(seconds=1))


PARENTS = {'controladora_compativel': True, 'regionais_do_catalogo_ausentes_no_banco': 0,
           'sites_ausentes_no_banco': 0, 'sites_com_nome_divergente': 0, 'sites_com_regional_divergente': 0}


def connection(rows):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433), *rows]
    return conn, cursor


class WlanShadowTest(unittest.TestCase):
    def test_projection_does_not_mutate_or_leak_secrets(self):
        native = payload()
        before = deepcopy(native)
        snap = module.prepare_wlan_snapshot(native, REGIONS, NOW)
        self.assertEqual(before, native)
        self.assertNotIn('SECRET_PRIVATE', snap.artifact.decode())
        self.assertNotIn('PRIVATE', json.dumps(snap.summary()))
        self.assertNotIn('PRIVATE', repr(snap))
        self.assertEqual(snap.catalog.rows[0][7], NOW)
        native['sites'][0]['wlans_configuradas'][0]['bandas'].append('6g')
        self.assertEqual(snap.catalog.rows[0][6], ('2g', '5g'))

    def test_digest_uses_real_collection_not_capture_time(self):
        self.assertEqual(snapshot().digest, module.prepare_wlan_snapshot(payload(), REGIONS, NOW).digest)
        self.assertNotEqual(snapshot().digest, snapshot(NOW + timedelta(seconds=2)).digest)

    def test_unconfirmed_sites_are_excluded_not_treated_as_empty(self):
        native = payload()
        native['sites'].append({'id': 'bad', 'coleta_wlans_confirmada': False})
        self.assertEqual(module.prepare_wlan_snapshot(native, REGIONS, NOW).digest, snapshot().digest)
        native['sites'][0]['coleta_wlans_confirmada'] = False
        with self.assertRaises(ValueError):
            module.prepare_wlan_snapshot(native, REGIONS, NOW)

    def test_invalid_or_future_evidence_is_rejected(self):
        for change in ('future', 'mismatch', 'duplicate', 'no_id', 'bad_active', 'no_zone'):
            native = payload()
            site = native['sites'][0]
            wlan = site['wlans_configuradas'][0]
            if change == 'future':
                native = payload(NOW + timedelta(seconds=2))
            elif change == 'mismatch':
                wlan['coletado_em'] = (NOW - timedelta(seconds=1)).isoformat()
            elif change == 'duplicate':
                site['wlans_configuradas'].append(dict(wlan))
            elif change == 'no_id':
                wlan.pop('wlan_id')
            elif change == 'bad_active':
                wlan['ativo'] = 'true'
            else:
                site['wlans_coletadas_em'] = '2026-11-17T15:00:00'
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.prepare_wlan_snapshot(native, REGIONS, NOW)

    def test_same_name_is_not_an_identity_and_unknown_regional_stays_null(self):
        native = payload()
        native['sites'][0]['wlans_configuradas'].append(dict(native['sites'][0]['wlans_configuradas'][0], wlan_id='wlan2'))
        snap = module.prepare_wlan_snapshot(native, {'regionais': {'REG_OTHER': {}}}, NOW)
        self.assertEqual(len(snap.catalog.rows), 2)
        self.assertEqual(snap.summary()['wlans_sem_regional'], 2)

    def test_checkpoint_roundtrip_conflicts_and_endpoint_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pub.json'
            module.save_wlan_publication(snapshot(), path)
            before = path.read_bytes()
            self.assertEqual(module.load_wlan_publication(path).digest, snapshot().digest)
            for change in ('old', 'conflict', 'endpoint'):
                native = payload(NOW - timedelta(seconds=1) if change == 'old' else NOW)
                if change == 'conflict':
                    native['sites'][0]['wlans_configuradas'][0]['ativo'] = False
                if change == 'endpoint':
                    native['controller']['ip'] = '192.0.2.2'
                snap = module.prepare_wlan_snapshot(native, REGIONS, NOW + timedelta(seconds=3))
                with self.subTest(change=change), self.assertRaises(module.SnapshotError):
                    module.save_wlan_publication(snap, path)
                self.assertEqual(path.read_bytes(), before)
            with patch.object(module.os, 'replace', side_effect=OSError):
                with self.assertRaises(OSError):
                    module.save_wlan_publication(snapshot(NOW + timedelta(seconds=5)), path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_writer_parameters_and_verification_before_marker(self):
        snap = snapshot()
        conn, cursor = connection([None, None, (1,)])
        with patch.object(module, '_inspect_parents', return_value=PARENTS):
            self.assertEqual(module.write_wlan_snapshot(conn, snap), 'sincronizado')
        calls = cursor.execute.call_args_list
        sql = [call.args[0] for call in calls]
        self.assertEqual(sum(statement.startswith('LOCK') for statement in sql), 5)
        self.assertLess(next(i for i, s in enumerate(sql) if s.startswith('SELECT count(*)')),
                        next(i for i, s in enumerate(sql) if s.startswith('INSERT INTO operacional.sincronizacoes_wlans')))
        insert = next(call for call in calls if call.args[0].startswith('INSERT INTO operacional.wlans_unifi'))
        self.assertIsInstance(insert.args[1][6], list)
        for call in calls:
            self.assertNotIn('DELETE', call.args[0])
            self.assertNotIn('SSID_PRIVATE', call.args[0])
            if len(call.args) == 2:
                self.assertEqual(call.args[0].count('%s'), len(call.args[1]))
        conn.commit.assert_not_called()

    def test_idempotence_older_observations_and_conflicts(self):
        snap = snapshot()
        digest = module._row_digest(snap, snap.catalog.rows[0])
        for marker in ((NOW, digest), (NOW + timedelta(seconds=1), 'other')):
            conn, cursor = connection([marker])
            with patch.object(module, '_inspect_parents', return_value=PARENTS):
                self.assertEqual(module.write_wlan_snapshot(conn, snap), 'sem_alteracoes')
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cursor.execute.call_args_list))
        conn, cursor = connection([(NOW, 'conflicting')])
        with patch.object(module, '_inspect_parents', return_value=PARENTS), self.assertRaises(module.SnapshotError):
            module.write_wlan_snapshot(conn, snap)

    def test_bootstrap_same_clock_checked_and_newer_row_preserved(self):
        snap = snapshot()
        row = snap.catalog.rows[0]
        conn, cursor = connection([None, (*row[:7], NOW + timedelta(seconds=1), row[8])])
        with patch.object(module, '_inspect_parents', return_value=PARENTS):
            self.assertEqual(module.write_wlan_snapshot(conn, snap), 'sem_alteracoes')
        conn, cursor = connection([None, (*row[:5], False, *row[6:])])
        with patch.object(module, '_inspect_parents', return_value=PARENTS), self.assertRaises(module.SnapshotError):
            module.write_wlan_snapshot(conn, snap)

    def test_parent_divergence_blocks_before_inserting(self):
        conn, cursor = connection([])
        with patch.object(module, '_inspect_parents', return_value={**PARENTS, 'sites_com_regional_divergente': 1}), self.assertRaises(module.SnapshotError):
            module.write_wlan_snapshot(conn, snapshot())
        self.assertFalse(any(call.args[0].startswith('INSERT') for call in cursor.execute.call_args_list))

    def test_inspection_read_only_reports_processed_and_pending(self):
        snap = snapshot()
        conn, cursor = connection([(NOW, module._row_digest(snap, snap.catalog.rows[0])), (188, 188)])
        with patch.object(module, '_inspect_parents', return_value=PARENTS):
            result = module.inspect_wlan_snapshot(conn, snap)
        self.assertTrue(result['conteudo_ja_sincronizado'])
        self.assertEqual(result['wlans_pendentes_desta_publicacao'], 0)
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'DELETE', 'LOCK')) for call in cursor.execute.call_args_list))

    def test_publisher_disabled_never_connects_and_failure_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regions = root / 'regions.json'
            regions.write_text(json.dumps(REGIONS), encoding='utf-8')
            source, publication = root / 'unifi.json', root / 'pub.json'
            prepared = snapshot()
            with patch.object(module, 'REGIONALS_PATH', regions), patch.object(module, 'SOURCE_PATH', source), patch.object(module, 'PUBLICATION_PATH', publication), patch.object(module, 'shadow_enabled', return_value=False) as enabled, patch.object(module, 'connect_collector') as connect:
                with patch.object(module, 'prepare_wlan_snapshot', return_value=prepared):
                    self.assertFalse(module.publish_wlan_catalog(payload(), root / 'other.json', MagicMock()))
                    self.assertTrue(module.publish_wlan_catalog(payload(), source, MagicMock()))
                    connect.assert_not_called()
                    enabled.return_value = True
                    connect.side_effect = RuntimeError('SECRET_PRIVATE')
                    logger = MagicMock()
                    self.assertFalse(module.publish_wlan_catalog(payload(), source, logger))
                    self.assertTrue(publication.exists())
                    self.assertNotIn('SECRET_PRIVATE', str(logger.method_calls))

    def test_cli_wrong_digest_blocks_before_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pub.json'
            module.save_wlan_publication(snapshot(), path)
            with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), patch('scripts.database.sync_wlan_catalog.connect_collector') as connect, redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--publication', str(path), '--apply', '--expected-digest', 'wrong']), 1)
                connect.assert_not_called()

    def test_json_hook_runs_after_replace_even_if_ap_hook_fails(self):
        root = Path(__file__).resolve().parents[2]
        path = root / 'data_store.py'
        function = next(node for node in ast.parse(path.read_text(encoding='utf-8-sig')).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'save_data')
        with tempfile.TemporaryDirectory() as directory:
            namespace = dict(json=json, os=os, tempfile=tempfile, datetime=datetime,
                             logging=logging, DATA_DIR=Path(directory))
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
            with patch('services.operational_ap_postgres.publish_ap_catalog', side_effect=RuntimeError), patch.object(module, 'publish_wlan_catalog') as publish, patch.object(logging, 'getLogger', return_value=MagicMock()):
                namespace['save_data']('other', {})
                publish.assert_not_called()
                publish.side_effect = lambda payload, source, logger: self.assertTrue(Path(source).is_file())
                self.assertTrue(namespace['save_data']('unifi', {}))
                publish.assert_called_once()
                publish.reset_mock()
                with patch.object(os, 'replace', side_effect=OSError), self.assertRaises(OSError):
                    namespace['save_data']('unifi', {})
                publish.assert_not_called()

    def test_cli_read_only_and_commit_failure_never_report_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pub.json'
            snap = snapshot()
            module.save_wlan_publication(snap, path)
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch('scripts.database.sync_wlan_catalog.connect_collector') as connect, patch('scripts.database.sync_wlan_catalog.inspect_wlan_snapshot', return_value={}), redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--publication', str(path)]), 0)
                connect.assert_called_once_with(read_only=True)
            output = io.StringIO()
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch('scripts.database.sync_wlan_catalog.connect_collector') as connect, patch('scripts.database.sync_wlan_catalog.write_wlan_snapshot', return_value='sincronizado'), redirect_stdout(output), redirect_stderr(io.StringIO()):
                connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                self.assertEqual(main(['--publication', str(path), '--apply', '--expected-digest', snap.digest]), 1)
                self.assertEqual(output.getvalue(), '')

    def test_migration_guards_and_no_delete_privileges(self):
        path = Path(__file__).resolve().parents[2] / 'scripts/database/sql/013_wlan_shadow_sync.sql'
        sql = path.read_text(encoding='utf-8')
        self.assertIn('SET LOCAL ROLE sentinel_owner', sql)
        self.assertIn("'E:/Sentinel/PostgreSQL/data'", sql)
        self.assertIn('PRIMARY KEY(controladora_id,site_id,id_origem)', sql)
        for forbidden in ('GRANT ALL', 'TO PUBLIC', 'GRANT DELETE', 'GRANT CREATE'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
