from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import import_regional_metadata_catalog as module
from tests.unit.operational_certificate_catalog_test import connection, IDENTITY
from tests.unit.operational_regional_metadata_sources_audit_test import payload

NOW = datetime(2026, 11, 19, 13, tzinfo=timezone.utc)


def frozen(original=None):
    return module.capture_payload(json.dumps(original or payload()).encode(), NOW)


def raw_capture():
    return json.dumps(frozen()).encode()


def build():
    return module.build_catalog(raw_capture())


def main_rows(catalog):
    return [(row[0], row[1], True) for row in catalog.rows]


class RegionalMetadataCatalogTests(unittest.TestCase):
    def test_capture_whitelists_metadata_and_keeps_naive_publication_text(self):
        original = payload()
        original['configuracao']['ultima_atualizacao'] = '2026-11-19T09:00:00'
        original['regionais']['REG_PRIVATE']['servidores'] = [{'password': 'ACCESS_PRIVATE', 'ip': '192.0.2.1'}]
        snap = frozen(original)
        encoded = json.dumps(snap)
        self.assertNotIn('SECRET_PRIVATE', encoded)
        self.assertNotIn('ACCESS_PRIVATE', encoded)
        self.assertNotIn('192.0.2.1', encoded)
        self.assertNotIn('servidores', encoded)
        self.assertEqual(snap['publicacao_textual'], '2026-11-19T09:00:00')
        catalog = module.build_catalog(encoded.encode())
        self.assertEqual(catalog.summary()['publicacao_cadastro'], 'sem_fuso')
        self.assertNotIn('PRIVATE', json.dumps(catalog.summary()) + repr(catalog))

    def test_uf_conflicts_unknown_values_padding_and_missing_fields_block(self):
        for entry in ({'uf': 'RJ'}, {'estado': 'sp', 'uf': 'sp'}, {'estado': 'XX', 'uf': 'XX'},
                      {'descricao': None}, {'descricao': ''}, {'nome': 123}, {'descricao': 'X' * 501},
                      {'nome': ' NAME_PRIVATE'}, {'descricao': 'X\x00Y'}):
            with self.assertRaises(module.ImportErrorSafe) as error:
                frozen(payload(**entry))
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_envelopes_codes_duplicates_nontext_or_empty_records_block(self):
        for value in ({}, {'regionais': {}, 'configuracao': {}},
                      {'regionais': {'reg_private': {}}, 'configuracao': {}},
                      {'regionais': {'REG_PRIVATE': None}, 'configuracao': {}}):
            with self.assertRaises(module.ImportErrorSafe):
                module.capture_payload(json.dumps(value).encode(), NOW)
        snap = frozen()
        snap['regionais'] *= 2
        with self.assertRaises(module.ImportErrorSafe):
            module.build_catalog(json.dumps(snap).encode())

    def test_hashes_bind_capture_projection_source_and_publication(self):
        original = frozen()
        self.assertEqual(original, frozen())
        self.assertNotEqual(original['digest_carga'], frozen(payload(descricao='OTHER_PRIVATE'))['digest_carga'])
        for key, value in (('digest_carga', 'a' * 64), ('sha256_metadados', 'a' * 64),
                           ('sha256_arquivo_origem', 'b' * 64), ('capturado_em', '2026-11-19T14:00:00Z')):
            changed = {**original, key: value}
            with self.assertRaises(module.ImportErrorSafe):
                module.build_catalog(json.dumps(changed).encode())

    def test_frozen_extra_fields_noncanonical_order_invalid_types_or_naive_capture_block(self):
        for mutate in (lambda p: p.update(version=True), lambda p: p.update(password='SECRET_PRIVATE'),
                       lambda p: p.update(capturado_em='2026-11-19T13:00:00'),
                       lambda p: p['regionais'][0].update(username='PRIVATE'),
                       lambda p: p.update(publicacao_textual='PRIVATE')):
            snap = frozen()
            mutate(snap)
            snap['digest_carga'] = module._hash({key: value for key, value in snap.items() if key != 'digest_carga'})
            with self.assertRaises(module.ImportErrorSafe):
                module.build_catalog(json.dumps(snap).encode())
        for raw in (b'{"version":1,"version":2}', b'{PRIVATE'):
            with self.assertRaises(module.ImportErrorSafe):
                module.build_catalog(raw)

    def test_inspect_is_readonly_and_returns_destination_counts_without_labels(self):
        catalog = build()
        conn, cur = connection([IDENTITY, (0,), (0,)], [main_rows(catalog), [], []])
        report = module.inspect_catalog(conn, catalog)
        self.assertTrue(report['tabelas_metadados_vazias'])
        self.assertFalse(report['conteudo_confere_com_captura'])
        self.assertEqual(report['nomes_regionais_divergentes'], 0)
        self.assertNotIn('PRIVATE', json.dumps(report))
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('READ ONLY' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'LOCK')) for sql in statements))

    def test_atomic_inserts_full_readback_without_updating_original_regionals(self):
        catalog = build()
        conn, cur = connection([IDENTITY, (True,), (0,), (0,)],
                               [main_rows(catalog), [catalog.source], list(catalog.rows)])
        module.write_catalog(conn, catalog)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any(sql.startswith(('UPDATE', 'DELETE', 'TRUNCATE')) for sql in statements))
        self.assertTrue(any('LOCK TABLE operacional.regionais IN SHARE MODE' == sql for sql in statements))
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertEqual(sum(sql.startswith('INSERT') for sql in statements), 2)
        conn.commit.assert_not_called()

    def test_wrong_identity_lock_existing_data_or_regional_divergence_blocks(self):
        catalog = build()
        for ones, lists in (([('other', 'other', 5432)], []), ([IDENTITY, (False,)], []),
                            ([IDENTITY, (True,), (1,), (1,)], [main_rows(catalog)]),
                            ([IDENTITY, (True,), (0,), (0,)], [[]]),
                            ([IDENTITY, (True,), (0,), (0,)], [[('REG_PRIVATE', 'OTHER_PRIVATE', True)]]),
                            ([IDENTITY, (True,), (0,), (0,)], [[('REG_PRIVATE', 'NAME_PRIVATE', False)]])):
            conn, cur = connection(ones, lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, catalog)
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cur.execute.call_args_list))

    def test_source_or_rows_readback_mismatch_blocks(self):
        catalog = build()
        for source, rows in (([], list(catalog.rows)), ([catalog.source], [])):
            conn, _ = connection([IDENTITY, (True,), (0,), (0,)], [main_rows(catalog), source, rows])
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, catalog)
            conn.commit.assert_not_called()

    def test_cli_freezes_safe_projection_without_sql_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = json.dumps(payload()).encode()
            (root / 'estrutura_regionais.json').write_bytes(original)
            path = root / 'metadata.json'
            with patch.object(module, 'ROOT', root), patch('services.operational_postgres.connect_collector') as connect, \
                    redirect_stdout(StringIO()) as out:
                self.assertEqual(module.main(['--capture', str(path)]), 0)
                connect.assert_not_called()
            self.assertNotIn('PRIVATE', out.getvalue())
            self.assertNotIn('SECRET_PRIVATE', path.read_text())
            self.assertEqual((root / 'estrutura_regionais.json').read_bytes(), original)
            before = path.read_bytes()
            with patch.object(module, 'ROOT', root), redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--capture', str(path)]), 1)
            self.assertEqual(path.read_bytes(), before)
            with redirect_stdout(StringIO()):
                self.assertEqual(module.main(['--source', str(path)]), 0)

    def test_cli_guards_missing_source_wrong_machine_digest_and_changing_file(self):
        for computer, digest in (('OTHER', build().digest), ('RIGEL', 'bad')):
            with patch.object(Path, 'read_bytes', return_value=raw_capture()), \
                    patch.dict(os.environ, {'COMPUTERNAME': computer}), \
                    patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', digest]), 1)
                connect.assert_not_called()
        with patch.object(Path, 'read_bytes', side_effect=[raw_capture(), b'changed']), \
                patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
            self.assertEqual(module.main(['--source', 'unused', '--apply']), 1)
            connect.assert_not_called()
        with redirect_stderr(StringIO()):
            self.assertEqual(module.main(['--apply']), 1)

    def test_cli_success_only_after_commit_and_failures_redacted(self):
        for failed in (False, True):
            with patch.object(Path, 'read_bytes', return_value=raw_capture()), \
                    patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                    patch('services.operational_postgres.connect_collector') as connect, \
                    patch.object(module, 'write_catalog'), redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
                if failed:
                    connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', build().digest]), int(failed))
            self.assertNotIn('PRIVATE', out.getvalue() + err.getvalue())
            if failed:
                self.assertEqual(out.getvalue(), '')
            else:
                self.assertEqual(json.loads(out.getvalue())['modo'], 'carga_inicial_metadados_regionais_confirmada')

    def test_schema_fk_restricted_reader_and_no_uf_inference_or_original_updates(self):
        sql = (module.ROOT / 'scripts/database/sql/025_regional_metadata_catalog.sql').read_text()
        self.assertIn('REFERENCES operacional.regionais(codigo)', sql)
        self.assertIn('CHECK (uf = estado)', sql)
        self.assertIn('TO sentinel_regionais_metadados_reader', sql)
        for forbidden in ('TO sentinel_reader', 'TO sentinel_api', 'GRANT UPDATE', 'GRANT DELETE',
                          'UPDATE operacional.regionais', 'ALTER TABLE operacional.regionais'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
