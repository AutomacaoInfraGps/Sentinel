from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database.import_link_catalog import (
    COLUMNS, ImportErrorSafe, build_link_catalog, inspect_link_catalog, write_link_catalog, main,
)


def record(**changes):
    return {'id': 'ID_PRIVATE', 'nome': 'NAME_PRIVATE', 'interface_monitorada': 'wan1',
            'fortigate_host': '192.0.2.1', 'fortigate_porta': 443,
            'provedor': 'PROVIDER_PRIVATE', 'ip': '198.51.100.1', 'mascara': '255.255.255.0',
            'velocidade': '100 Mbps', 'status': 'online', 'ativo': True,
            'origem_sync': 'fortimanager_config+proxy_monitor',
            'modo_verificacao': 'monitor_zabbix_packet_loss', 'packet_loss_percent': 0,
            'sdwan_member_id': 1, 'priority': 1,
            'ultima_verificacao': '2026-11-16T16:00:00',
            'password': 'SECRET_PRIVATE', 'sla_data': {'token': 'SECRET_PRIVATE'}, **changes}


def payload(records=None):
    return {'regionais': {'REG_A': {'links_internet_auto': [record()] if records is None else records,
                                   'links': [{'id': 'OLD_PRIVATE'}, None]}},
            'configuracao': {'ultima_atualizacao': '2026-11-17T12:00:00'}}


def raw(value):
    return json.dumps(value).encode()


def build(records=None):
    return build_link_catalog(raw(payload(records)), 'America/Sao_Paulo')


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class LinkCatalogTest(unittest.TestCase):
    def test_auto_only_keeps_legacy_untouched_and_does_not_export_values(self):
        source = payload()
        before = deepcopy(source)
        catalog = build_link_catalog(raw(source), 'America/Sao_Paulo')
        self.assertEqual(source, before)
        self.assertEqual(len(catalog.rows), 1)
        self.assertEqual(len(catalog.rows[0]), len(COLUMNS))
        self.assertNotIn('PRIVATE', json.dumps(catalog.summary()))
        self.assertNotIn('PRIVATE', repr(catalog))
        self.assertNotIn('SECRET', repr(catalog.rows))
        self.assertNotIn('OLD_PRIVATE', repr(catalog.rows))
        self.assertEqual(catalog.summary()['por_modo_verificacao'], {'monitor_zabbix_packet_loss': 1})

    def test_verification_time_does_not_become_collection_or_publication_time(self):
        row = build().rows[0]
        self.assertEqual(row[21].isoformat(), '2026-11-16T19:00:00+00:00')
        self.assertIsNone(row[22])
        self.assertTrue(row[23])
        self.assertIsNone(row[6])
        self.assertIsNone(row[7])
        self.assertEqual(build().summary()['sem_coleta_explicita'], 1)
        explicit = build([record(ultima_verificacao='2026-11-16T16:00:00-03:00',
                                 coletado_em='2026-11-16T19:00:00Z')]).rows[0]
        self.assertFalse(explicit[23])
        self.assertEqual(explicit[22].isoformat(), '2026-11-16T19:00:00+00:00')

    def test_unknown_and_missing_verification_are_not_current_time(self):
        catalog = build([record(ultima_verificacao=None)])
        self.assertIsNone(catalog.rows[0][21])
        self.assertEqual(catalog.summary()['verificacoes_ausentes'], 1)
        with self.assertRaises(ImportErrorSafe):
            build([record(coletado_em='2026-11-16T16:00:00')])

    def test_auto_missing_or_empty_does_not_fall_back_to_legacy(self):
        source = payload()
        source['regionais']['REG_B'] = {'links': [record()]}
        source['regionais']['REG_C'] = {'links_internet_auto': [], 'links': [record()]}
        result = build_link_catalog(raw(source), 'UTC')
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.missing_lists, 1)
        self.assertEqual(result.empty_lists, 1)
        with self.assertRaises(ImportErrorSafe):
            build([])

    def test_key_is_regional_id_and_never_provider_or_public_ip(self):
        source = payload()
        source['regionais']['REG_B'] = deepcopy(source['regionais']['REG_A'])
        self.assertEqual(len(build_link_catalog(raw(source), 'UTC').rows), 2)
        self.assertEqual(len(build([record(), record(id='other', interface_monitorada='wan2')]).rows), 2)
        for second in (record(interface_monitorada='wan2'), record(id='other')):
            with self.assertRaises(ImportErrorSafe):
                build([record(), second])

    def test_invalid_fields_do_not_silently_discard_records_or_print_source_values(self):
        for key, value in (('id', None), ('id', True), ('id', 1.5),
                           ('interface_monitorada', None), ('fortigate_host', 'https://PRIVATE@example.test'),
                           ('fortigate_porta', 65536), ('ativo', 'false'), ('ip', 'PRIVATE_INVALID'),
                           ('packet_loss_percent', True), ('packet_loss_percent', float('nan')),
                           ('packet_loss_percent', 101), ('priority', -1), ('sdwan_member_id', False),
                           ('status', 'PRIVATE_UNKNOWN'), ('ultima_verificacao', '16:00:00'),
                           ('vdom', 'global')):
            with self.subTest(key=key, value=value), self.assertRaises(ImportErrorSafe) as error:
                build([record(**{key: value})])
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_ip_cidr_dns_endpoint_zero_metrics_and_numeric_ids_are_preserved(self):
        row = build([record(id=0, fortigate_host='firewall.example.test', ip='198.51.100.1/24',
                            priority=0, sdwan_member_id='0', packet_loss_percent='0')]).rows[0]
        self.assertEqual(row[1], '0')
        self.assertEqual(row[4], 'firewall.example.test')
        self.assertEqual(row[9], '198.51.100.1/24')
        self.assertEqual(row[18:21], ('0', 0, 0.0))

    def test_digest_guards_entire_file_and_explicit_timezone(self):
        first = build()
        changed = payload()
        changed['configuracao']['other'] = 'changed'
        self.assertNotEqual(first.digest, build_link_catalog(raw(changed), 'America/Sao_Paulo').digest)
        self.assertNotEqual(first.digest, build_link_catalog(raw(payload()), 'UTC').digest)

    def test_malformed_regional_or_auto_lists_and_duplicate_json_are_blocked(self):
        for source in ({}, {'regionais': []}, {'regionais': {'REG_A': None}},
                       {'regionais': {'REG_A': {'links_internet_auto': {}}}}):
            with self.assertRaises(ImportErrorSafe):
                build_link_catalog(raw(source), 'UTC')
        with self.assertRaises(ImportErrorSafe):
            build_link_catalog(b'{"regionais":{},"regionais":{}}', 'UTC')

    def test_sql_writer_uses_fixed_columns_bound_values_and_safe_lock_order(self):
        catalog = build()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,), (1,)],
                                  [[('REG_A',)], [('online', 1)]])
        write_link_catalog(conn, catalog)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE', sql)
        self.assertIn('LOCK TABLE operacional.links_internet IN ROW EXCLUSIVE MODE', sql)
        insertion = next(call for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT'))
        self.assertEqual(insertion.args[0].count('%s'), len(insertion.args[1]))
        self.assertEqual(len(insertion.args[1]), len(COLUMNS) + 2)
        self.assertNotIn('PRIVATE', insertion.args[0])
        self.assertNotIn('SECRET', repr(cursor.execute.call_args_list))
        self.assertFalse(any(word in statement for statement in sql for word in ('UPDATE ', 'DELETE ', 'TRUNCATE ')))
        conn.commit.assert_not_called()

    def test_existing_table_wrong_database_or_missing_regionals_fail_before_insert(self):
        for ones, lists in (([('sentinel', 'sentinel_collector', 5433), (1,)], []),
                            ([('aegis', 'sentinel_collector', 5432)], []),
                            ([('sentinel', 'sentinel_collector', 5433), (0,)], [[]])):
            conn, cursor = connection(ones, lists)
            with self.assertRaises(ImportErrorSafe):
                write_link_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cursor.execute.call_args_list))

    def test_bad_final_total_or_status_counts_aborts(self):
        for total, statuses in ((0, []), (1, [('offline', 1)])):
            conn, _ = connection([('sentinel', 'sentinel_collector', 5433), (0,), (total,)],
                                 [[('REG_A',)], statuses])
            with self.assertRaises(ImportErrorSafe):
                write_link_catalog(conn, build())

    def test_inspection_is_read_only(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,)], [[]])
        report = inspect_link_catalog(conn, build())
        self.assertTrue(report['tabela_links_vazia'])
        self.assertEqual(report['regionais_do_catalogo_ausentes_no_banco'], 1)
        self.assertIn('READ ONLY', cursor.execute.call_args_list[0].args[0])

    def test_cli_simulation_hash_and_machine_guards_never_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'catalog.json'
            source.write_bytes(raw(payload()))
            args = ['--source', str(source), '--source-timezone', 'UTC']
            with patch('services.operational_postgres.connect_collector') as connect:
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(args), 0)
                self.assertNotIn('PRIVATE', output.getvalue())
                with patch.dict('os.environ', {'COMPUTERNAME': 'RIGEL'}), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, '--apply', '--expected-digest', 'wrong']), 1)
                with patch.dict('os.environ', {'COMPUTERNAME': 'OTHER'}), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, '--check-database']), 1)
                connect.assert_not_called()

    def test_schema_keeps_nullable_context_and_reader_readonly(self):
        sql = (Path(__file__).resolve().parents[2] / 'scripts/database/sql/008_link_catalog.sql').read_text()
        self.assertIn('PRIMARY KEY (codigo_regional, id_origem)', sql)
        self.assertIn('coletado_em timestamptz,', sql)
        self.assertIn('firewall_serial varchar(120),', sql)
        self.assertNotIn('REFERENCES operacional.firewalls', sql)
        self.assertIn('GRANT SELECT, INSERT ON operacional.links_internet TO sentinel_collector', sql)
        self.assertNotIn('GRANT ALL', sql)


if __name__ == '__main__':
    unittest.main()
