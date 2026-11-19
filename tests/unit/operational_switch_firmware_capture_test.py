from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import capture_switch_firmware_catalog as module
from tests.unit.operational_switch_firmware_sources_audit_test import firmware, cache_record, create_database

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
CACHE = json.dumps({'NAME_PRIVATE': cache_record(password='SECRET_PRIVATE')}).encode()


def capture(rows=None, cache=CACHE):
    with patch.object(Path, 'read_bytes', return_value=cache), \
            patch.object(module, 'read_inventory', return_value=([firmware()] if rows is None else rows, {})):
        return module.capture(Path('unused.sqlite3'), Path('unused.json'), now=NOW)


class FirmwareCaptureTests(unittest.TestCase):
    def test_projection_preserves_metadata_but_never_binds_device(self):
        payload = capture()
        self.assertEqual(payload['registros'][0], {**firmware(),
                         'diagnostico_vinculo': 'ip_e_nome_concordantes_candidato'})
        self.assertNotIn('SECRET_PRIVATE', json.dumps(payload))
        self.assertNotIn('hostid', json.dumps(payload))
        self.assertFalse(module.summary(payload)['vinculos_aprovados_automaticamente'])
        self.assertNotIn('PRIVATE', json.dumps(module.summary(payload)))

    def test_unresolved_records_are_preserved_without_renaming(self):
        cache = {'NAME_PRIVATE': cache_record(), 'OTHER_PRIVATE': cache_record(hostid='2'),
                 'CONFLICT': cache_record(hostid='3', ip='192.0.2.4'),
                 'IP_TARGET': cache_record(hostid='4', ip='192.0.2.3')}
        rows = [firmware(), firmware(host='192.0.2.3', ip_address='192.0.2.3', switch_name='CONFLICT'),
                firmware(host='192.0.2.9', ip_address='192.0.2.9', switch_name='MISSING')]
        payload = capture(rows, json.dumps(cache).encode())
        self.assertEqual([row['switch_name'] for row in payload['registros']], ['NAME_PRIVATE', 'CONFLICT', 'MISSING'])
        self.assertEqual(set(module.summary(payload)['por_diagnostico_vinculo']),
                         {'ambiguo_nao_aprovado', 'ip_e_nome_apontam_identidades_diferentes', 'sem_correspondencia'})

    def test_empty_invalid_extra_fields_and_duplicate_hosts_block(self):
        for rows in ([], [None], [firmware(password='SECRET_PRIVATE')], [firmware(), firmware()],
                     [firmware(model=12)], [firmware(host='X' * 256)], [firmware(ip_address='invalid')],
                     [firmware(source='SECRET_PRIVATE')], [firmware(current_version='')]):
            with self.assertRaises(module.ImportErrorSafe) as error:
                capture(rows)
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_dates_require_timezone_and_preserve_text(self):
        value = '2026-11-18T13:00:00-03:00'
        self.assertEqual(capture([firmware(checked_at_utc=value)])['registros'][0]['checked_at_utc'], value)
        for value in ('2026-11-18T13:00:00', '2026-11-18', 'PRIVATE', None):
            with self.assertRaises(module.ImportErrorSafe):
                capture([firmware(checked_at_utc=value)])

    def test_digest_covers_metadata_diagnosis_and_time(self):
        original = capture()
        self.assertEqual(original, capture())
        changed = capture([firmware(current_version='OTHER_PRIVATE')])
        self.assertNotEqual(original['digest_carga'], changed['digest_carga'])
        for key, value in (('capturado_em', '2026-11-19T13:00:00Z'), ('sha256_cache_status', 'a' * 64)):
            payload = deepcopy(original)
            payload[key] = value
            with self.assertRaises(module.ImportErrorSafe):
                module.validate(payload)
        payload = deepcopy(original)
        payload['registros'][0]['diagnostico_vinculo'] = 'sem_correspondencia'
        with self.assertRaises(module.ImportErrorSafe):
            module.validate(payload)

    def test_snapshot_schema_and_inventory_hash_validated_independently(self):
        for mutate in (lambda p: p.update(password='SECRET_PRIVATE'),
                       lambda p: p.update(version=True),
                       lambda p: p['registros'][0].update(diagnostico_vinculo='PRIVATE'),
                       lambda p: p['registros'][0].update(model='CHANGED_PRIVATE'),
                       lambda p: p.update(sha256_cache_status='bad')):
            payload = deepcopy(capture())
            mutate(payload)
            payload['digest_carga'] = module._hash({k: v for k, v in payload.items() if k != 'digest_carga'})
            with self.assertRaises(module.ImportErrorSafe):
                module.validate(payload)

    def test_unavailable_sqlite_invalid_or_changing_cache_blocks(self):
        with patch.object(Path, 'read_bytes', return_value=CACHE), \
                patch.object(module, 'read_inventory', return_value=(None, {})):
            with self.assertRaises(module.ImportErrorSafe):
                module.capture(Path('unused'), Path('unused'))
        for cache in (b'{}', b'null', b'{"x":null}', b'{"x":{},"x":{}}'):
            with self.assertRaises(module.ImportErrorSafe):
                capture(cache=cache)
        with patch.object(Path, 'read_bytes', side_effect=[CACHE, b'{}']), \
                patch.object(module, 'read_inventory', return_value=([firmware()], {})):
            with self.assertRaises(module.ImportErrorSafe):
                module.capture(Path('unused'), Path('unused'))

    def test_freeze_replay_and_no_overwrite_or_raw_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database, cache, output = root / 'data.sqlite3', root / 'cache.json', root / 'capture.json'
            create_database(database)
            cache.write_bytes(CACHE)
            before = database.read_bytes()
            args = ['--database', str(database), '--cache', str(cache), '--output', str(output)]
            with redirect_stdout(StringIO()) as out:
                self.assertEqual(module.main(args), 0)
            self.assertNotIn('PRIVATE', out.getvalue())
            self.assertEqual(database.read_bytes(), before)
            raw = output.read_bytes()
            self.assertNotIn(b'SECRET_PRIVATE', raw)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(module.main(args), 1)
            self.assertEqual(output.read_bytes(), raw)
            with patch.object(module, 'read_inventory') as read, redirect_stdout(StringIO()) as out:
                self.assertEqual(module.main(['--source', str(output)]), 0)
                read.assert_not_called()
            self.assertEqual(json.loads(out.getvalue())['digest_carga'], module.validate(json.loads(raw))['digest_carga'])

    def test_dry_run_has_no_output_file_and_failures_have_no_raw_exception(self):
        with patch.object(module, 'capture', return_value=capture()), \
                patch.object(Path, 'open') as write, redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main([]), 0)
            write.assert_not_called()
            self.assertEqual(json.loads(out.getvalue())['modo'], 'simulacao_sem_conexao_ao_banco')
        with patch.object(module, 'capture', side_effect=RuntimeError('SECRET_PRIVATE')), \
                redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
            self.assertEqual(module.main([]), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('PRIVATE', err.getvalue())


if __name__ == '__main__':
    unittest.main()
