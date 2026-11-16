from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database.import_vpn_catalog import (
    ImportErrorSafe, build_vpn_catalog, inspect_vpn_catalog, write_vpn_catalog, main,
)


def record(**changes):
    return {'tunel': 'T_PRIVATE', 'firewall_serial': 'SERIAL_PRIVATE', 'device': 'HUB_PRIVATE',
            'device_namespace': 'fortigate_ssh:192.0.2.1', 'vdom': 'root',
            'vdom_origem': 'vdom_desabilitado', 'vpn_source': 'fortigate_ssh',
            'coletado_em': '2026-11-16T15:00:00-03:00', 'ultima_verificacao': '15:00:00',
            'regional': 'REG_A', 'status': 'online', 'interface': 'N/A',
            'password': 'SECRET_PRIVATE', 'comentario': 'COMMENT_PRIVATE', **changes}


def raw(value):
    return json.dumps(value).encode()


def source(records=None):
    return {'groups': {'vpns': {'source': 'vpn_manual',
                              'records': [record()] if records is None else records}}}


REGIONS = {'regionais': {'REG_A': {'nome': 'A'}}}


def build(records=None):
    return build_vpn_catalog(raw(source(records)), raw(REGIONS))


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class VPNCatalogTest(unittest.TestCase):
    def test_complete_record_uses_aware_collection_not_legacy_clock(self):
        catalog = build()
        self.assertEqual(catalog.rows[0][9].isoformat(), '2026-11-16T18:00:00+00:00')
        self.assertEqual(catalog.rows[0][13], '15:00:00')
        self.assertIsNone(catalog.rows[0][12])
        self.assertEqual(catalog.summary()['vpns'], 1)
        self.assertEqual(catalog.summary()['por_status'], {'online': 1})
        self.assertNotIn('PRIVATE', repr(catalog))
        self.assertNotIn('PRIVATE', json.dumps(catalog.summary()))
        self.assertNotIn('SECRET', str(catalog.rows))
        self.assertNotIn('COMMENT', str(catalog.rows))

    def test_identity_does_not_use_regional_or_endpoint(self):
        with self.assertRaises(ImportErrorSafe):
            build([record(), record(regional='REG_B', device_namespace='fortigate_ssh:192.0.2.2')])
        self.assertEqual(len(build([record(), record(firewall_serial='OTHER')]).rows), 2)
        self.assertEqual(len(build([record(), record(vdom='other', vdom_origem='resposta_equipamento')]).rows), 2)

    def test_unknown_or_missing_regional_is_null_not_global_or_guessed(self):
        for regional, binding in (('REG_A_extra', 'nao_encontrado'),
                                  ('SEM_REGIONAL', 'ausente'), (None, 'ausente')):
            row = build([record(regional=regional)]).rows[0]
            self.assertIsNone(row[5])
            self.assertEqual(row[7], binding)

    def test_incomplete_invalid_fallback_and_naive_timestamps_are_rejected(self):
        for field, value in (('firewall_serial', None), ('vdom', None), ('vdom', 'global'),
                             ('tunel', ''), ('vpn_source', 'fortimanager_proxy'),
                             ('device_namespace', 'other'), ('vdom_origem', 'guess'),
                             ('status', 'unknown'), ('status', True),
                             ('coletado_em', '2026-11-16T15:00:00'),
                             ('coletado_em', '15:00:00'), ('coletado_em', None),
                             ('ultima_verificacao', '25:00:00')):
            with self.subTest(field=field, value=value), self.assertRaises(ImportErrorSafe):
                build([record(**{field: value})])
        with self.assertRaises(ImportErrorSafe):
            build([record(vdom='other')])

    def test_malformed_or_empty_sources_do_not_become_empty_inventory(self):
        for payload in ({}, [], {'groups': {'vpns': {'records': []}}},
                        source([]), source([None])):
            with self.subTest(payload=payload), self.assertRaises(ImportErrorSafe):
                build_vpn_catalog(raw(payload), raw(REGIONS))
        with self.assertRaises(ImportErrorSafe):
            build_vpn_catalog(b'{"groups":{},"groups":{}}', raw(REGIONS))

    def test_both_raw_files_are_guarded_and_map_group_with_complete_metadata_is_accepted(self):
        payload = source()
        first = build_vpn_catalog(raw(payload), raw(REGIONS))
        payload['groups']['vpns']['source'] = 'mapa'
        second = build_vpn_catalog(raw(payload), raw(REGIONS))
        self.assertNotEqual(first.digest, second.digest)
        catalog = deepcopy(REGIONS)
        catalog['regionais']['REG_A']['descricao'] = 'Changed'
        self.assertNotEqual(first.digest, build_vpn_catalog(raw(source()), raw(catalog)).digest)

    def test_writer_uses_bound_parameters_and_compatible_locks(self):
        catalog = build()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,), (1,)],
                                  [[('REG_A',)], [('vinculado', 1)]])
        write_vpn_catalog(conn, catalog)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE', statements)
        self.assertIn('LOCK TABLE operacional.vpns IN ROW EXCLUSIVE MODE', statements)
        insertion = next(call for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT'))
        self.assertEqual(insertion.args[0].count('%s'), len(insertion.args[1]))
        self.assertNotIn('PRIVATE', insertion.args[0])
        self.assertFalse(any(word in sql for sql in statements for word in ('UPDATE ', 'DELETE ', 'TRUNCATE ')))
        conn.commit.assert_not_called()

    def test_nonempty_wrong_instance_and_missing_regionals_fail_before_insert(self):
        cases = [([('sentinel', 'sentinel_collector', 5433), (1,)], []),
                 ([('aegis', 'sentinel_collector', 5432)], []),
                 ([('sentinel', 'sentinel_collector', 5433), (0,)], [[]])]
        for ones, lists in cases:
            conn, cursor = connection(ones, lists)
            with self.assertRaises(ImportErrorSafe):
                write_vpn_catalog(conn, build())
            self.assertFalse(any(c.args[0].startswith('INSERT') for c in cursor.execute.call_args_list))

    def test_final_counts_or_bindings_fail_closed(self):
        for count, bindings in ((0, []), (1, [('nao_encontrado', 1)])):
            conn, _ = connection([('sentinel', 'sentinel_collector', 5433), (0,), (count,)],
                                 [[('REG_A',)], bindings])
            with self.assertRaises(ImportErrorSafe):
                write_vpn_catalog(conn, build())

    def test_inspection_is_read_only(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,)], [[]])
        result = inspect_vpn_catalog(conn, build())
        self.assertEqual(result['regionais_do_catalogo_ausentes_no_banco'], 1)
        self.assertTrue(result['tabela_vpns_vazia'])
        self.assertIn('READ ONLY', cursor.execute.call_args_list[0].args[0])
        self.assertNotIn('PRIVATE', str(result))

    def test_simulation_and_hash_guards_never_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            path, regions = Path(folder) / 'state.json', Path(folder) / 'regions.json'
            path.write_bytes(raw(source()))
            regions.write_bytes(raw(REGIONS))
            args = ['--source', str(path), '--regionals', str(regions)]
            with patch('services.operational_postgres.connect_collector') as connect:
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(args), 0)
                self.assertNotIn('PRIVATE', output.getvalue())
                with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, '--apply', '--expected-digest', 'wrong']), 1)
                with patch.dict('os.environ', {'COMPUTERNAME': 'OTHER'}), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, '--check-database']), 1)
                connect.assert_not_called()

    def test_schema_is_least_privilege_and_does_not_link_remote_regional_firewall(self):
        sql = (Path(__file__).resolve().parents[2] / 'scripts/database/sql/006_vpn_catalog.sql').read_text()
        self.assertIn('PRIMARY KEY (firewall_serial, vdom, tunel)', sql)
        self.assertIn('GRANT SELECT, INSERT ON operacional.vpns TO sentinel_collector', sql)
        self.assertNotIn('REFERENCES operacional.firewalls', sql)
        self.assertNotIn('GRANT ALL', sql)
        self.assertNotIn('GRANT UPDATE', sql)


if __name__ == '__main__':
    unittest.main()
