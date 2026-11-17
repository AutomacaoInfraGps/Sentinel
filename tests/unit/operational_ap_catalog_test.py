from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database.import_ap_catalog import (
    AP_COLUMNS, SITE_COLUMNS, CONTROLLER_ID, ImportErrorSafe,
    build_ap_catalog, inspect_ap_catalog, main, write_ap_catalog,
)


def raw(value):
    return json.dumps(value).encode()


def source():
    return {
        'timestamp': '2026-11-17T08:00:00',
        'controller': {'ip': '192.0.2.1', 'porta': 8443, 'password': 'SECRET_PRIVATE'},
        'sites': [{'id': 'SITE_PRIVATE', 'nome': 'V021_BAHIA', 'wlan_password': 'SECRET_PRIVATE'}],
        'aps': [{'nome': 'AP_PRIVATE', 'mac': '00:11:22:AA:BB:CC', 'ip': '198.51.100.1',
                 'site': 'V021_BAHIA', 'modelo_codigo': 'uap', 'modelo': 'AP Model',
                 'firmware': '1.2.3', 'status': 'online', 'clientes': 0, 'uptime': 0,
                 'vap_table': [{'passphrase': 'SECRET_PRIVATE'}], 'password': 'SECRET_PRIVATE'}],
        'interferencia_5ghz_por_site': {'secret': 'SECRET_PRIVATE'},
    }


def regions():
    return {'regionais': {'REG_BAHIA': {'nome': 'Bahia', 'password': 'SECRET_PRIVATE'}}}


def build(payload=None, catalog=None, zone='America/Sao_Paulo'):
    return build_ap_catalog(raw(source() if payload is None else payload),
                            raw(regions() if catalog is None else catalog), zone)


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class ApCatalogTests(unittest.TestCase):
    def test_typed_projection_and_summary_exclude_secrets_and_record_values(self):
        payload = source()
        before = deepcopy(payload)
        catalog = build(payload)
        self.assertEqual(before, payload)
        self.assertEqual(len(catalog.aps[0]), len(AP_COLUMNS))
        self.assertEqual(len(catalog.sites[0]), len(SITE_COLUMNS))
        self.assertEqual(catalog.aps[0][0], CONTROLLER_ID)
        self.assertEqual(catalog.aps[0][1], '00:11:22:aa:bb:cc')
        self.assertEqual(catalog.aps[0][9:11], (0, 0))
        self.assertEqual(catalog.sites[0][3], 'REG_BAHIA')
        self.assertNotIn('PRIVATE', repr(catalog))
        self.assertNotIn('SECRET_PRIVATE', repr((catalog.controller, catalog.sites, catalog.aps)))
        self.assertNotIn('PRIVATE', json.dumps(catalog.summary()))
        self.assertEqual(catalog.summary()['aps_com_regional'], 1)
        self.assertFalse(catalog.summary()['sincronizacao_automatica_aps'])

    def test_publication_clock_never_becomes_ap_collection(self):
        catalog = build()
        self.assertEqual(catalog.controller[3].isoformat(), '2026-11-17T11:00:00+00:00')
        self.assertTrue(catalog.controller[4])
        self.assertIsNone(catalog.aps[0][11])
        self.assertEqual(catalog.summary()['sem_coleta_explicita_por_ap'], 1)
        payload = source()
        payload['aps'][0]['coletado_em'] = '2026-11-17T08:00:00-03:00'
        self.assertEqual(build(payload).aps[0][11].isoformat(), '2026-11-17T11:00:00+00:00')
        payload['aps'][0]['coletado_em'] = '2026-11-17T08:00:00'
        with self.assertRaises(ImportErrorSafe):
            build(payload)

    def test_missing_publication_is_not_now(self):
        payload = source()
        payload.pop('timestamp')
        catalog = build(payload)
        self.assertIsNone(catalog.controller[3])
        self.assertEqual(catalog.summary()['publicacao_da_fonte'], 'ausente')

    def test_ap_identity_is_controller_mac_not_name_ip_or_site(self):
        payload = source()
        payload['sites'].append({'id': 'second', 'nome': 'Second'})
        payload['aps'].append(dict(payload['aps'][0], site='Second', mac='00-11-22-AA-BB-CD'))
        catalog = build(payload)
        self.assertEqual(len(catalog.aps), 2)
        payload['aps'][1]['mac'] = '001122aabbcc'
        with self.assertRaises(ImportErrorSafe):
            build(payload)

    def test_unknown_site_rejected_but_unknown_regional_quarantined(self):
        payload = source()
        payload['sites'].append({'id': 'other', 'nome': 'Unassigned'})
        payload['aps'][0]['site'] = 'Unassigned'
        catalog = build(payload)
        self.assertEqual(catalog.summary()['aps_sem_regional'], 1)
        self.assertIsNone(next(row for row in catalog.sites if row[1] == 'other')[3])
        self.assertEqual(len(catalog.sites), 2)
        payload['aps'][0]['site'] = 'Unknown'
        with self.assertRaises(ImportErrorSafe):
            build(payload)

    def test_explicit_site_id_can_disambiguate_but_not_conflict(self):
        payload = source()
        payload['sites'].append({'id': 'second', 'nome': 'V021_BAHIA'})
        with self.assertRaises(ImportErrorSafe):
            build(payload)
        payload['aps'][0]['site_id'] = 'second'
        self.assertEqual(build(payload).aps[0][2], 'second')
        payload['aps'][0]['site_id'] = 'missing'
        with self.assertRaises(ImportErrorSafe):
            build(payload)

    def test_ambiguous_regional_does_not_pick_first(self):
        catalog = build(catalog={'regionais': {'A': {'nome': 'Bahia'}, 'B': {'nome': 'Bahia'}}})
        self.assertIsNone(catalog.sites[0][3])
        self.assertEqual(catalog.sites[0][4], 'ambiguo')

    def test_invalid_fields_fail_without_echoing_source_values(self):
        for field, value in (('mac', None), ('mac', 'SECRET_PRIVATE'), ('mac', '01:11:22:33:44:55'),
                              ('ip', 'SECRET_PRIVATE'), ('status', 'SECRET_PRIVATE'), ('clientes', True),
                              ('clientes', -1), ('uptime', 1.5), ('uptime', 9223372036854775808),
                              ('em_manutencao', 'false'), ('nome', None), ('coletado_em', '08:00:00')):
            payload = source()
            payload['aps'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ImportErrorSafe) as caught:
                build(payload)
            self.assertNotIn('SECRET_PRIVATE', str(caught.exception))

    def test_invalid_controller_inventory_and_duplicate_json_fail(self):
        for field, value in (('ip', 'https://SECRET_PRIVATE'), ('porta', True), ('porta', None), ('porta', 65536)):
            payload = source()
            payload['controller'][field] = value
            with self.assertRaises(ImportErrorSafe):
                build(payload)
        for field, value in (('sites', []), ('aps', []), ('aps', [None]), ('sites', [None])):
            payload = source()
            payload[field] = value
            with self.assertRaises(ImportErrorSafe):
                build(payload)
        payload = source()
        payload['sites'].append(deepcopy(payload['sites'][0]))
        with self.assertRaises(ImportErrorSafe):
            build(payload)
        with self.assertRaises(ImportErrorSafe):
            build_ap_catalog(b'{"aps":[],"aps":[]}', raw(regions()), 'UTC')

    def test_digest_covers_both_files_timezone_and_projected_mapping(self):
        first = build()
        payload = source()
        payload['unused'] = True
        self.assertNotEqual(first.digest, build(payload).digest)
        regional = regions()
        regional['unused'] = True
        self.assertNotEqual(first.digest, build(catalog=regional).digest)
        self.assertNotEqual(first.digest, build(zone='UTC').digest)
        with patch('scripts.database.import_ap_catalog.resolve_unifi_site_for_catalog',
                   return_value=(None, 'nao_encontrado')):
            self.assertNotEqual(first.digest, build().digest)

    def test_writer_bound_values_order_counts_and_no_commit(self):
        catalog = build()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0, 0, 0), (1, 1, 1), (1,)],
                                  [[('REG_BAHIA',)], [('online', 1)]])
        write_ap_catalog(conn, catalog)
        calls = cursor.execute.call_args_list
        locks = [call.args[0] for call in calls if call.args[0].startswith('LOCK')]
        self.assertEqual(locks, [
            'LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE',
            'LOCK TABLE operacional.controladoras_unifi IN ROW EXCLUSIVE MODE',
            'LOCK TABLE operacional.sites_unifi IN ROW EXCLUSIVE MODE',
            'LOCK TABLE operacional.aps_unifi IN ROW EXCLUSIVE MODE',
        ])
        inserts = [call for call in calls if call.args[0].startswith('INSERT')]
        self.assertEqual(len(inserts), 3)
        for call in inserts:
            self.assertEqual(call.args[0].count('%s'), len(call.args[1]))
            self.assertNotIn('PRIVATE', call.args[0])
        self.assertNotIn('SECRET_PRIVATE', repr(calls))
        self.assertFalse(any(word in call.args[0] for call in calls for word in ('DELETE ', 'TRUNCATE ', 'UPDATE ')))
        conn.commit.assert_not_called()

    def test_existing_table_wrong_destination_or_missing_regional_blocks_all_inserts(self):
        for ones, lists in (([('aegis', 'sentinel_collector', 5432)], []),
                            ([('sentinel', 'sentinel_collector', 5433), (0, 1, 0)], []),
                            ([('sentinel', 'sentinel_collector', 5433), (0, 0, 0)], [[]])):
            conn, cursor = connection(ones, lists)
            with self.assertRaises(ImportErrorSafe):
                write_ap_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cursor.execute.call_args_list))

    def test_final_counts_status_and_regional_count_must_match(self):
        for final, statuses, regional_count in (((1, 1, 0), [('online', 1)], (1,)),
                                               ((1, 1, 1), [('offline', 1)], (1,)),
                                               ((1, 1, 1), [('online', 1)], (0,))):
            conn, _ = connection([('sentinel', 'sentinel_collector', 5433), (0, 0, 0), final, regional_count],
                                 [[('REG_BAHIA',)], statuses])
            with self.assertRaises(ImportErrorSafe):
                write_ap_catalog(conn, build())

    def test_inspection_is_read_only_and_counts_missing_regionals(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0, 0, 0)], [[]])
        result = inspect_ap_catalog(conn, build())
        self.assertTrue(result['tabelas_unifi_vazias'])
        self.assertEqual(result['regionais_do_catalogo_ausentes_no_banco'], 1)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY', sql)
        self.assertFalse(any(word in statement for statement in sql for word in ('INSERT', 'LOCK TABLE', 'UPDATE ', 'DELETE ')))

    def test_cli_default_no_connection_and_apply_requires_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, regional = root / 'unifi.json', root / 'regionals.json'
            cache.write_bytes(raw(source()))
            regional.write_bytes(raw(regions()))
            args = ['--source', str(cache), '--regionals', str(regional), '--source-timezone', 'UTC']
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

    def test_migration_owner_identity_scope_and_minimal_grants(self):
        path = Path(__file__).resolve().parents[2] / 'scripts/database/sql/010_ap_catalog.sql'
        sql = path.read_text(encoding='utf-8')
        self.assertIn('SET LOCAL ROLE sentinel_owner', sql)
        self.assertIn("'E:/Sentinel/PostgreSQL/data'", sql)
        self.assertIn('PRIMARY KEY (controladora_id, mac)', sql)
        self.assertIn('FOREIGN KEY (controladora_id, site_id)', sql)
        self.assertIn('GRANT SELECT, INSERT ON', sql)
        self.assertNotIn('TO PUBLIC', sql)
        self.assertNotIn('GRANT UPDATE', sql)
        self.assertNotIn('GRANT ALL', sql)


if __name__ == '__main__':
    unittest.main()
