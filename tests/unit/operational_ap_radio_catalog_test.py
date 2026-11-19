from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import import_ap_radio_catalog as module
from scripts.database import capture_ap_radio_catalog as capture_module
from tests.unit.operational_ap_radio_capture_test import capture, payload, NOW

IDENTITY = ('sentinel', 'sentinel_collector', 5433)


def build():
    return module.build_catalog(capture_module._encode(capture()))


def connection(catalog, *, writing=False, counts=(0, 0, 0, 0), endpoint=('192.0.2.1', 8443),
               destination=True, readback=True):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [IDENTITY] + ([(True,)] if writing else []) + [endpoint] + [(value,) for value in counts]
    lists = [[('PRIVATE_SITE',)] if destination else [],
             [('00:11:22:33:44:55', 'PRIVATE_SITE')] if destination else []]
    lists += [list(rows) if readback else [] for rows in catalog.rows.values()]
    cursor.fetchall.side_effect = lists
    return conn, cursor


class ApRadioCatalogTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(module, 'datetime', wraps=datetime)
        self.clock = clock.start()
        self.clock.now.return_value = NOW + timedelta(days=1)
        self.addCleanup(clock.stop)

    def test_typed_rows_preserve_states_nulls_and_channel_types(self):
        catalog = build()
        self.assertEqual([len(rows) for rows in catalog.rows.values()], [1, 1, 2, 1])
        configs = catalog.rows['configuracoes_radios_unifi']
        self.assertEqual([row[6] for row in configs], [0, 'auto'])
        stats = catalog.rows['estatisticas_radios_unifi'][0]
        self.assertEqual(stats[8:10], (0, 'informado'))
        self.assertEqual(stats[-2:], (None, 'ausente'))
        receipt = catalog.rows['recebimentos_radios_unifi'][0]
        self.assertEqual(receipt[5:8], (None, False, False))
        self.assertNotIn('PRIVATE', repr(catalog))
        self.assertNotIn('SECRET_MARKER', repr(catalog.rows))

    def test_inspect_reads_all_tables_without_any_write_or_lock(self):
        catalog = build()
        conn, cursor = connection(catalog, readback=False)
        report = module.inspect_catalog(conn, catalog)
        self.assertTrue(report['destino_compativel'])
        self.assertTrue(report['tabelas_rf_conferidas'])
        self.assertTrue(report['tabelas_rf_vazias'])
        self.assertFalse(report['conteudo_confere_com_captura'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(all(sql.startswith(('SELECT ', 'SET ')) for sql in statements))
        self.assertTrue(any('READ ONLY' in sql for sql in statements))

    def test_loaded_readback_matches_full_source_receipts_config_and_stats(self):
        catalog = build()
        conn, _ = connection(catalog, counts=(1, 1, 2, 1))
        report = module.inspect_catalog(conn, catalog)
        self.assertFalse(report['tabelas_rf_vazias'])
        self.assertTrue(report['conteudo_confere_com_captura'])

    def test_writer_checks_target_and_readback_without_existing_updates(self):
        catalog = build()
        conn, cursor = connection(catalog, writing=True)
        module.write_catalog(conn, catalog)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(sum(sql.startswith('INSERT ') for sql in statements), 5)
        self.assertFalse(any(sql.startswith(('UPDATE ', 'DELETE ', 'TRUNCATE ', 'ALTER ')) for sql in statements))
        self.assertTrue(any('controladoras_unifi IN SHARE MODE' in sql for sql in statements))
        self.assertTrue(any('estatisticas_radios_unifi IN ROW EXCLUSIVE MODE' in sql for sql in statements))
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        inserts = [call for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO operacional.configuracoes')]
        self.assertEqual([call.args[1][6] for call in inserts], ['0', '"auto"'])
        self.assertTrue(all('%s::jsonb' in call.args[0] for call in inserts))
        conn.commit.assert_not_called()

    def test_wrong_identity_or_concurrent_import_blocks_before_inserts(self):
        for responses in ([('other', 'other', 5432)], [IDENTITY, (False,)]):
            conn, cursor = connection(build(), writing=True)
            cursor.fetchone.side_effect = responses
            with self.assertRaises((ValueError, module.ImportErrorSafe)):
                module.write_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT ') for call in cursor.execute.call_args_list))

    def test_populated_tables_or_target_divergence_never_rewrite_bindings(self):
        for options in ({'counts': (1, 0, 0, 0)}, {'counts': (0, 0, 1, 0)},
                        {'destination': False}, {'endpoint': None}, {'endpoint': ('other', 8443)}):
            catalog = build()
            conn, cursor = connection(catalog, writing=True, **options)
            with self.subTest(options=options), self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, catalog)
            self.assertFalse(any(call.args[0].startswith('INSERT ') for call in cursor.execute.call_args_list))

    def test_any_full_readback_mismatch_aborts_before_caller_commit(self):
        catalog = build()
        for index in range(4):
            conn, cursor = connection(catalog, writing=True)
            rows = [list(values) for values in catalog.rows.values()]
            rows[index] = []
            cursor.fetchall.side_effect = [[('PRIVATE_SITE',)], [('00:11:22:33:44:55', 'PRIVATE_SITE')], *rows]
            with self.subTest(table=index), self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, catalog)
            conn.commit.assert_not_called()

    def test_future_capture_blocks_write(self):
        frozen = capture_module.capture_payload(json.dumps(payload()).encode(), NOW + timedelta(days=2))
        catalog = module.build_catalog(capture_module._encode(frozen))
        conn, cursor = connection(catalog, writing=True)
        with self.assertRaises(module.ImportErrorSafe):
            module.write_catalog(conn, catalog)
        self.assertFalse(any(call.args[0].startswith('INSERT ') for call in cursor.execute.call_args_list))

    def test_cli_no_database_without_explicit_flag_and_output_redacted(self):
        raw = capture_module._encode(capture())
        with patch.object(Path, 'read_bytes', return_value=raw), patch(
                'services.operational_postgres.connect_collector') as connect, redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main(['--source', 'unused']), 0)
            connect.assert_not_called()
        self.assertFalse(json.loads(out.getvalue())['postgresql_acessado'])
        self.assertNotIn('PRIVATE', out.getvalue())

    def test_cli_machine_digest_corruption_and_changing_file_block_connection(self):
        raw = capture_module._encode(capture())
        for computer, digest in (('OTHER', build().digest), ('RIGEL', 'bad')):
            with patch.object(Path, 'read_bytes', return_value=raw), patch.dict('os.environ', {'COMPUTERNAME': computer}), patch(
                    'services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', digest]), 1)
                connect.assert_not_called()
        for data in ([raw, b'changed'], [b'{}']):
            with patch.object(Path, 'read_bytes', side_effect=data), patch(
                    'services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source', 'unused', '--check-database']), 1)
                connect.assert_not_called()

    def test_cli_write_success_only_after_commit_and_failure_has_no_raw_error(self):
        raw = capture_module._encode(capture())
        for failure in (False, True):
            with patch.object(Path, 'read_bytes', return_value=raw), patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), patch(
                    'services.operational_postgres.connect_collector') as connect, patch.object(module, 'write_catalog'), redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as error:
                if failure:
                    connect.return_value.__exit__.side_effect = RuntimeError('SECRET_MARKER')
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', build().digest]), int(failure))
                connect.assert_called_once_with(read_only=False)
            self.assertNotIn('SECRET_MARKER', out.getvalue() + error.getvalue())
            if failure:
                self.assertEqual(out.getvalue(), '')
            else:
                self.assertEqual(json.loads(out.getvalue())['modo'], 'carga_inicial_radios_unifi_confirmada')

    def test_cli_database_check_uses_readonly_and_does_not_write(self):
        with patch.object(Path, 'read_bytes', return_value=capture_module._encode(capture())), patch.dict(
                'os.environ', {'COMPUTERNAME': 'RIGEL'}), patch('services.operational_postgres.connect_collector') as connect, patch.object(
                module, 'inspect_catalog', return_value={'destino_compativel': True}), patch.object(module, 'write_catalog') as writer, redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main(['--source', 'unused', '--check-database']), 0)
            connect.assert_called_once_with(read_only=True)
            writer.assert_not_called()
        self.assertTrue(json.loads(out.getvalue())['vinculos_sql_conferidos'])

    def test_schema_keeps_tables_separate_restricted_and_original_schema_unchanged(self):
        sql = (module.ROOT / 'scripts/database/sql/027_unifi_radio_catalog.sql').read_text()
        for table in module.TABLE_COLUMNS:
            self.assertIn('CREATE TABLE operacional.' + table, sql)
        self.assertIn('REFERENCES operacional.aps_unifi(controladora_id, mac)', sql)
        self.assertIn('REFERENCES operacional.sites_unifi(controladora_id, id_origem)', sql)
        self.assertIn('CHECK (medido_em IS NULL)', sql)
        self.assertIn('CHECK (NOT data_medicao_confirmada)', sql)
        self.assertIn('TO sentinel_unifi_radios_reader', sql)
        self.assertIn('CURRENT_TIMESTAMP', sql)
        for forbidden in ('TO sentinel_reader', 'TO sentinel_api', 'GRANT UPDATE', 'GRANT DELETE',
                          'ALTER TABLE operacional.aps_unifi', 'UPDATE operacional.', 'DELETE FROM'):
            self.assertNotIn(forbidden, sql)
        self.assertEqual(sql.count('CREATE TABLE '), 4)


if __name__ == '__main__':
    unittest.main()
