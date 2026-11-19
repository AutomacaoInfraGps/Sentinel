from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.database import sync_switch_firmware_catalog as module
from tests.unit.operational_certificate_catalog_test import connection, IDENTITY
from tests.unit.operational_switch_firmware_capture_test import capture
from tests.unit.operational_switch_firmware_sources_audit_test import firmware


def catalog(*, when='2026-11-19T12:00:00Z', rows=None):
    payload = capture(rows)
    payload['capturado_em'] = when
    payload['digest_carga'] = module._hash({key: value for key, value in payload.items() if key != 'digest_carga'})
    return module.build_catalog(json.dumps(payload).encode())


def stored(snap, present=True):
    return [(*row, present) for row in snap.rows]


class FirmwareSyncTests(unittest.TestCase):
    def test_initial_state_retained_and_first_sync_not_yet_marked(self):
        snap = catalog()
        conn, cur = connection([IDENTITY, snap.source, None], [stored(snap)])
        report = module.inspect_catalog(conn, snap)
        self.assertFalse(report['conteudo_ja_sincronizado'])
        self.assertFalse(report['captura_mais_antiga'])
        self.assertIsNone(report['ultima_captura_sincronizada'])
        self.assertTrue(any('READ ONLY' in call.args[0] for call in cur.execute.call_args_list))
        self.assertFalse(any(call.args[0].startswith(('INSERT', 'UPDATE', 'DELETE')) for call in cur.execute.call_args_list))

    def test_first_sync_atomic_full_readback_preserves_original_source(self):
        snap = catalog()
        conn, cur = connection([IDENTITY, (True,), snap.source, None, snap.source, module._marker(snap)],
                               [stored(snap), stored(snap)])
        self.assertEqual(module.write_catalog(conn, snap), 'sincronizado')
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('DELETE', 'TRUNCATE', 'UPDATE operacional.fontes_')) for sql in statements))
        self.assertTrue(any('ON CONFLICT (fonte_id,host_origem)' in sql for sql in statements))
        conn.commit.assert_not_called()

    def test_exact_repeat_is_noop_only_after_full_content_comparison(self):
        snap = catalog()
        conn, cur = connection([IDENTITY, (True,), snap.source, module._marker(snap)], [stored(snap)])
        self.assertEqual(module.write_catalog(conn, snap), 'ja_sincronizado')
        self.assertFalse(any(call.args[0].startswith(('UPDATE', 'INSERT')) for call in cur.execute.call_args_list))
        drift = stored(snap)
        drift[0] = (*drift[0][:6], 'DIFFERENT_PRIVATE', *drift[0][7:])
        self.assertFalse(module._report((snap.source, module._marker(snap), drift), snap)['conteudo_ja_sincronizado'])

    def test_older_capture_or_same_time_different_digest_block(self):
        old = catalog()
        newer = catalog(when='2026-11-19T13:00:00Z')
        for marker in (module._marker(newer), (old.source[2], 'a' * 64, *module._marker(old)[2:])):
            conn, cur = connection([IDENTITY, (True,), old.source, marker], [stored(old)])
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, old)
            self.assertFalse(any(call.args[0].startswith(('UPDATE', 'INSERT')) for call in cur.execute.call_args_list))

    def test_new_export_cannot_roll_back_observation_or_rewrite_same_observation(self):
        initial = catalog()
        for row in (firmware(checked_at_utc='2026-11-17T16:00:00Z'), firmware(current_version='CHANGED_PRIVATE')):
            incoming = catalog(when='2026-11-19T13:00:00Z', rows=[row])
            conn, cur = connection([IDENTITY, (True,), initial.source, None], [stored(initial)])
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, incoming)
            self.assertFalse(any(call.args[0].startswith(('UPDATE', 'INSERT')) for call in cur.execute.call_args_list))

    def test_newer_observation_updates_metadata_without_binding(self):
        initial = catalog()
        incoming = catalog(when='2026-11-19T13:00:00Z', rows=[firmware(
            checked_at_utc='2026-11-19T12:30:00Z', current_version='NEW_PRIVATE')])
        conn, cur = connection([IDENTITY, (True,), initial.source, None, initial.source, module._marker(incoming)],
                               [stored(initial), stored(incoming)])
        self.assertEqual(module.write_catalog(conn, incoming), 'sincronizado')
        insert = next(call for call in cur.execute.call_args_list
                      if call.args[0].startswith('INSERT INTO operacional.inventario_'))
        self.assertFalse(insert.args[1][-1])
        self.assertEqual(insert.args[1][7], 'NEW_PRIVATE')

    def test_removed_records_retained_as_absent_new_hosts_can_reuse_order(self):
        initial = catalog()
        incoming = catalog(when='2026-11-19T13:00:00Z', rows=[firmware(host='192.0.2.2', ip_address='192.0.2.2')])
        final = stored(initial, False) + stored(incoming)
        conn, cur = connection([IDENTITY, (True,), initial.source, None, initial.source, module._marker(incoming)],
                               [stored(initial), final])
        self.assertEqual(module.write_catalog(conn, incoming), 'sincronizado')
        report = module._report((initial.source, module._marker(incoming), final), incoming)
        self.assertEqual(report['banco_registros_preservados'], 2)
        self.assertEqual(report['banco_registros_presentes'], 1)
        self.assertTrue(report['conteudo_ja_sincronizado'])
        self.assertTrue(any('presente_na_captura=false' in call.args[0] for call in cur.execute.call_args_list))

    def test_missing_initial_or_corrupt_initial_data_blocks(self):
        snap = catalog()
        for ones, lists in (([IDENTITY, None], []), ([IDENTITY, snap.source, None], [[]]),
                            ([IDENTITY, snap.source, None], [stored(snap, False)])):
            conn, _ = connection(ones, lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.inspect_catalog(conn, snap)

    def test_busy_lock_or_wrong_identity_blocks_before_mutations(self):
        for ones in ([('other', 'other', 5432)], [IDENTITY, (False,)]):
            conn, cur = connection(ones)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_catalog(conn, catalog())
            self.assertFalse(any(call.args[0].startswith(('UPDATE', 'INSERT')) for call in cur.execute.call_args_list))

    def test_final_readback_mismatch_cancels(self):
        snap = catalog()
        conn, _ = connection([IDENTITY, (True,), snap.source, None, snap.source, module._marker(snap)],
                             [stored(snap), stored(snap, False)])
        with self.assertRaises(module.ImportErrorSafe):
            module.write_catalog(conn, snap)
        conn.commit.assert_not_called()

    def test_cli_default_read_only_and_apply_after_commit_only(self):
        for apply, failed in ((False, False), (True, False), (True, True)):
            snap = catalog()
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

    def test_cli_wrong_machine_digest_or_changed_file_never_connects(self):
        for computer, digest, contents in (('OTHER', catalog().digest, [b'raw', b'raw']),
                                          ('RIGEL', 'wrong', [b'raw', b'raw']),
                                          ('RIGEL', catalog().digest, [b'raw', b'changed'])):
            with patch.object(Path, 'read_bytes', side_effect=contents), \
                    patch.object(module, 'build_catalog', return_value=catalog()), \
                    patch.dict(os.environ, {'COMPUTERNAME': computer}), \
                    patch('services.operational_postgres.connect_collector') as connect, redirect_stderr(StringIO()):
                self.assertEqual(module.main(['--source', 'unused', '--apply', '--expected-digest', digest]), 1)
                connect.assert_not_called()

    def test_schema_keeps_restricted_readers_soft_presence_and_no_delete_grant(self):
        sql = (module.ROOT / 'scripts/database/sql/024_switch_firmware_sync.sql').read_text()
        self.assertIn('DROP CONSTRAINT inventario_firmware_switches_fonte_id_ordem_key', sql)
        self.assertIn('presente_na_captura boolean NOT NULL DEFAULT true', sql)
        self.assertIn('TO sentinel_firmware_reader', sql)
        for forbidden in ('GRANT DELETE', 'TO sentinel_api', 'TO sentinel_reader'):
            self.assertNotIn(forbidden, sql)


if __name__ == '__main__':
    unittest.main()
