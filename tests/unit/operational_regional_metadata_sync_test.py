from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from io import StringIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.database import sync_regional_metadata_catalog as module
from scripts.database.import_regional_metadata_catalog import capture_payload
from tests.unit.operational_certificate_catalog_test import connection, IDENTITY
from tests.unit.operational_regional_metadata_sources_audit_test import payload


def catalog(*, captured='2026-11-19T13:00:00+00:00', publication='2026-11-19T09:00:00', entry=None, original=None):
    data = original or payload(**(entry or {}))
    data['configuracao']['ultima_atualizacao'] = publication
    frozen = capture_payload(json.dumps(data).encode(), datetime.fromisoformat(captured))
    return module.build_catalog(json.dumps(frozen).encode())


def rows(snap, present=True):
    return [(*row, present) for row in snap.rows]


def parents(snap):
    return [(row[0], row[1], True) for row in snap.rows]


class RegionalMetadataSyncTests(unittest.TestCase):
    def test_inspect_initial_is_readonly_and_does_not_publish_marker(self):
        snap = catalog()
        conn, cur = connection([IDENTITY, snap.source, None], [rows(snap), parents(snap)])
        report = module.inspect_catalog(conn, snap)
        self.assertTrue(report['conteudo_atual_confere'])
        self.assertFalse(report['conteudo_ja_sincronizado'])
        self.assertIsNone(report['ultima_captura_sincronizada'])
        self.assertFalse(report['fuso_declarado_incompativel'])
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'DELETE')) for call in cur.execute.call_args_list))
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_first_sync_and_newer_identical_capture_update_only_marker(self):
        initial = catalog()
        newer = catalog(captured='2026-11-19T14:00:00+00:00', publication='2026-11-19T10:00:00')
        for snap, previous in ((initial, None), (newer, module._marker(initial))):
            conn, cur = connection([IDENTITY, (True,), initial.source, previous, initial.source, module._marker(snap)],
                                   [rows(initial), parents(initial), rows(snap), parents(snap)])
            self.assertEqual(module.write_catalog(conn, snap), 'sincronizado')
            statements = [call.args[0] for call in cur.execute.call_args_list]
            self.assertFalse(any(sql.startswith(('UPDATE operacional.metadados_', 'INSERT INTO operacional.metadados_')) for sql in statements))
            self.assertTrue(any('INSERT INTO operacional.sincronizacoes_' in sql for sql in statements))
            self.assertFalse(any('PRIVATE' in sql for sql in statements))
            conn.commit.assert_not_called()

    def test_repeated_snapshot_is_noop_only_when_all_content_matches(self):
        snap = catalog()
        conn, cur = connection([IDENTITY, (True,), snap.source, module._marker(snap)], [rows(snap), parents(snap)])
        self.assertEqual(module.write_catalog(conn, snap), 'ja_sincronizado')
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cur.execute.call_args_list))
        bad = [(*snap.rows[0][:2], 'WRONG_PRIVATE', *snap.rows[0][3:], True)]
        report = module._report((snap.source, module._marker(snap), bad,
                                 {row[0]: row[1:] for row in parents(snap)}), snap)
        self.assertFalse(report['conteudo_ja_sincronizado'])

    def test_new_metadata_upsert_preserves_initial_source_and_parent_catalog(self):
        initial = catalog()
        newer = catalog(captured='2026-11-19T14:00:00+00:00', publication='2026-11-19T10:00:00',
                        entry={'descricao': 'NEW_PRIVATE', 'estado': 'RJ', 'uf': 'RJ'})
        conn, cur = connection([IDENTITY, (True,), initial.source, None, initial.source, module._marker(newer)],
                               [rows(initial), parents(initial), rows(newer), parents(newer)])
        self.assertEqual(module.write_catalog(conn, newer), 'sincronizado')
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('ON CONFLICT (codigo_regional)' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('UPDATE operacional.regionais', 'UPDATE operacional.fontes_', 'DELETE', 'TRUNCATE')) for sql in statements))
        insert = next(call for call in cur.execute.call_args_list if call.args[0].startswith('INSERT INTO operacional.metadados_'))
        self.assertEqual(insert.args[1], (module.SOURCE, *newer.rows[0]))

    def test_removed_metadata_preserved_as_absent_without_deleting_parent(self):
        data = payload()
        data['regionais']['REG_SECOND'] = {**data['regionais']['REG_PRIVATE'], 'nome': 'SECOND_PRIVATE'}
        initial = catalog(original=data)
        incoming = catalog(captured='2026-11-19T14:00:00+00:00', publication='2026-11-19T10:00:00')
        final = rows(incoming) + [(*initial.rows[1], False)]
        conn, _ = connection([IDENTITY, (True,), initial.source, None, initial.source, module._marker(incoming)],
                              [rows(initial), parents(initial), final, parents(initial)])
        self.assertEqual(module.write_catalog(conn, incoming), 'sincronizado')

    def test_new_regional_metadata_requires_existing_matching_parent(self):
        snap = catalog()
        for parent in ([], [('REG_PRIVATE', 'OTHER_PRIVATE', True)], [('REG_PRIVATE', 'NAME_PRIVATE', False)]):
            conn, cur = connection([IDENTITY, (True,), snap.source, None], [rows(snap), parent])
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, snap)
            self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cur.execute.call_args_list))

    def test_older_capture_or_conflicting_same_capture_blocks(self):
        snap = catalog()
        newer = catalog(captured='2026-11-19T14:00:00+00:00')
        for marker in (module._marker(newer), (*module._marker(snap)[:4], 'a' * 64, 1)):
            conn, cur = connection([IDENTITY, (True,), snap.source, marker], [rows(snap), parents(snap)])
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, snap)
            self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cur.execute.call_args_list))

    def test_new_capture_cannot_restore_old_publication_or_change_same_publication_metadata(self):
        initial = catalog()
        incoming_values = [catalog(captured='2026-11-19T14:00:00+00:00', publication='2026-11-19T08:00:00'),
                           catalog(captured='2026-11-19T14:00:00+00:00', entry={'descricao': 'OTHER_PRIVATE'}),
                           catalog(captured='2026-11-19T14:00:00+00:00', publication='2026-11-19T10:00:00-03:00')]
        for incoming in incoming_values:
            conn, cur = connection([IDENTITY, (True,), initial.source, None], [rows(initial), parents(initial)])
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, incoming)
            self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE')) for call in cur.execute.call_args_list))

    def test_aware_times_compare_instants_without_inferring_zone_for_naive(self):
        result = module._publication_flags('2026-11-19T09:00:00-03:00', '2026-11-19T12:00:00Z', 'a', 'b')
        self.assertTrue(result['conflito_mesma_publicacao'])
        self.assertFalse(result['publicacao_mais_antiga'])
        self.assertTrue(module._publication_flags('2026-11-19T09:00:00', '2026-11-19T12:00:00Z', 'a', 'a')['fuso_declarado_incompativel'])

    def test_missing_initial_empty_or_drifted_initial_state_blocks(self):
        snap = catalog()
        for ones, lists in (([IDENTITY, None], []), ([IDENTITY, snap.source, None], [[]]),
                            ([IDENTITY, snap.source, None], [rows(snap, False)])):
            conn, _ = connection(ones, lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.inspect_catalog(conn, snap)

    def test_wrong_identity_busy_lock_or_final_readback_mismatch_blocks(self):
        snap = catalog()
        for ones, lists in (([('other', 'other', 5432)], []), ([IDENTITY, (False,)], []),
                            ([IDENTITY, (True,), snap.source, None, snap.source, module._marker(snap)],
                             [rows(snap), parents(snap), rows(snap, False), parents(snap)])):
            conn, _ = connection(ones, lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, snap)
            conn.commit.assert_not_called()

    def test_cli_default_readonly_apply_guard_and_commit_error_redacted(self):
        snap = catalog()
        for apply, failed in ((False, False), (True, False), (True, True)):
            with patch.object(Path, 'read_bytes', return_value=b'raw'), patch.object(module, 'build_catalog', return_value=snap), \
                    patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                    patch('services.operational_postgres.connect_collector') as connect, \
                    patch.object(module, 'inspect_catalog', return_value={}) as inspect, \
                    patch.object(module, 'write_catalog', return_value='sincronizado') as write, \
                    redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
                if failed:
                    connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                flags = ['--apply', '--expected-digest', snap.digest] if apply else []
                self.assertEqual(module.main(['--source', 'unused', *flags]), int(failed))
                connect.assert_called_once_with(read_only=not apply)
                self.assertEqual(write.called, apply)
                self.assertEqual(inspect.called, not apply)
            self.assertNotIn('PRIVATE', out.getvalue() + err.getvalue())
            if failed:
                self.assertEqual(out.getvalue(), '')

    def test_cli_wrong_host_digest_or_changing_file_never_connects(self):
        snap = catalog()
        for machine, digest, content in (('OTHER', snap.digest, [b'raw', b'raw']),
                                         ('RIGEL', 'bad', [b'raw', b'raw']),
                                         ('RIGEL', snap.digest, [b'raw', b'changed'])):
            with patch.object(Path, 'read_bytes', side_effect=content), patch.object(module, 'build_catalog', return_value=snap), \
                    patch.dict(os.environ, {'COMPUTERNAME': machine}), \
                    patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', digest]), 1)
                connect.assert_not_called()

    def test_schema_soft_presence_restricted_reader_and_no_parent_changes(self):
        sql = (module.ROOT / 'scripts/database/sql/026_regional_metadata_sync.sql').read_text()
        self.assertIn('presente_na_captura boolean NOT NULL DEFAULT true', sql)
        self.assertIn('TO sentinel_regionais_metadados_reader', sql)
        for forbidden in ('TO sentinel_reader', 'TO sentinel_api', 'GRANT DELETE',
                          'ALTER TABLE operacional.regionais', 'UPDATE operacional.regionais'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
