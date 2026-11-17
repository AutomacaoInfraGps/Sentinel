from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database.import_wlan_catalog import (
    COLUMNS, ImportErrorSafe, build_wlan_catalog, inspect_wlan_catalog, write_wlan_catalog, main,
)

AT = '2026-11-17T13:00:00Z'


def raw(value):
    return json.dumps(value).encode()


def source():
    return {'controller': {'ip': '192.0.2.1', 'porta': 8443, 'password': 'SECRET_PRIVATE'},
            'timestamp': '2020-01-01T00:00:00', 'aps': [{'password': 'SECRET_PRIVATE'}],
            'sites': [{'id': 'SITE_PRIVATE', 'nome': 'V021_BAHIA',
                       'coleta_wlans_confirmada': True, 'wlans_situacao': 'confirmada', 'wlans_coletadas_em': AT,
                       'redes_wifi': [{'nome': 'DISPLAY_PRIVATE', 'password': 'SECRET_PRIVATE'}],
                       'wlans_configuradas': [{'wlan_id': 'WLAN_PRIVATE', 'nome': 'SSID_PRIVATE',
                                               'networkconf_id': 'NETWORK_PRIVATE', 'ativo': True,
                                               'bandas': ['2g', '5g'], 'coletado_em': AT,
                                               'origem': 'configuracao_unifi', 'password': 'SECRET_PRIVATE'}]}]}


def regions():
    return {'regionais': {'REG_BAHIA': {'nome': 'Bahia'}}}


def build(payload=None, regional=None):
    return build_wlan_catalog(raw(source() if payload is None else payload),
                              raw(regions() if regional is None else regional))


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


def parent_rows():
    return [[('REG_BAHIA',)], [('SITE_PRIVATE', 'V021_BAHIA', 'REG_BAHIA')]]


class WlanCatalogTests(unittest.TestCase):
    def test_safe_projection_is_immutable_and_only_configuration_is_imported(self):
        payload = source()
        before = deepcopy(payload)
        catalog = build(payload)
        self.assertEqual(before, payload)
        self.assertEqual(len(catalog.rows[0]), len(COLUMNS))
        self.assertEqual(catalog.rows[0][6], ('2g', '5g'))
        self.assertNotIn('SECRET_PRIVATE', repr(catalog.rows))
        self.assertNotIn('DISPLAY_PRIVATE', repr(catalog.rows))
        self.assertNotIn('PRIVATE', repr(catalog))
        self.assertNotIn('PRIVATE', json.dumps(catalog.summary()))
        self.assertFalse(catalog.summary()['lista_de_exibicao_importada'])
        self.assertFalse(catalog.summary()['sincronizacao_automatica_wlans'])

    def test_wlan_identity_not_ssid_and_ids_are_scoped_to_site(self):
        payload = source()
        site = payload['sites'][0]
        site['wlans_configuradas'].append(dict(site['wlans_configuradas'][0], wlan_id='other'))
        self.assertEqual(len(build(payload).rows), 2)
        payload['sites'].append(dict(deepcopy(site), id='second'))
        self.assertEqual(len(build(payload).rows), 4)
        payload['sites'][0]['wlans_configuradas'][1]['wlan_id'] = 'WLAN_PRIVATE'
        with self.assertRaises(ImportErrorSafe):
            build(payload)

    def test_ssid_spaces_case_and_unknown_enabled_are_preserved(self):
        payload = source()
        wlan = payload['sites'][0]['wlans_configuradas'][0]
        wlan['nome'] = ' MARTE '
        wlan['ativo'] = None
        wlan['networkconf_id'] = None
        result = build(payload)
        self.assertEqual(result.rows[0][3], ' MARTE ')
        self.assertIsNone(result.rows[0][5])
        self.assertEqual(result.summary()['por_ativo'], {'desconhecido': 1})
        self.assertEqual(result.summary()['sem_id_rede'], 1)

    def test_explicit_collection_not_file_or_ap_clock_and_site_must_match(self):
        catalog = build()
        self.assertEqual(catalog.rows[0][7].isoformat(), '2026-11-17T13:00:00+00:00')
        for value in (None, '13:00:00', '2026-11-17T13:00:00', '2026-11-17T13:01:00Z'):
            payload = source()
            payload['sites'][0]['wlans_configuradas'][0]['coletado_em'] = value
            with self.assertRaises(ImportErrorSafe):
                build(payload)

    def test_missing_unconfirmed_or_runtime_only_configuration_blocks_load(self):
        for key, value in (('coleta_wlans_confirmada', False), ('coleta_wlans_confirmada', 1),
                           ('wlans_situacao', None), ('wlans_configuradas', None)):
            payload = source()
            payload['sites'][0][key] = value
            with self.assertRaises(ImportErrorSafe):
                build(payload)
        payload = source()
        payload['sites'][0]['wlans_configuradas'][0]['origem'] = 'runtime_ap'
        with self.assertRaises(ImportErrorSafe):
            build(payload)

    def test_empty_site_and_unknown_regional_are_preserved_without_creating_parent(self):
        payload = source()
        payload['sites'][0]['nome'] = 'Unknown'
        payload['sites'].append(dict(payload['sites'][0], id='empty', wlans_configuradas=[]))
        catalog = build(payload)
        self.assertEqual(catalog.summary()['wlans_sem_regional'], 1)
        self.assertEqual(catalog.summary()['sites_com_lista_vazia'], 1)
        self.assertEqual(catalog.summary()['sites_com_coleta_confirmada'], 2)
        payload['sites'][0]['wlans_configuradas'] = []
        with self.assertRaises(ImportErrorSafe):
            build(payload)

    def test_invalid_fields_are_blocked_without_value_echo(self):
        for key, value in (('wlan_id', None), ('wlan_id', True), ('wlan_id', 'PRIVATE INVALID'),
                           ('nome', None), ('ativo', 'false'), ('bandas', '5g'), ('bandas', [{}]),
                           ('networkconf_id', {'password': 'SECRET_PRIVATE'})):
            payload = source()
            payload['sites'][0]['wlans_configuradas'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ImportErrorSafe) as caught:
                build(payload)
            self.assertNotIn('PRIVATE', str(caught.exception))

    def test_invalid_controller_duplicate_site_and_json_fail(self):
        for key, value in (('ip', 'https://PRIVATE@controller'), ('porta', None), ('porta', True)):
            payload = source()
            payload['controller'][key] = value
            with self.assertRaises(ImportErrorSafe):
                build(payload)
        payload = source()
        payload['sites'].append(deepcopy(payload['sites'][0]))
        with self.assertRaises(ImportErrorSafe):
            build(payload)
        with self.assertRaises(ImportErrorSafe):
            build_wlan_catalog(b'{"sites":[],"sites":[]}', raw(regions()))

    def test_digest_covers_both_files_and_effective_bindings(self):
        first = build()
        payload = source()
        payload['unrelated'] = 1
        self.assertNotEqual(first.digest, build(payload).digest)
        regional = regions()
        regional['unrelated'] = 1
        self.assertNotEqual(first.digest, build(regional=regional).digest)
        with patch('scripts.database.import_wlan_catalog.resolve_unifi_site_for_catalog', return_value=(None, 'nao_encontrado')):
            self.assertNotEqual(first.digest, build().digest)

    def test_read_only_inspection_checks_existing_site_name_and_regional(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), ('192.0.2.1', 8443), (0,)], parent_rows())
        result = inspect_wlan_catalog(conn, build())
        self.assertTrue(result['controladora_compativel'])
        self.assertTrue(result['tabela_wlans_vazia'])
        self.assertEqual(result['sites_com_regional_divergente'], 0)
        self.assertFalse(any(call.args[0].startswith(('LOCK', 'INSERT', 'UPDATE', 'DELETE')) for call in cursor.execute.call_args_list))
        conn, _ = connection([('sentinel', 'sentinel_collector', 5433), ('wrong', 8443), (0,)],
                             [[('REG_BAHIA',)], [('SITE_PRIVATE', 'Wrong', None)]])
        result = inspect_wlan_catalog(conn, build())
        self.assertFalse(result['controladora_compativel'])
        self.assertEqual(result['sites_com_nome_divergente'], 1)
        self.assertEqual(result['sites_com_regional_divergente'], 1)

    def test_sql_writer_only_inserts_wlans_and_binds_native_arrays(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,), ('192.0.2.1', 8443), (1,), (1,)],
                                  [*parent_rows(), [(True, 1)]])
        write_wlan_catalog(conn, build())
        calls = cursor.execute.call_args_list
        inserts = [call for call in calls if call.args[0].startswith('INSERT')]
        self.assertEqual(len(inserts), 1)
        self.assertTrue(inserts[0].args[0].startswith('INSERT INTO operacional.wlans_unifi'))
        self.assertIsInstance(inserts[0].args[1][6], list)
        self.assertEqual(inserts[0].args[0].count('%s'), len(inserts[0].args[1]))
        self.assertNotIn('PRIVATE', inserts[0].args[0])
        self.assertNotIn('SECRET_PRIVATE', repr(calls))
        sql = [call.args[0] for call in calls]
        self.assertIn('LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE', sql)
        self.assertFalse(any(word in statement for statement in sql for word in ('UPDATE ', 'DELETE ', 'TRUNCATE ')))
        conn.commit.assert_not_called()

    def test_existing_rows_wrong_instance_missing_or_mismatched_parents_block_insert(self):
        for ones, lists in (([('aegis', 'sentinel_collector', 5432)], []),
                            ([('sentinel', 'sentinel_collector', 5433), (1,)], []),
                            ([('sentinel', 'sentinel_collector', 5433), (0,), ('wrong', 8443)], parent_rows()),
                            ([('sentinel', 'sentinel_collector', 5433), (0,), ('192.0.2.1', 8443)], [[], []]),
                            ([('sentinel', 'sentinel_collector', 5433), (0,), ('192.0.2.1', 8443)],
                             [[('REG_BAHIA',)], [('SITE_PRIVATE', 'V021_BAHIA', None)]])):
            conn, cursor = connection(ones, lists)
            with self.assertRaises(ImportErrorSafe):
                write_wlan_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cursor.execute.call_args_list))

    def test_final_counts_active_and_bindings_are_validated(self):
        for count, active, bound in ((0, [(True, 1)], 1), (1, [(False, 1)], 1), (1, [(True, 1)], 0)):
            conn, _ = connection([('sentinel', 'sentinel_collector', 5433), (0,), ('192.0.2.1', 8443), (count,), (bound,)],
                                 [*parent_rows(), active])
            with self.assertRaises(ImportErrorSafe):
                write_wlan_catalog(conn, build())

    def test_cli_simulation_no_connection_and_write_requires_exact_digest_and_rigel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, regional = root / 'unifi.json', root / 'regions.json'
            cache.write_bytes(raw(source()))
            regional.write_bytes(raw(regions()))
            args = ['--source', str(cache), '--regionals', str(regional)]
            with patch('services.operational_postgres.connect_collector') as connect, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
                connect.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['modo'], 'simulacao_sem_conexao_ao_banco')
            with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(io.StringIO()):
                self.assertEqual(main([*args, '--apply', '--expected-digest', 'bad']), 1)
                connect.assert_not_called()
            with patch.dict('os.environ', {'COMPUTERNAME': 'OTHER'}), patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(io.StringIO()):
                self.assertEqual(main([*args, '--check-database']), 1)
                connect.assert_not_called()

    def test_migration_uses_existing_sites_and_minimal_privileges(self):
        path = Path(__file__).resolve().parents[2] / 'scripts/database/sql/012_wlan_catalog.sql'
        sql = path.read_text(encoding='utf-8')
        self.assertIn("'E:/Sentinel/PostgreSQL/data'", sql)
        self.assertIn('SET LOCAL ROLE sentinel_owner', sql)
        self.assertIn('PRIMARY KEY (controladora_id,site_id,id_origem)', sql)
        self.assertIn('REFERENCES operacional.sites_unifi(controladora_id,id_origem)', sql)
        self.assertIn('bandas text[]', sql)
        for text in ('GRANT UPDATE', 'GRANT DELETE', 'GRANT ALL', 'TO PUBLIC', 'UNIQUE (nome)'):
            self.assertNotIn(text, sql)


if __name__ == '__main__':
    unittest.main()
