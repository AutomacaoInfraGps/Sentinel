from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import sync_ap_radio_catalog as module
from scripts.database import capture_ap_radio_catalog as capture_module
from tests.unit.operational_ap_radio_capture_test import capture, payload, NOW


def build(original=None, minutes=0):
    frozen = capture_module.capture_payload(json.dumps(original or payload()).encode(), NOW + timedelta(minutes=minutes))
    return module.build_catalog(capture_module._encode(frozen))


def state(catalog, marker=False):
    return (catalog.rows['fontes_radios_unifi'][0], module._marker(catalog) if marker else None,
            {table: tuple((*row, True) for row in catalog.rows[table]) for table in module.RF_TABLES})


def updated():
    original = payload()
    received = NOW.isoformat()
    original['timestamp'] = '2026-11-19T14:01:00'
    original['aps'][0]['coletado_em'] = received
    original['aps'][0]['radios_nativos']['recebido_em'] = received
    original['sites'][0]['coletado_em'] = received
    return original


class ApRadioSyncTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(module, 'datetime', wraps=datetime)
        self.clock = clock.start()
        self.clock.now.return_value = NOW + timedelta(days=1)
        self.addCleanup(clock.stop)

    def report(self, before, catalog):
        return module._report(before, catalog, {'destino_compativel': True})

    def writer(self, before, catalog, *, after=None, destination=True):
        conn, cursor = MagicMock(), MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433), (True,)]
        after = after if after is not None else state(catalog, True)
        source = before[0]
        after = (source, after[1], after[2])
        with patch.object(module, '_state', side_effect=[before, after]), patch.object(
                module, 'destination_status', return_value={'destino_compativel': destination}):
            result = module.write_catalog(conn, catalog)
        return result, conn, cursor

    def test_initial_capture_initializes_only_marker_then_is_idempotent(self):
        catalog = build()
        report = self.report(state(catalog), catalog)
        self.assertTrue(report['conteudo_atual_confere'])
        self.assertFalse(report['conteudo_ja_sincronizado'])
        result, conn, cursor = self.writer(state(catalog), catalog)
        self.assertEqual(result, 'sincronizado')
        changes = [call.args[0] for call in cursor.execute.call_args_list if call.args[0].startswith(('INSERT ', 'UPDATE '))]
        self.assertEqual(len(changes), 1)
        self.assertIn('sincronizacoes_radios_unifi', changes[0])
        conn.commit.assert_not_called()
        result, _, cursor = self.writer(state(catalog, True), catalog)
        self.assertEqual(result, 'ja_sincronizado')
        self.assertFalse(any(call.args[0].startswith(('INSERT ', 'UPDATE ')) for call in cursor.execute.call_args_list))

    def test_new_capture_same_content_updates_only_receipt_marker(self):
        initial, new = build(), build(minutes=1)
        report = self.report(state(initial, True), new)
        self.assertTrue(report['conteudo_atual_confere'])
        self.assertFalse(report['conteudo_ja_sincronizado'])
        _, _, cursor = self.writer(state(initial, True), new)
        self.assertFalse(any(call.args[0].startswith('UPDATE ') for call in cursor.execute.call_args_list))

    def test_initialization_requires_exact_initial_capture_and_intact_rows(self):
        initial = build()
        with self.assertRaises(module.ImportErrorSafe):
            self.writer(state(initial), build(minutes=1))
        broken = state(initial)
        broken[2][module.RF_TABLES[1]] = ()
        self.assertTrue(self.report(broken, initial)['base_inicial_divergente'])
        with self.assertRaises(module.ImportErrorSafe):
            self.writer(broken, initial)

    def test_changed_snapshot_preserves_absent_rows_and_uses_typed_upserts(self):
        original = updated()
        original['aps'][0]['radios_nativos']['configuracoes']['registros'].pop()
        new = build(original, minutes=1)
        _, _, cursor = self.writer(state(build(), True), new)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(sum(sql.startswith('UPDATE ') for sql in statements), 3)
        self.assertTrue(all('presente_na_captura=false' in sql for sql in statements if sql.startswith('UPDATE ')))
        self.assertFalse(any(sql.startswith(('DELETE ', 'TRUNCATE ')) for sql in statements))
        self.assertFalse(any('INSERT INTO operacional.fontes_radios_unifi' in sql for sql in statements))
        configs = [call for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO operacional.configuracoes')]
        self.assertIn('%s::jsonb', configs[0].args[0])
        self.assertIn('ON CONFLICT', configs[0].args[0])
        self.assertTrue(any('aps_unifi IN SHARE MODE' in sql for sql in statements))

    def test_older_capture_future_capture_and_same_clock_conflict_block(self):
        initial = build()
        for previous, new in ((state(build(minutes=2), True), initial),
                              (state(initial, True), build(updated())),
                              (state(initial, True), build(minutes=3000))):
            with self.subTest(digest=new.digest), self.assertRaises(module.ImportErrorSafe):
                self.writer(previous, new)

    def test_same_received_time_cannot_change_metrics_and_old_received_is_blocked(self):
        original = payload()
        original['timestamp'] = '2026-11-19T14:01:00'
        stats = original['aps'][0]['radios_nativos']['estatisticas']['registros'][0]
        stats['cu_total'] = 3
        report = self.report(state(build(), True), build(original, minutes=1))
        self.assertEqual(report['aps_com_conflito_no_mesmo_recebimento'], 1)
        with self.assertRaises(module.ImportErrorSafe):
            self.writer(state(build(), True), build(original, minutes=1))
        report = self.report(state(build(updated(), minutes=1), True), build(minutes=2))
        self.assertEqual(report['aps_com_recebimento_mais_antigo'], 1)

    def test_publication_regression_timezone_change_and_same_publication_conflict(self):
        for old, new, old_hash, new_hash, flag in (
                ('2026-11-19T14:00:00', '2026-11-19T13:00:00', 'a', 'b', 'publicacao_mais_antiga'),
                ('2026-11-19T14:00:00', '2026-11-19T14:00:00Z', 'a', 'a', 'fuso_declarado_incompativel'),
                ('2026-11-19T14:00:00', '2026-11-19T14:00:00', 'a', 'b', 'conflito_mesma_publicacao')):
            self.assertTrue(module._publication_flags(old, new, old_hash, new_hash)[flag])

    def test_absence_not_deletion_and_reappearance_requires_new_received_time(self):
        initial = build()
        previous = state(initial, True)
        for table in module.RF_TABLES:
            previous[2][table] = tuple((*row[:-1], False) for row in previous[2][table])
        self.assertEqual(self.report(previous, build(minutes=1))['aps_com_conflito_no_mesmo_recebimento'], 1)
        report = self.report(previous, build(updated(), minutes=1))
        self.assertEqual(report['aps_com_conflito_no_mesmo_recebimento'], 0)
        self.assertEqual(report['banco_contagens_preservadas'][module.RF_TABLES[0]], 1)

    def test_target_mismatch_and_final_readback_mismatch_abort(self):
        initial = build()
        with self.assertRaises(module.ImportErrorSafe):
            self.writer(state(initial), initial, destination=False)
        with self.assertRaises(module.ImportErrorSafe):
            self.writer(state(initial), initial, after=state(initial))

    def test_real_inspection_query_path_is_read_only_and_redacted(self):
        initial = build()
        before = state(initial)
        conn, cursor = MagicMock(), MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [('sentinel', 'sentinel_collector', 5433), before[0], None, ('192.0.2.1', 8443)]
        cursor.fetchall.side_effect = [*before[2].values(), [('PRIVATE_SITE',)], [('00:11:22:33:44:55', 'PRIVATE_SITE')]]
        report = module.inspect_catalog(conn, initial)
        self.assertTrue(report['conteudo_atual_confere'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertTrue(all(call.args[0].startswith(('SELECT ', 'SET ')) for call in cursor.execute.call_args_list))

    def test_wrong_identity_or_busy_lock_prevents_writes(self):
        for responses in ([('other', 'other', 5432)], [('sentinel', 'sentinel_collector', 5433), (False,)]):
            conn, cursor = MagicMock(), MagicMock()
            conn.cursor.return_value.__enter__.return_value = cursor
            cursor.fetchone.side_effect = responses
            with self.assertRaises(ValueError):
                module.write_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT ') for call in cursor.execute.call_args_list))

    def test_cli_guards_machine_digest_and_changing_file(self):
        raw = capture_module._encode(capture())
        for machine, data, digest in (('OTHER', [raw, raw], build().digest),
                                      ('RIGEL', [raw, raw], 'bad'), ('RIGEL', [raw, b'changed'], build().digest)):
            with patch.dict('os.environ', {'COMPUTERNAME': machine}), patch.object(Path, 'read_bytes', side_effect=data), patch(
                    'services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', digest]), 1)
                connect.assert_not_called()

    def test_cli_readonly_default_and_commit_failure_no_success_or_secret(self):
        raw = capture_module._encode(capture())
        for apply in (False, True):
            with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), patch.object(Path, 'read_bytes', return_value=raw), patch(
                    'services.operational_postgres.connect_collector') as connect, patch.object(module, 'inspect_catalog', return_value={}), patch.object(
                    module, 'write_catalog', return_value='sincronizado'), redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as error:
                if apply:
                    connect.return_value.__exit__.side_effect = RuntimeError('SECRET_MARKER')
                args = ['--source', 'unused'] + (['--apply', '--expected-digest', build().digest] if apply else [])
                self.assertEqual(module.main(args), int(apply))
                connect.assert_called_once_with(read_only=not apply)
                self.assertNotIn('SECRET_MARKER', out.getvalue() + error.getvalue())
                if apply:
                    self.assertEqual(out.getvalue(), '')
                else:
                    self.assertEqual(json.loads(out.getvalue())['modo'], 'conferencia_sem_gravacao')

    def test_migration_does_not_change_source_or_ap_bindings_or_grant_delete(self):
        sql = (module.ROOT / 'scripts/database/sql/028_unifi_radio_shadow_sync.sql').read_text()
        self.assertIn('E:/Sentinel/PostgreSQL/data', sql)
        self.assertIn('SET LOCAL ROLE sentinel_owner', sql)
        self.assertEqual(sql.count('ALTER TABLE '), 3)
        self.assertIn('TO sentinel_unifi_radios_reader', sql)
        for forbidden in ('GRANT DELETE', 'ALTER TABLE operacional.aps_unifi', 'ALTER TABLE operacional.fontes_radios_unifi'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
