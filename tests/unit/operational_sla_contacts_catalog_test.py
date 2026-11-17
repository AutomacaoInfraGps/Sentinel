from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from openpyxl import Workbook
from scripts.database import import_sla_contacts as module

REGIONS = {'regionais': {'REG_BAHIA': {'nome': 'Bahia', 'senha': 'SECRET_PRIVATE'}}}


def record(**changes):
    return {'NOME_REGIONAL': 'V021_BAHIA', 'NOME_REG_FORTI': 'REPORT_BAHIA',
            'NOME_DIRETOR_1': 'PERSON_PRIVATE', 'EMAIL_DIRETOR': 'EMAIL_PRIVATE@example.test', **changes}


def workbook(records=None, *, sheet='Contacts', headers=None):
    book = Workbook()
    page = book.active
    page.title = sheet
    columns = headers or module.CONTACT_COLUMNS
    page.append(list(columns))
    for item in records if records is not None else [record()]:
        page.append([item.get(column) for column in columns])
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def catalog():
    return module.build_contact_catalog(workbook(), json.dumps(REGIONS).encode(), 'Contacts')


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class SlaContactsCatalogTest(unittest.TestCase):
    def test_typed_projection_and_summary_do_not_expose_people(self):
        snap = catalog()
        self.assertEqual(snap.assignments[0], ('REG_BAHIA', 'V021_BAHIA', 'REPORT_BAHIA', 'identidade_normalizada_unica', 2))
        self.assertEqual(snap.contacts[0], ('REG_BAHIA', 'diretor', 'PERSON_PRIVATE', 'EMAIL_PRIVATE@example.test'))
        self.assertEqual(snap.summary()['vinculos_contato_regional_papel'], 1)
        self.assertNotIn('PRIVATE', json.dumps(snap.summary()))
        self.assertNotIn('PRIVATE', repr(snap))

    def test_roles_preserved_and_same_email_never_merges_people(self):
        row = record(NOME_GERENTE='OTHER_PRIVATE', EMAIL_GERENTE='EMAIL_PRIVATE@example.test',
                     NOME_APOIO_1='SEM_APOIO', EMAIL_APOIO_1='SEM_EMAIL',
                     NOME_APOIO_2='', EMAIL_APOIO_2='SHARED_PRIVATE@example.test')
        snap = module.build_contact_catalog(workbook([row]), json.dumps(REGIONS).encode(), 'Contacts')
        self.assertEqual(len(snap.contacts), 3)
        self.assertEqual(snap.summary()['emails_sem_nome'], 1)
        self.assertFalse(snap.summary()['pessoas_fundidas_automaticamente'])

    def test_unknown_ambiguous_and_duplicate_target_block_load(self):
        for rows, regions in (([record(NOME_REGIONAL='Unknown')], REGIONS),
                              ([record(), record()], REGIONS),
                              ([record(), record(NOME_REGIONAL='REG_BAHIA', NOME_REG_FORTI='Other')], REGIONS),
                              ([record()], {'regionais': {'REG_ONE': {'nome': 'Bahia'}, 'REG_TWO': {'nome': 'Bahia'}}})):
            with self.subTest(rows=len(rows)), self.assertRaises(module.ImportErrorSafe):
                module.build_contact_catalog(workbook(rows), json.dumps(regions).encode(), 'Contacts')

    def test_verified_alias_keeps_labels_and_uses_correct_macae(self):
        row = record(NOME_REGIONAL='V049_REGIONAL_MACAE01', NOME_REG_FORTI='REPORT DE SEGURANCA-FTG_REGMACAE01')
        snap = module.build_contact_catalog(workbook([row]), json.dumps({'regionais': {'REG_MACAE': {}, 'REG_GRSA_MACAE': {}}}).encode(), 'Contacts')
        self.assertEqual(snap.assignments[0][0], 'REG_MACAE')
        self.assertEqual(snap.assignments[0][1], row['NOME_REGIONAL'])
        self.assertEqual(snap.assignments[0][3], 'alias_sla_verificado')

    def test_invalid_cells_formulas_headers_and_wrong_sheet_are_rejected(self):
        for content in (workbook([record(NOME_GERENTE='=PRIVATE()')]),
                        workbook([record(NOME_DIRETOR_1=42)]),
                        workbook(headers=(*module.CONTACT_COLUMNS, 'NOME_REGIONAL')),
                        workbook(headers=module.CONTACT_COLUMNS[:-1])):
            with self.assertRaises(module.ImportErrorSafe):
                module.build_contact_catalog(content, json.dumps(REGIONS).encode(), 'Contacts')
        with self.assertRaises(module.ImportErrorSafe):
            module.build_contact_catalog(workbook(), json.dumps(REGIONS).encode(), 'Missing')

    def test_empty_or_invalid_sources_block_without_error_values(self):
        for content in (workbook([]), workbook([record(NOME_DIRETOR_1='', EMAIL_DIRETOR='')])):
            with self.assertRaises(module.ImportErrorSafe):
                module.build_contact_catalog(content, json.dumps(REGIONS).encode(), 'Contacts')
        with self.assertRaises(module.ImportErrorSafe):
            module.build_contact_catalog(workbook(), b'{"regionais":{}}', 'Contacts')

    def test_digest_covers_file_catalog_and_projection(self):
        raw = workbook()
        regions = json.dumps(REGIONS).encode()
        first = module.build_contact_catalog(raw, regions, 'Contacts')
        self.assertEqual(first.digest, module.build_contact_catalog(raw, regions, 'Contacts').digest)
        changed = deepcopy(REGIONS)
        changed['regionais']['REG_OTHER'] = {}
        self.assertNotEqual(first.digest, module.build_contact_catalog(raw, json.dumps(changed).encode(), 'Contacts').digest)
        self.assertNotEqual(first.digest, module.build_contact_catalog(workbook([record(NOME_DIRETOR_1='Different')]), regions, 'Contacts').digest)

    def test_writer_uses_bound_values_verifies_counts_and_leaves_commit_to_caller(self):
        snap = catalog()
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (True,), (0,), (0,), (0,), (1,), (1,), (1,)],
                                  [[('REG_BAHIA',)], [('REG_BAHIA',)], [('diretor', 1)]])
        module.write_contact_catalog(conn, snap)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(sum(statement.startswith('LOCK') for statement in sql), 4)
        self.assertIn('LOCK TABLE operacional.regionais IN ACCESS SHARE MODE', sql)
        for table in module.TABLES:
            self.assertIn('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE', sql)
        self.assertFalse(any('SHARE ROW EXCLUSIVE' in statement for statement in sql))
        advisory_index = next(i for i, statement in enumerate(sql) if 'pg_try_advisory_xact_lock' in statement)
        first_count_index = next(i for i, statement in enumerate(sql) if statement.startswith('SELECT count(*)'))
        self.assertLess(advisory_index, first_count_index)
        self.assertEqual(sum(statement.startswith('INSERT') for statement in sql), 3)
        for call in cursor.execute.call_args_list:
            self.assertNotIn('PRIVATE', call.args[0])
            self.assertFalse(call.args[0].startswith(('UPDATE', 'DELETE')))
            if len(call.args) == 2:
                self.assertEqual(call.args[0].count('%s'), len(call.args[1]))
        conn.commit.assert_not_called()

    def test_occupied_or_missing_regional_blocks_before_insert(self):
        for counts, regions in (((1, 0, 0), [('REG_BAHIA',)]), ((0, 0, 0), [])):
            conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (True,), *((n,) for n in counts)], [regions])
            with self.assertRaises(module.ImportErrorSafe):
                module.write_contact_catalog(conn, catalog())
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cursor.execute.call_args_list))

    def test_post_insert_count_mismatch_cancels(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (True,), (0,), (0,), (0,), (1,), (1,), (0,)],
                                  [[('REG_BAHIA',)], [('REG_BAHIA',)]])
        with self.assertRaises(module.ImportErrorSafe):
            module.write_contact_catalog(conn, catalog())
        conn.commit.assert_not_called()

    def test_concurrent_bootstrap_is_refused_before_counts_or_inserts(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (False,)])
        with self.assertRaises(module.ImportErrorSafe):
            module.write_contact_catalog(conn, catalog())
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any(statement.startswith(('LOCK', 'INSERT', 'SELECT count(*)')) for statement in sql))
        cursor.fetchall.assert_not_called()

    def test_writer_table_lock_modes_work_with_select_insert_permissions(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (True,), (0,), (0,), (0,), (1,), (1,), (1,)],
                                  [[('REG_BAHIA',)], [('REG_BAHIA',)], [('diretor', 1)]])
        def enforce_least_privilege(sql, *parameters):
            if sql.startswith('LOCK TABLE'):
                permitted = (' IN ACCESS SHARE MODE', ' IN ROW EXCLUSIVE MODE')
                if not sql.endswith(permitted):
                    raise PermissionError('Lock requires privileges not granted by migration 014')
        cursor.execute.side_effect = enforce_least_privilege
        module.write_contact_catalog(conn, catalog())
        conn.commit.assert_not_called()

    def test_inspection_never_writes(self):
        conn, cursor = connection([('sentinel', 'sentinel_collector', 5433), (0,), (0,), (0,)], [[('REG_BAHIA',)]])
        self.assertTrue(module.inspect_contact_catalog(conn, catalog())['tabelas_contatos_vazias'])
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'DELETE', 'LOCK')) for call in cursor.execute.call_args_list))

    def test_cli_simulates_without_sql_and_does_not_change_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, regions = root / 'contacts.xlsx', root / 'regions.json'
            source.write_bytes(workbook())
            regions.write_text(json.dumps(REGIONS), encoding='utf-8')
            before = source.read_bytes()
            output = StringIO()
            with patch('services.operational_postgres.connect_collector') as connect, redirect_stdout(output):
                self.assertEqual(module.main(['--source', str(source), '--sheet', 'Contacts', '--regionals', str(regions)]), 0)
                connect.assert_not_called()
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(json.loads(output.getvalue())['modo'], 'simulacao_sem_conexao_ao_banco')
            self.assertNotIn('PRIVATE', output.getvalue())

    def test_cli_requires_frozen_arguments_exact_digest_and_successful_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, regions = root / 'contacts.xlsx', root / 'regions.json'
            source.write_bytes(workbook())
            regions.write_text(json.dumps(REGIONS), encoding='utf-8')
            args = ['--source', str(source), '--sheet', 'Contacts', '--regionals', str(regions), '--apply']
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(args + ['--expected-digest', 'wrong']), 1)
                connect.assert_not_called()
                self.assertEqual(module.main(['--check-database']), 1)
                connect.assert_not_called()
                snap = module.build_contact_catalog(source.read_bytes(), regions.read_bytes(), 'Contacts')
                connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                output = StringIO()
                with patch.object(module, 'write_contact_catalog'), redirect_stdout(output):
                    self.assertEqual(module.main(args + ['--expected-digest', snap.digest]), 1)
                self.assertEqual(output.getvalue(), '')

    def test_migration_limits_access_to_contact_reader_and_collector(self):
        sql = (Path(__file__).resolve().parents[2] / 'scripts/database/sql/014_sla_contacts.sql').read_text(encoding='utf-8')
        self.assertIn('CREATE ROLE sentinel_contatos_reader NOLOGIN', sql)
        self.assertIn('FROM PUBLIC, sentinel_reader, sentinel_api', sql)
        self.assertIn('SET LOCAL ROLE sentinel_owner', sql)
        self.assertIn("'E:/Sentinel/PostgreSQL/data'", sql)
        self.assertIn('PRIMARY KEY(fonte_id,codigo_regional,papel)', sql)
        self.assertNotIn(' TO sentinel_reader', sql)
        self.assertNotIn(' TO sentinel_api', sql)
        for forbidden in ('GRANT ALL', 'GRANT DELETE', 'GRANT UPDATE', 'TO PUBLIC'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
