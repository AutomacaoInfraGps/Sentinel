from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import import_admin_catalog as module


def sources():
    return [
        {'atualizado_em': '2026-11-18T07:00:00', 'dispositivos': {
            'FGT_TEST': {'nome': 'FGT_TEST', 'tipo': 'fortigate', 'admins': ['ACCOUNT_PRIVATE'],
                         'consulta_valida': True, 'ultima_coleta_valida': '2026-11-18T06:59:00',
                         'novos': ['ACCOUNT_PRIVATE'], 'motivo': 'SECRET_PRIVATE'},
            '__fortimanager__': {'nome': 'Central', 'tipo': 'fortimanager', 'admins': ['API_PRIVATE']}}},
        {'FGT_TEST': ['APPROVED_PRIVATE'], 'BASELINE_ONLY': ['KEEP_PRIVATE']},
        {'firewalls_por_regional': {'REG_TEST': [{'nome': 'FGT_TEST'}]}},
        {'regionais': {'REG_TEST': {'senha': 'SECRET_PRIVATE'}}}]


def build(values=None):
    return module.build_admin_catalog(*(json.dumps(value).encode() for value in values or sources()),
                                      'America/Sao_Paulo')


def connection(ones, lists):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class AdminCatalogTests(unittest.TestCase):
    def test_observations_baseline_and_differences_are_separate(self):
        snap = build()
        self.assertEqual(len(snap.devices), 3)
        self.assertIn(('BASELINE_ONLY', 'KEEP_PRIVATE'), snap.approved)
        self.assertNotIn(('FGT_TEST', 'ACCOUNT_PRIVATE'), snap.approved)
        self.assertIn(('FGT_TEST', 'ACCOUNT_PRIVATE', 'novo'), snap.differences)
        self.assertEqual(snap.published_at.isoformat(), '2026-11-18T10:00:00+00:00')

    def test_missing_evidence_is_not_inferred_as_valid(self):
        snap = build()
        central = next(row for row in snap.devices if row[0] == '__fortimanager__')
        self.assertIsNone(central[3])
        self.assertIsNone(central[7])
        self.assertIn(('__fortimanager__', 'API_PRIVATE', 'cache_sem_confirmacao_atual'), snap.observed)

    def test_failure_keeps_old_accounts_without_marking_fresh(self):
        values = sources()
        values[0]['dispositivos']['FGT_TEST'].update(consulta_valida=False, consulta_indisponivel=True)
        snap = build(values)
        self.assertIn(('FGT_TEST', 'ACCOUNT_PRIVATE', 'cache_sem_confirmacao_atual'), snap.observed)
        self.assertIsNotNone(next(row for row in snap.devices if row[0] == 'FGT_TEST')[-1])

    def test_unknown_and_ambiguous_bindings_are_nullable(self):
        for entries in ({'REG_TEST': [{'nome': 'OTHER'}]},
                        {'REG_TEST': [{'nome': 'FGT_TEST'}], 'REG_OTHER': [{'nome': 'FGT_TEST'}]}):
            values = sources()
            values[2]['firewalls_por_regional'] = entries
            values[3]['regionais']['REG_OTHER'] = {}
            row = next(row for row in build(values).devices if row[0] == 'FGT_TEST')
            self.assertIsNone(row[3])
            self.assertIn(row[4], ('ambiguo', 'nao_encontrado'))

    def test_no_credentials_accounts_or_names_in_summary_and_repr(self):
        snap = build()
        self.assertNotIn('PRIVATE', json.dumps(snap.summary()))
        self.assertNotIn('PRIVATE', repr(snap))
        self.assertNotIn('SECRET_PRIVATE', str(snap.devices))
        self.assertFalse(snap.summary()['baseline_modificada'])

    def test_lists_duplicates_and_identity_whitespace_rejected(self):
        for accounts in (None, {}, ['a', 'a'], [' a'], [3], [''], ['x\x00y']):
            values = sources()
            values[0]['dispositivos']['FGT_TEST']['admins'] = accounts
            with self.subTest(accounts=accounts), self.assertRaises(module.ImportErrorSafe):
                build(values)

    def test_case_sensitive_accounts_are_not_merged(self):
        values = sources()
        values[1]['FGT_TEST'] = ['Admin', 'admin']
        self.assertEqual(len([row for row in build(values).approved if row[0] == 'FGT_TEST']), 2)

    def test_invalid_flags_contradictions_dates_and_central_identity_rejected(self):
        for changes in ({'consulta_valida': 'true'}, {'offline': True},
                        {'ultima_coleta_valida': '07:00:00'},
                        {'ultima_coleta_valida': '2026-11-19T07:00:00'}, {'tipo': 'fortimanager'}):
            values = sources()
            values[0]['dispositivos']['FGT_TEST'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(module.ImportErrorSafe):
                build(values)

    def test_empty_sources_and_duplicate_json_keys_blocked(self):
        for index in range(4):
            values = sources()
            values[index] = {}
            with self.assertRaises(module.ImportErrorSafe):
                build(values)
        raw = [json.dumps(value).encode() for value in sources()]
        raw[1] = b'{"a":[],"a":[]}'
        with self.assertRaises(module.ImportErrorSafe):
            module.build_admin_catalog(*raw, 'America/Sao_Paulo')

    def test_raw_hashes_and_projection_are_digest_bound(self):
        first = build()
        values = sources()
        values[1]['BASELINE_ONLY'].append('ADDED_PRIVATE')
        self.assertNotEqual(first.digest, build(values).digest)
        self.assertEqual(first.hashes[0], build(values).hashes[0])

    def test_sql_parameterized_independent_inserts_and_no_updates(self):
        snap = build()
        expected = [1, len(snap.devices), len(snap.observed), len(snap.approved), len(snap.differences)]
        conn, cur = connection([('sentinel', 'sentinel_collector', 5433), (True,),
                                *((0,) for _ in module.TABLES), *((count,) for count in expected)],
                               [[('REG_TEST',)]])
        module.write_admin_catalog(conn, snap)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('ROW EXCLUSIVE MODE' in sql for sql in statements))
        self.assertFalse(any('SHARE ROW EXCLUSIVE' in sql for sql in statements))
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('UPDATE', 'DELETE', 'TRUNCATE')) for sql in statements))
        conn.commit.assert_not_called()

    def test_loaded_tables_lock_conflict_missing_regions_or_bad_counts_block(self):
        for ones, lists in (
            ([('sentinel', 'sentinel_collector', 5433), (False,)], []),
            ([('sentinel', 'sentinel_collector', 5433), (True,), (1,), (0,), (0,), (0,), (0,)], [[('REG_TEST',)]]),
            ([('sentinel', 'sentinel_collector', 5433), (True,), *((0,) for _ in module.TABLES)], [[]]),
            ([('sentinel', 'sentinel_collector', 5433), (True,), *((0,) for _ in module.TABLES), (9,)], [[('REG_TEST',)]])):
            conn, cur = connection(ones, lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_admin_catalog(conn, build())
            conn.commit.assert_not_called()

    def test_check_database_is_read_only(self):
        conn, cur = connection([('sentinel', 'sentinel_collector', 5433), *((0,) for _ in module.TABLES)],
                               [[('REG_TEST',)]])
        result = module.inspect_admin_catalog(conn, build())
        self.assertTrue(result['tabelas_monitor_admins_vazias'])
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'DELETE')) for call in cur.execute.call_args_list))

    def test_cli_dry_run_and_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, value in enumerate(sources()):
                path = Path(directory) / f'{index}.json'
                path.write_text(json.dumps(value), encoding='utf-8')
                paths.extend((('--cache', '--baseline', '--firewalls', '--regionals')[index], str(path)))
            args = [*paths, '--source-timezone', 'America/Sao_Paulo']
            with patch.dict(os.environ, {'COMPUTERNAME': 'NOT_RIGEL'}), redirect_stdout(StringIO()) as out:
                self.assertEqual(module.main(args), 0)
            self.assertEqual(json.loads(out.getvalue())['modo'], 'simulacao_sem_conexao_ao_banco')
            for flags in (['--apply'], ['--check-database']):
                with patch.dict(os.environ, {'COMPUTERNAME': 'NOT_RIGEL'}), redirect_stderr(StringIO()):
                    self.assertEqual(module.main([*args, *flags]), 1)
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), redirect_stderr(StringIO()):
                self.assertEqual(module.main([*args, '--apply', '--expected-digest', 'wrong']), 1)
            with redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source-timezone', 'America/Sao_Paulo', '--check-database']), 1)

    def test_sql_restricts_sensitive_tables(self):
        sql = (module.ROOT / 'scripts/database/sql/016_admin_monitor_catalog.sql').read_text()
        self.assertIn('FROM PUBLIC, sentinel_reader, sentinel_api', sql)
        self.assertIn('TO sentinel_admins_reader', sql)
        self.assertNotIn('GRANT DELETE', sql)
        self.assertNotIn('GRANT UPDATE', sql)
        self.assertNotIn('TO sentinel_api', sql)

    def test_cli_does_not_report_success_before_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ['--source-timezone', 'America/Sao_Paulo', '--apply', '--expected-digest', build().digest]
            for flag, value in zip(('cache', 'baseline', 'firewalls', 'regionals'), sources()):
                path = Path(directory) / (flag + '.json')
                path.write_text(json.dumps(value), encoding='utf-8')
                args.extend(('--' + flag, str(path)))
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                    patch('services.operational_postgres.connect_collector') as connect, \
                    patch.object(module, 'write_admin_catalog'), \
                    redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as error:
                connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                self.assertEqual(module.main(args), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('SECRET_PRIVATE', error.getvalue())


if __name__ == '__main__':
    unittest.main()
