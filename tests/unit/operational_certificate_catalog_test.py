from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import import_certificate_catalog as module

NOW = datetime(2026, 11, 18, 15, tzinfo=timezone.utc)
IDENTITY = ('sentinel', 'sentinel_collector', 5433)


def record(**changes):
    return {'thumbprint': 'A' * 40, 'subject': 'SUBJECT_PRIVATE', 'issuer': 'ISSUER_PRIVATE',
            'notAfter': '2026-12-31T12:00:00-03:00', **changes}


def build(value=None):
    return module.build_certificate_catalog(json.dumps([record()] if value is None else value).encode())


def source_row(catalog):
    return (module.SOURCE_ID, catalog.source_sha256, catalog.digest, False, None, None, None, None)


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


class CertificateCatalogTests(unittest.TestCase):
    def test_origin_host_store_region_and_collection_stay_unknown(self):
        summary = build().summary(NOW)
        self.assertFalse(summary['origem_confirmada'])
        for key in ('host_origem', 'repositorio_origem', 'codigo_regional', 'coletado_em'):
            self.assertIsNone(summary[key])
        self.assertFalse(summary['coletor_executado'])
        self.assertFalse(summary['sincronizacao_automatica_certificados'])

    def test_repeated_subject_different_thumbprints_and_expired_certificates_retained(self):
        values = [record(), record(thumbprint='B' * 40, notAfter='2020-01-01T00:00:00Z')]
        snap = build(values)
        self.assertEqual(len(snap.rows), 2)
        self.assertEqual(snap.summary(NOW)['assuntos_repetidos_sem_fusao'], 1)
        self.assertEqual(snap.summary(NOW)['validade_apenas_temporal']['expirado'], 1)

    def test_thumbprints_normalize_but_textual_value_is_retained(self):
        snap = build([record(thumbprint='aa ' * 19 + 'aa')])
        self.assertEqual(snap.rows[0][1], 'aa ' * 19 + 'aa')
        self.assertEqual(snap.rows[0][2], 'A' * 40)
        self.assertEqual(build([record(thumbprint='b' * 64)]).rows[0][2], 'B' * 64)

    def test_duplicate_normalized_thumbprint_blocks_instead_of_merging(self):
        for second in (record(), record(thumbprint='aa ' * 19 + 'aa'), record(issuer='OTHER_PRIVATE')):
            with self.assertRaises(module.ImportErrorSafe) as error:
                build([record(), second])
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_single_object_aliases_and_alias_conflicts(self):
        entry = {'Thumbprint': 'A' * 40, 'Subject': 'SUBJECT_PRIVATE',
                 'Issuer': 'ISSUER_PRIVATE', 'NotAfter': '2026-12-31T15:00:00Z'}
        self.assertEqual(len(build(entry).rows), 1)
        entry['subject'] = 'OTHER_PRIVATE'
        with self.assertRaises(module.ImportErrorSafe):
            build(entry)

    def test_unknown_fields_and_material_sensitive_fields_are_not_imported(self):
        for extra in ({'privateKey': 'SECRET_PRIVATE'}, {'password': 'SECRET_PRIVATE'},
                      {'rawData': 'RAW_PRIVATE'}, {'host': 'HOST_PRIVATE'},
                      {'store': 'STORE_PRIVATE'}, {'coletado_em': '2026-11-18T00:00:00Z'},
                      {'HasPrivateKey': False}, {'arbitrary': {'nested': 'SECRET_PRIVATE'}}):
            with self.assertRaises(module.ImportErrorSafe) as error:
                build([record(**extra)])
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_invalid_envelopes_empty_lists_missing_fields_and_nontext_values_block(self):
        for value in ([], None, 'PRIVATE', [None], [record(subject=None)],
                      [record(issuer=123)], [record(thumbprint='PRIVATE')],
                      [record(subject=False, Subject='PRIVATE')], [record(subject='X' * 4001)]):
            if value is None:
                with self.assertRaises(module.ImportErrorSafe):
                    module.build_certificate_catalog(b'null')
            else:
                with self.assertRaises(module.ImportErrorSafe):
                    build(value)

    def test_aware_expiration_preserves_text_and_converts_to_utc(self):
        snap = build()
        self.assertEqual(snap.rows[0][5], '2026-12-31T12:00:00-03:00')
        self.assertEqual(snap.rows[0][6].isoformat(), '2026-12-31T15:00:00+00:00')
        self.assertEqual(snap.rows[0][6], build([record(notAfter='2026-12-31T15:00:00Z')]).rows[0][6])

    def test_naive_missing_localized_or_legacy_expirations_block_without_timezone_guess(self):
        for value in ('2026-12-31T12:00:00', '2026-12-31', '31/12/2026 12:00:00',
                      '/Date(1234)/', 'PRIVATE', None, 1):
            with self.assertRaises(module.ImportErrorSafe):
                build([record(notAfter=value)])

    def test_temporal_status_is_dynamic_not_in_digest_or_persistent_projection(self):
        snap = build([record(notAfter=NOW.isoformat())])
        first, later = snap.summary(NOW), snap.summary(NOW + timedelta(seconds=1))
        self.assertEqual(first['validade_apenas_temporal'], {'a_vencer_menos_30_dias': 1})
        self.assertEqual(later['validade_apenas_temporal'], {'expirado': 1})
        self.assertEqual(first['digest_carga'], later['digest_carga'])
        self.assertFalse(first['status_de_validade_persistido'])
        self.assertFalse(first['confianca_criptografica_validada'])

    def test_hash_digest_and_summary_are_bound_without_raw_metadata_exports(self):
        snap = build()
        self.assertNotEqual(snap.digest, build([record(issuer='OTHER_PRIVATE')]).digest)
        self.assertNotIn('PRIVATE', json.dumps(snap.summary(NOW)) + repr(snap))
        self.assertNotIn('A' * 40, json.dumps(snap.summary(NOW)))

    def test_duplicate_keys_invalid_json_and_bom(self):
        for raw in (b'[{"thumbprint":"a","thumbprint":"b"}]', b'{PRIVATE'):
            with self.assertRaises(module.ImportErrorSafe):
                module.build_certificate_catalog(raw)
        raw = b'\xef\xbb\xbf' + json.dumps([record()]).encode()
        self.assertEqual(len(module.build_certificate_catalog(raw).rows), 1)

    def test_inspection_read_only(self):
        conn, cur = connection([IDENTITY, (0,), (0,)])
        self.assertTrue(module.inspect_certificate_catalog(conn)['tabelas_certificados_legados_vazias'])
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('READ ONLY' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'DELETE')) for sql in statements))

    def test_atomic_parameterized_insert_and_full_typed_readback(self):
        snap = build()
        conn, cur = connection([IDENTITY, (True,), (0,), (0,)], [[source_row(snap)], list(snap.rows)])
        module.write_certificate_catalog(conn, snap)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('UPDATE', 'DELETE', 'TRUNCATE')) for sql in statements))
        self.assertFalse(any('SHARE ROW EXCLUSIVE' in sql for sql in statements))
        conn.commit.assert_not_called()

    def test_wrong_identity_occupied_lock_or_existing_data_blocks(self):
        for values in ([('other', 'other', 5432)], [IDENTITY, (False,)], [IDENTITY, (True,), (1,), (3,)]):
            conn, cur = connection(values)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_certificate_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cur.execute.call_args_list))

    def test_unknown_origin_or_certificate_readback_mismatch_cancels(self):
        snap = build()
        incorrect_source = (*source_row(snap)[:4], 'HOST_PRIVATE', None, None, None)
        for lists in ([[incorrect_source], list(snap.rows)], [[source_row(snap)], []]):
            conn, _ = connection([IDENTITY, (True,), (0,), (0,)], lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_certificate_catalog(conn, snap)
            conn.commit.assert_not_called()

    def test_cli_dry_run_never_connects_or_changes_source_and_guards_sql(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'metadata.json'
            original = json.dumps([record()]).encode()
            source.write_bytes(original)
            args = ['--source', str(source)]
            with patch('services.operational_postgres.connect_collector') as connect, redirect_stdout(StringIO()) as out:
                self.assertEqual(module.main(args), 0)
                connect.assert_not_called()
            self.assertNotIn('PRIVATE', out.getvalue())
            self.assertEqual(source.read_bytes(), original)
            for computer, flags in (('OTHER', ['--apply']), ('RIGEL', ['--apply', '--expected-digest', 'wrong'])):
                with patch.dict(os.environ, {'COMPUTERNAME': computer}), redirect_stderr(StringIO()), \
                        patch('services.operational_postgres.connect_collector') as connect:
                    self.assertEqual(module.main([*args, *flags]), 1)
                    connect.assert_not_called()
            with redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--check-database']), 1)

    def test_changed_source_blocks_before_sql_connection(self):
        raw = json.dumps([record()]).encode()
        with patch.object(Path, 'read_bytes', side_effect=[raw, b'[]']), \
                patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
            self.assertEqual(module.main(['--source', 'unused', '--apply']), 1)
            connect.assert_not_called()

    def test_commit_failure_has_no_success_or_raw_exception_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'metadata.json'
            source.write_text(json.dumps([record()]), encoding='utf-8')
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                    patch('services.operational_postgres.connect_collector') as connect, \
                    patch.object(module, 'write_certificate_catalog'), \
                    redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
                connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                self.assertEqual(module.main(['--source', str(source), '--apply', '--expected-digest', build().digest]), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('SECRET_PRIVATE', err.getvalue())

    def test_migration_restricted_reader_null_origin_and_metadata_only(self):
        sql = (module.ROOT / 'scripts/database/sql/021_certificate_legacy_catalog.sql').read_text()
        self.assertIn('CREATE ROLE sentinel_certificados_reader NOLOGIN', sql)
        self.assertIn('TO sentinel_certificados_reader', sql)
        self.assertNotIn('TO sentinel_reader', sql)
        self.assertNotIn('TO sentinel_api', sql)
        self.assertNotIn('GRANT UPDATE', sql)
        self.assertNotIn('GRANT DELETE', sql)
        for field in ('host_origem', 'repositorio_origem', 'codigo_regional', 'coletado_em'):
            self.assertIn('CHECK (' + field + ' IS NULL)', sql)
        for forbidden in ('password', 'private_key', 'pfx', 'pem'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
