from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database.import_firewall_cache import ImportErrorSafe
from scripts.database.import_switch_catalog import (
    SOURCE, build_switch_catalog, inspect_switch_catalog, main, write_switch_catalog,
)


def cache():
    return {'Switch A': {'hostid': '100', 'regional': 'TLSV POA', 'ip': '192.0.2.1',
                         'modelo': 'Model', 'is_core': True, 'em_manutencao': False,
                         'status': 'warning', 'ultima_verificacao': '2026-11-16T11:00:00',
                         'warning_problemas': ['PRIVATE_WARNING'],
                         'password': 'PRIVATE_PASSWORD', 'token': 'PRIVATE_TOKEN'}}


def regionals():
    return {'regionais': {'REG_TLSV_POA': {'nome': 'TLSV POA', 'senha': 'PRIVATE_REGIONAL'}}}


def raw(value):
    return json.dumps(value).encode()


def build(records=None, regions=None):
    return build_switch_catalog(raw(records if records is not None else cache()),
                                raw(regions if regions is not None else regionals()), 'America/Sao_Paulo')


def connection(counts, lists=()):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = counts
    cursor.fetchall.side_effect = lists
    return conn, cursor


class SwitchCatalogTest(unittest.TestCase):
    def test_projection_typed_and_never_exports_secrets_or_warning_text(self):
        catalog = build()
        self.assertEqual(catalog.rows[0][0:2], ('zabbix', '100'))
        self.assertEqual(catalog.rows[0][5], 'REG_TLSV_POA')
        self.assertEqual(catalog.rows[0][16], datetime(2026, 11, 16, 14, tzinfo=timezone.utc))
        self.assertEqual(catalog.rows[0][22], 1)
        self.assertNotIn('PRIVATE', repr(catalog.rows))
        self.assertNotIn('Switch A', repr(catalog))
        self.assertFalse(catalog.summary()['sincronizacao_automatica_switches'])

    def test_ambiguous_missing_and_unmatched_regionals_are_null(self):
        regions = {'regionais': {'REG_TLSV_POA': {'nome': 'TLSV POA'},
                                 'REG_OTHER': {'nome': 'TLSV POA'}}}
        self.assertEqual(build(regions=regions).rows[0][5:8], (None, 'TLSV POA', 'ambiguo'))
        records = cache()
        records['Switch A']['regional'] = 'POA'
        self.assertEqual(build(records).rows[0][7], 'nao_encontrado')
        records['Switch A']['regional'] = None
        self.assertEqual(build(records).rows[0][7], 'ausente')

    def test_code_exact_alias_and_accent_normalization_without_partial_matching(self):
        records = cache()
        records['Switch A']['regional'] = 'regional TLSV-POA'
        self.assertEqual(build(records).rows[0][5], 'REG_TLSV_POA')
        records['Switch A']['regional'] = 'TLSV POA extra'
        self.assertIsNone(build(records).rows[0][5])

    def test_duplicate_and_missing_ids_fail_without_discarding(self):
        records = cache()
        records['Switch B'] = deepcopy(records['Switch A'])
        with self.assertRaises(ImportErrorSafe):
            build(records)
        for hostid in (None, '', '0', '001', 'abc', True):
            records = cache()
            records['Switch A']['hostid'] = hostid
            with self.subTest(hostid=hostid), self.assertRaises(ImportErrorSafe):
                build(records)

    def test_local_switch_separate_identity_and_dns_not_guessed_as_ip(self):
        records = cache()
        records['Switch A'].update(local_only=True, hostid=None, ip='switch-a.example.test')
        catalog = build(records)
        self.assertEqual(catalog.rows[0][:2], ('local', 'switch a'))
        self.assertIsNone(catalog.rows[0][9])
        self.assertEqual(catalog.summary()['enderecos_dns'], 1)

    def test_invalid_types_addresses_and_duplicate_json_fail_closed(self):
        for field, value in (('is_core', 'false'), ('local_only', 1),
                             ('em_manutencao', 'yes'), ('warning_problemas', {}),
                             ('ip', 'https://PRIVATE_PASSWORD@example.test'),
                             ('ip', '999.999.999.999'), ('ultima_verificacao', 'bad')):
            records = cache()
            records['Switch A'][field] = value
            with self.subTest(field=field), self.assertRaises(ImportErrorSafe) as error:
                build(records)
            self.assertNotIn('PRIVATE', str(error.exception))
        with self.assertRaises(ImportErrorSafe):
            build_switch_catalog(b'{"Switch A":{},"Switch A":{}}', raw(regionals()), 'UTC')
        with self.assertRaises(ImportErrorSafe):
            build({})

    def test_missing_observation_is_not_current_time(self):
        records = cache()
        records['Switch A'].pop('ultima_verificacao')
        catalog = build(records)
        self.assertIsNone(catalog.rows[0][16])
        self.assertEqual(catalog.summary()['sem_data_de_observacao'], 1)

    def test_guard_digest_covers_both_files_and_source_timezone(self):
        first = build()
        regions = regionals()
        regions['regionais']['REG_TLSV_POA']['descricao'] = 'Changed'
        self.assertNotEqual(first.digest, build(regions=regions).digest)
        records = cache()
        records['Switch A']['status'] = 'offline'
        self.assertNotEqual(first.digest, build(records).digest)

    def test_write_lock_compatible_and_bound_values_match_columns(self):
        catalog = build()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,), (1,)],
                                   [[('REG_TLSV_POA',)], [('vinculado', 1)]])
        write_switch_catalog(conn, catalog)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE', statements)
        self.assertIn('LOCK TABLE operacional.switches IN ROW EXCLUSIVE MODE', statements)
        insertion = next(call for call in cursor.execute.call_args_list
                         if call.args[0].startswith('INSERT INTO operacional.switches'))
        self.assertEqual(insertion.args[0].count('%s'), len(insertion.args[1]))
        self.assertEqual(insertion.args[1][0], SOURCE)
        self.assertNotIn('PRIVATE', repr(cursor.execute.call_args_list))
        self.assertFalse(any('UPDATE' in sql or 'DELETE' in sql or 'TRUNCATE' in sql for sql in statements))
        conn.commit.assert_not_called()

    def test_nonempty_wrong_instance_or_unknown_regionals_fail_before_insert(self):
        cases = [([('sentinel', 'sentinel_collector', 5433), (1,)], []),
                 ([('aegis', 'sentinel_collector', 5432)], []),
                 ([('sentinel', 'sentinel_collector', 5433), (0,)], [[]])]
        for counts, lists in cases:
            conn, cursor = connection(counts, lists)
            with self.assertRaises(ImportErrorSafe):
                write_switch_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cursor.execute.call_args_list))

    def test_bad_final_binding_counts_abort(self):
        conn, _ = connection([('sentinel', 'sentinel_collector', 5433), (0,), (1,)],
                             [[('REG_TLSV_POA',)], [('nao_encontrado', 1)]])
        with self.assertRaises(ImportErrorSafe):
            write_switch_catalog(conn, build())

    def test_check_database_read_only_and_no_codes_in_report(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,)], [[]])
        result = inspect_switch_catalog(conn, build())
        self.assertEqual(result['regionais_do_catalogo_ausentes_no_banco'], 1)
        self.assertNotIn('REG_TLSV_POA', repr(result))
        self.assertEqual(cursor.execute.call_args_list[0].args[0], 'SET TRANSACTION READ ONLY')

    def test_default_simulation_no_db_and_hash_guard_before_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            source, regions = Path(folder) / 'cache.json', Path(folder) / 'regions.json'
            source.write_bytes(raw(cache()))
            regions.write_bytes(raw(regionals()))
            args = ['--cache', str(source), '--regionals', str(regions),
                    '--source-timezone', 'America/Sao_Paulo']
            with patch('services.operational_postgres.connect_collector') as connect:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(args), 0)
                self.assertNotIn('PRIVATE', output.getvalue())
                connect.assert_not_called()
                with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, '--apply', '--expected-digest', 'wrong']), 1)
                connect.assert_not_called()

    def test_schema_quarantine_and_no_broad_grants(self):
        root = Path(__file__).resolve().parents[2]
        sql = (root / 'scripts/database/sql/004_switch_catalog.sql').read_text()
        self.assertIn('CONSTRAINT switch_vinculo_coerente', sql)
        self.assertIn('PRIMARY KEY (fonte, tipo_origem, id_origem)', sql)
        self.assertIn('GRANT SELECT, INSERT ON operacional.switches TO sentinel_collector', sql)
        self.assertNotIn('GRANT ALL', sql)


if __name__ == '__main__':
    unittest.main()
