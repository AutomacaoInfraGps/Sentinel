from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import import_switch_firmware_catalog as module
from tests.unit.operational_certificate_catalog_test import connection, IDENTITY
from tests.unit.operational_switch_firmware_capture_test import capture


def raw_capture():
    return json.dumps(capture()).encode()


def build():
    return module.build_catalog(raw_capture())


class FirmwareCatalogTests(unittest.TestCase):
    def test_typed_projection_preserves_source_and_diagnosis_without_binding(self):
        catalog = build()
        self.assertEqual(catalog.rows[0][1:8], ('192.0.2.1', 'NAME_PRIVATE', 'REG_PRIVATE',
                         '192.0.2.1', 'MODEL_PRIVATE', 'VERSION_PRIVATE', '2026-11-18T16:00:00Z'))
        self.assertEqual(catalog.rows[0][8].isoformat(), '2026-11-18T16:00:00+00:00')
        self.assertEqual(catalog.rows[0][-2:], ('ip_e_nome_concordantes_candidato', False))
        self.assertEqual(catalog.source[-1], catalog.digest)
        self.assertNotIn('PRIVATE', repr(catalog) + json.dumps(catalog.report))

    def test_tampered_or_extra_fields_rejected_before_database(self):
        for change in (lambda p: p.update(digest_carga='a' * 64),
                       lambda p: p['registros'][0].update(hostid='123'),
                       lambda p: p['registros'][0].update(checked_at_utc='2026-11-18T16:00:00')):
            payload = capture()
            change(payload)
            with self.assertRaises(module.ImportErrorSafe):
                module.build_catalog(json.dumps(payload).encode())

    def test_inspection_is_read_only_and_checks_full_content(self):
        catalog = build()
        conn, cur = connection([IDENTITY, (1,), (1,)], [[catalog.source], list(catalog.rows)])
        result = module.inspect_catalog(conn, catalog)
        self.assertFalse(result['tabelas_firmware_vazias'])
        self.assertTrue(result['conteudo_confere_com_captura'])
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('READ ONLY' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'LOCK')) for sql in statements))

    def test_atomic_parameterized_write_and_typed_readback(self):
        catalog = build()
        conn, cur = connection([IDENTITY, (True,), (0,), (0,)], [[catalog.source], list(catalog.rows)])
        module.write_catalog(conn, catalog)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('UPDATE', 'DELETE', 'TRUNCATE')) for sql in statements))
        inserts = [call for call in cur.execute.call_args_list if call.args[0].startswith('INSERT')]
        self.assertEqual(len(inserts), 2)
        self.assertEqual(inserts[1].args[1], (module.SOURCE, *catalog.rows[0]))
        self.assertEqual(inserts[1].args[0].count('%s'), len(inserts[1].args[1]))
        conn.commit.assert_not_called()

    def test_wrong_identity_busy_lock_or_existing_data_prevents_insert(self):
        for ones in ([('other', 'other', 5432)], [IDENTITY, (False,)],
                     [IDENTITY, (True,), (1,), (140,)], [IDENTITY, (True,), (0,), (1,)]):
            conn, cur = connection(ones)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, build())
            self.assertFalse(any(call.args[0].startswith('INSERT') for call in cur.execute.call_args_list))

    def test_any_readback_divergence_blocks_commit(self):
        catalog = build()
        for lists in (([], list(catalog.rows)), ([catalog.source], []),
                      ([catalog.source], [(*catalog.rows[0][:-1], True)])):
            conn, _ = connection([IDENTITY, (True,), (0,), (0,)], lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, catalog)
            conn.commit.assert_not_called()

    def test_dry_run_never_connects_and_does_not_modify_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'snapshot.json'
            original = raw_capture()
            source.write_bytes(original)
            with patch('services.operational_postgres.connect_collector') as connect, redirect_stdout(StringIO()) as out:
                self.assertEqual(module.main(['--source', str(source)]), 0)
                connect.assert_not_called()
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(json.loads(out.getvalue())['postgresql_acessado'])
            self.assertNotIn('PRIVATE', out.getvalue())

    def test_guards_and_changed_capture_prevent_connection(self):
        for computer, digest in (('OTHER', build().digest), ('RIGEL', 'bad')):
            with patch.object(Path, 'read_bytes', return_value=raw_capture()), \
                    patch.dict(os.environ, {'COMPUTERNAME': computer}), \
                    patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', digest]), 1)
                connect.assert_not_called()
        with patch.object(Path, 'read_bytes', side_effect=[raw_capture(), b'{}']), \
                patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
            self.assertEqual(module.main(['--source', 'unused', '--apply']), 1)
            connect.assert_not_called()

    def test_success_after_transaction_exit_only_and_errors_redacted(self):
        for failed in (False, True):
            with patch.object(Path, 'read_bytes', return_value=raw_capture()), \
                    patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                    patch('services.operational_postgres.connect_collector') as connect, \
                    patch.object(module, 'write_catalog') as write, \
                    redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
                if failed:
                    connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                result = module.main(['--source', 'unused', '--apply', '--expected-digest', build().digest])
                self.assertEqual(result, int(failed))
                write.assert_called_once()
                connect.assert_called_once_with(read_only=False)
            if failed:
                self.assertEqual(out.getvalue(), '')
                self.assertNotIn('SECRET_PRIVATE', err.getvalue())
            else:
                self.assertEqual(json.loads(out.getvalue())['modo'], 'carga_inicial_firmware_confirmada')
                self.assertTrue(json.loads(out.getvalue())['postgresql_acessado'])

    def test_check_database_connects_read_only_without_write(self):
        with patch.object(Path, 'read_bytes', return_value=raw_capture()), \
                patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                patch('services.operational_postgres.connect_collector') as connect, \
                patch.object(module, 'inspect_catalog', return_value={'conteudo_confere_com_captura': False}), \
                patch.object(module, 'write_catalog') as write, redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main(['--source', 'unused', '--check-database']), 0)
            write.assert_not_called()
            connect.assert_called_once_with(read_only=True)
        self.assertEqual(json.loads(out.getvalue())['modo'], 'conferencia_somente_leitura')

    def test_schema_restricts_reader_and_confirmation_without_job_or_device_fk(self):
        sql = (module.ROOT / 'scripts/database/sql/023_switch_firmware_catalog.sql').read_text()
        self.assertIn('CREATE ROLE sentinel_firmware_reader NOLOGIN', sql)
        self.assertIn('CHECK (NOT vinculo_confirmado)', sql)
        self.assertIn('TO sentinel_firmware_reader', sql)
        for forbidden in ('TO sentinel_api', 'TO sentinel_reader', 'GRANT UPDATE', 'GRANT DELETE',
                          'REFERENCES operacional.switches', 'REFERENCES operacional.regionais', 'password'):
            self.assertNotIn(forbidden, sql)
        self.assertIn('E:/Sentinel/PostgreSQL/data', sql)


if __name__ == '__main__':
    unittest.main()
