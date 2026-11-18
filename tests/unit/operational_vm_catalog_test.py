from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import import_vm_catalog as module

REGIONS = {'regionais': {'REG_RIO_DE_JANEIRO': {'nome': 'REG_RIO_DE_JANEIRO'},
                         'REG_OTHER': {'nome': 'Other'}}}


def vm(**changes):
    return {'id': 'VM_PRIVATE', 'name': 'NAME_PRIVATE', 'ip': '192.0.2.1',
            'regional': 'Rio de Janeiro', 'status': 'Unknown', 'last_check': None,
            'username': 'ACCOUNT_PRIVATE', 'password': 'SECRET_PRIVATE', **changes}


def build(records=None, regions=None, zone=None):
    return module.build_vm_catalog(json.dumps([vm()] if records is None else records).encode(),
                                   json.dumps(REGIONS if regions is None else regions).encode(), zone)


def connection(ones, lists):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class VMCatalogTests(unittest.TestCase):
    def test_reviewed_rj_mapping_keeps_unknown_and_absent_date(self):
        snap = build()
        self.assertEqual(snap.rows[0][3:6], ('REG_RIO_DE_JANEIRO', 'Rio de Janeiro', 'rotulo_rj_confirmado'))
        self.assertEqual(snap.rows[0][7:], ('Unknown', None))
        self.assertIsNone(snap.source_timezone)
        self.assertEqual(snap.summary()['sem_data_de_verificacao'], 1)

    def test_no_credential_or_telemetry_in_projection_summary_or_repr(self):
        snap = build([vm(processors=2, memory=4096, details={'value': 'DETAIL_PRIVATE'},
                         host_name='HOST_PRIVATE', operatingSystem='Windows Server')])
        self.assertNotIn('SECRET_PRIVATE', str(snap.rows))
        self.assertNotIn('ACCOUNT_PRIVATE', str(snap.rows))
        self.assertNotIn('DETAIL_PRIVATE', str(snap.rows))
        self.assertNotIn('HOST_PRIVATE', str(snap.rows))
        self.assertNotIn('PRIVATE', json.dumps(snap.summary()) + repr(snap))
        self.assertFalse(snap.summary()['credenciais_importadas'])
        self.assertFalse(snap.summary()['telemetria_importada'])
        self.assertEqual(snap.summary()['campos_tecnicos_nao_importados']['memory'], 1)

    def test_only_approved_rj_label_or_exact_rj_code_accepted(self):
        snap = build([vm(regional='REG_RIO_DE_JANEIRO')])
        self.assertEqual(snap.rows[0][5], 'codigo_exato_aprovado')
        for label in ('RG_RIO_DE_JANEIRO', 'REG_OTHER', 'Other', '', 'SECRET_PRIVATE'):
            with self.subTest(label=label), self.assertRaises(module.ImportErrorSafe) as error:
                build([vm(regional=label)])
            self.assertNotIn('SECRET_PRIVATE', str(error.exception))

    def test_missing_rj_or_empty_invalid_envelopes_are_blocked(self):
        for records, regions in (([], REGIONS), ({}, REGIONS), ([None], REGIONS),
                                  ([vm()], {}), ([vm()], {'regionais': {'REG_OTHER': {}}})):
            with self.assertRaises(module.ImportErrorSafe):
                build(records, regions)

    def test_duplicate_or_invalid_id_blocks_without_merging(self):
        for records in ([vm(), vm(ip='192.0.2.2')], [vm(id=None)], [vm(id=17)], [vm(id=' padded ')], [vm(id='')]):
            with self.assertRaises(module.ImportErrorSafe):
                build(records)

    def test_duplicate_ip_invalid_ip_and_scoped_ipv6_are_blocked(self):
        for records in ([vm(), vm(id='VM_OTHER')], [vm(ip='not-an-ip')], [vm(ip='fe80::1%6')]):
            with self.assertRaises(module.ImportErrorSafe):
                build(records)

    def test_main_ip_normalizes_and_extra_addresses_are_not_silently_dropped(self):
        snap = build([vm(ip='2001:0db8::1', ipAddresses=['2001:db8::1'])])
        self.assertEqual(snap.rows[0][2], '2001:db8::1')
        for listed in (['192.0.2.2'], ['192.0.2.1', '192.0.2.2'], {}, [None], ['invalid']):
            with self.assertRaises(module.ImportErrorSafe):
                build([vm(ipAddresses=listed)])

    def test_unknown_and_running_are_preserved_as_declarations_not_measurements(self):
        for status in ('Unknown', 'Running', 'Stopped', 'Unreachable'):
            snap = build([vm(status=status)])
            self.assertEqual(snap.rows[0][7], status)
            self.assertTrue(snap.summary()['status_eh_declaracao_do_cadastro'])
        with self.assertRaises(module.ImportErrorSafe):
            build([vm(status='SECRET_PRIVATE')])

    def test_aware_dates_preserved_and_naive_dates_require_explicit_zone(self):
        stamp = '2026-11-18T08:00:00'
        with self.assertRaises(module.ImportErrorSafe):
            build([vm(last_check=stamp)])
        snap = build([vm(last_check=stamp)], zone='America/Sao_Paulo')
        self.assertEqual(snap.rows[0][-1].isoformat(), '2026-11-18T11:00:00+00:00')
        aware = build([vm(last_check=stamp + '-03:00')])
        self.assertEqual(aware.rows[0][-1], snap.rows[0][-1])
        for value in ('08:00:00', '2026-11-18', 'invalid', 1):
            with self.assertRaises(module.ImportErrorSafe):
                build([vm(last_check=value)])

    def test_invalid_timezone_and_ambiguous_legacy_time_block(self):
        for zone in ('Invalid/Private', True, ''):
            with self.assertRaises(module.ImportErrorSafe):
                build(zone=zone)
        with self.assertRaises(module.ImportErrorSafe):
            build([vm(last_check='2018-11-04T00:30:00')], zone='America/Sao_Paulo')

    def test_file_hashes_and_typed_projection_bound_to_digest(self):
        first = build()
        other = build([vm(name='OTHER_PRIVATE')])
        self.assertNotEqual(first.digest, other.digest)
        self.assertEqual(first.regionals_sha256, other.regionals_sha256)
        with self.assertRaises(module.ImportErrorSafe):
            module.build_vm_catalog(b'[{"id":"a","id":"b"}]', json.dumps(REGIONS).encode())

    def test_inspection_is_read_only(self):
        conn, cur = connection([('sentinel', 'sentinel_collector', 5433), (0,), (0,)], [[('REG_RIO_DE_JANEIRO',)]])
        result = module.inspect_vm_catalog(conn, build())
        self.assertTrue(result['tabelas_cadastro_vms_vazias'])
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'DELETE')) for call in cur.execute.call_args_list))

    def test_parameterized_atomic_bootstrap_and_exact_readback(self):
        snap = build()
        conn, cur = connection([('sentinel', 'sentinel_collector', 5433), (True,), (0,), (0,), (1,)],
                               [[('REG_RIO_DE_JANEIRO',)], list(snap.rows)])
        module.write_vm_catalog(conn, snap)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any('SECRET_PRIVATE' in str(call.args) for call in cur.execute.call_args_list))
        self.assertFalse(any(sql.startswith(('DELETE', 'UPDATE', 'TRUNCATE')) for sql in statements))
        self.assertFalse(any('operacional.servidores' in sql for sql in statements))
        self.assertFalse(any('SHARE ROW EXCLUSIVE' in sql for sql in statements))
        conn.commit.assert_not_called()

    def test_wrong_identity_lock_occupied_tables_missing_regional_and_bad_readback_block(self):
        for ones, lists in (([('other', 'other', 5432)], []),
                             ([('sentinel', 'sentinel_collector', 5433), (False,)], []),
                             ([('sentinel', 'sentinel_collector', 5433), (True,), (1,), (1,)], [[('REG_RIO_DE_JANEIRO',)]]),
                             ([('sentinel', 'sentinel_collector', 5433), (True,), (0,), (0,)], [[]]),
                             ([('sentinel', 'sentinel_collector', 5433), (True,), (0,), (0,), (1,)], [[('REG_RIO_DE_JANEIRO',)], []])):
            conn, _ = connection(ones, lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_vm_catalog(conn, build())
            conn.commit.assert_not_called()

    def test_cli_dry_run_no_secret_export_no_sql_and_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, regional = root / 'vms.json', root / 'regions.json'
            source.write_text(json.dumps([vm()]), encoding='utf-8')
            regional.write_text(json.dumps(REGIONS), encoding='utf-8')
            args = ['--source', str(source), '--regionals', str(regional)]
            original = source.read_bytes()
            with patch('services.operational_postgres.connect_collector') as connect, redirect_stdout(StringIO()) as out:
                self.assertEqual(module.main(args), 0)
                connect.assert_not_called()
            self.assertNotIn('PRIVATE', out.getvalue())
            self.assertEqual(source.read_bytes(), original)
            for computer, flags in (('OTHER', ['--apply']), ('RIGEL', ['--apply', '--expected-digest', 'wrong'])):
                with patch.dict(os.environ, {'COMPUTERNAME': computer}), redirect_stderr(StringIO()):
                    self.assertEqual(module.main([*args, *flags]), 1)
            with redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--check-database']), 1)

    def test_commit_failure_has_no_success_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, regional = root / 'vms.json', root / 'regions.json'
            source.write_text(json.dumps([vm()]), encoding='utf-8')
            regional.write_text(json.dumps(REGIONS), encoding='utf-8')
            args = ['--source', str(source), '--regionals', str(regional), '--apply', '--expected-digest', build().digest]
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                    patch('services.operational_postgres.connect_collector') as connect, \
                    patch.object(module, 'write_vm_catalog'), redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
                connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                self.assertEqual(module.main(args), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('SECRET_PRIVATE', err.getvalue())

    def test_ddl_has_only_registration_fields_and_limited_grants(self):
        sql = (module.ROOT / 'scripts/database/sql/018_vm_catalog.sql').read_text()
        self.assertIn('TO sentinel_reader', sql)
        self.assertIn('TO sentinel_collector', sql)
        self.assertNotIn('GRANT UPDATE', sql)
        self.assertNotIn('GRANT DELETE', sql)
        for forbidden in ('password', 'username', 'processors', 'memory', 'details'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
