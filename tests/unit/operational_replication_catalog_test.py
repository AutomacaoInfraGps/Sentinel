from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import import_replication_catalog as module


def row(**changes):
    return {'nome': 'DC_PRIVATE.example.test', 'tipo': 'Origem', 'status': 'OK',
            'delta': '10m', 'parceiros': 4, 'falhas': 0, 'erros': 0, 'replicacoes': 4,
            'ultima_replicacao': '2026-11-18T10:43:47', 'detalhes': '', **changes}


def payload(**changes):
    return {'timestamp': '2026-11-18T10:43:47', 'total_servidores': 34,
            'servidores_saudaveis': 32, 'servidores_problemas': 2,
            'servidores': [row(), row(tipo='Destino')],
            'erros_operacionais': ['1722 - ERROR_PRIVATE'], **changes}


def build(value=None, zone='America/Sao_Paulo'):
    return module.build_replication_catalog(json.dumps(payload() if value is None else value).encode(), zone)


def connection(ones, lists=()):
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = ones
    cursor.fetchall.side_effect = lists
    return conn, cursor


IDENTITY = ('sentinel', 'sentinel_collector', 5433)


class ReplicationCatalogTests(unittest.TestCase):
    def test_preserves_sections_declared_totals_and_errors_without_healthy_inference(self):
        snap = build()
        summary = snap.summary()
        self.assertEqual(summary['registros'], 2)
        self.assertEqual(summary['controladores_distintos'], 1)
        self.assertEqual(summary['totais_declarados']['total_servidores'], 34)
        self.assertEqual(summary['erros_operacionais'], 1)
        self.assertTrue(summary['total_declarado_difere_de_linhas'])
        self.assertEqual(snap.errors, ((1, '1722 - ERROR_PRIVATE'),))
        self.assertEqual([record[3] for record in snap.rows], ['Origem', 'Destino'])

    def test_only_full_name_plus_section_is_identity(self):
        self.assertEqual(len(build(payload(servidores=[row(), row(nome='DC_PRIVATE.other.test')])).rows), 2)
        for records in ([row(), row()], [row(), row(nome='dc_private.EXAMPLE.test')]):
            with self.assertRaises(module.ImportErrorSafe):
                build(payload(servidores=records))

    def test_summary_and_repr_do_not_expose_records_unknown_fields_or_errors(self):
        snap = build(payload(password='SECRET_PRIVATE', servidores=[row(username='ACCOUNT_PRIVATE')]))
        self.assertNotIn('PRIVATE', json.dumps(snap.summary()) + repr(snap))
        self.assertNotIn('SECRET_PRIVATE', str(snap.rows))
        self.assertNotIn('ACCOUNT_PRIVATE', str(snap.rows))

    def test_dates_keep_text_and_explicit_timezone_conversion_without_inventing_measurement(self):
        snap = build()
        self.assertEqual(snap.publication.isoformat(), '2026-11-18T13:43:47+00:00')
        self.assertEqual(snap.publication_text, '2026-11-18T10:43:47')
        self.assertEqual(snap.rows[0][10], '2026-11-18T10:43:47')
        self.assertEqual(snap.rows[0][11], snap.publication)
        for key in ('publicacao_nao_comprova_coleta_ad', 'ultima_replicacao_nao_comprova_sucesso'):
            self.assertTrue(snap.summary()[key])
        with self.assertRaises(module.ImportErrorSafe):
            build(zone=None)
        aware = payload(timestamp='2026-11-18T10:43:47-03:00',
                        servidores=[row(ultima_replicacao=None)])
        snap = build(aware, zone=None)
        self.assertIsNone(snap.rows[0][11])
        self.assertEqual(snap.summary()['sem_ultima_replicacao_declarada'], 1)

    def test_invalid_dates_zones_and_dst_gap_block(self):
        for zone in ('PRIVATE_ZONE', '', True):
            with self.assertRaises(module.ImportErrorSafe):
                build(zone=zone)
        for stamp in ('2026-11-18', '08:00:00', 'PRIVATE', '2018-11-04T00:30:00', None):
            with self.assertRaises(module.ImportErrorSafe):
                build(payload(timestamp=stamp))

    def test_only_reviewed_local_envelope_and_explicit_errors_list_accepted(self):
        for value in ({}, {'detalhes': {'controladores': [row()]}}, [],
                      payload(servidores=[]), payload(servidores=[None]),
                      payload(erros_operacionais=None), payload(erros_operacionais=[None])):
            with self.assertRaises(module.ImportErrorSafe):
                build(value)
        self.assertEqual(build(payload(erros_operacionais=[])).errors, ())

    def test_unproven_identity_section_status_or_new_collection_evidence_blocks(self):
        for changes in ({'nome': ''}, {'nome': 'ERRO.GALAXIA.LOCAL'}, {'tipo': 'Problema'},
                        {'tipo': None}, {'status': 'PRIVATE'}, {'coletado_em': '2026-11-18T10:00:00Z'}):
            with self.assertRaises(module.ImportErrorSafe):
                build(payload(servidores=[row(**changes)]))

    def test_invalid_counters_do_not_coerce_and_absent_stays_null(self):
        for value in (True, -1, 2.5, '4', 2147483648):
            with self.assertRaises(module.ImportErrorSafe):
                build(payload(servidores=[row(falhas=value)]))
            with self.assertRaises(module.ImportErrorSafe):
                build(payload(total_servidores=value))
        record = row()
        del record['falhas']
        self.assertIsNone(build(payload(servidores=[record])).rows[0][7])
        # Percentages/declared inconsistencies are retained, not relabeled as real failures.
        self.assertEqual(build(payload(servidores=[row(erros=100, falhas=100)])).rows[0][7:9], (100, 100))

    def test_duplicate_keys_and_malformed_json_block_with_safe_errors(self):
        for raw in (b'{"servidores":[],"servidores":[]}', b'{PRIVATE'):
            with self.assertRaises(module.ImportErrorSafe) as error:
                module.build_replication_catalog(raw)
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_digest_binds_source_bytes_zone_errors_and_projection(self):
        snap = build()
        self.assertNotEqual(snap.digest, build(payload(erros_operacionais=[])).digest)
        self.assertNotEqual(snap.digest, build(payload(servidores=[row(status='Error')])).digest)
        self.assertNotEqual(snap.digest, build(zone='UTC').digest)

    def test_inspection_is_read_only(self):
        conn, cur = connection([IDENTITY, (0,), (0,), (0,)])
        self.assertTrue(module.inspect_replication_catalog(conn)['tabelas_replicacao_ad_vazias'])
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('READ ONLY' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'DELETE')) for sql in statements))

    def test_atomic_parameterized_write_and_exact_readback(self):
        snap = build()
        source = (module.SOURCE_ID, snap.source_sha256, snap.digest, snap.source_timezone,
                  snap.publication_text, snap.publication, dict(snap.totals))
        conn, cur = connection([IDENTITY, (True,), (0,), (0,), (0,)],
                               [[source], list(snap.rows), list(snap.errors)])
        module.write_replication_catalog(conn, snap)
        statements = [call.args[0] for call in cur.execute.call_args_list]
        self.assertFalse(any('PRIVATE' in sql for sql in statements))
        self.assertFalse(any(sql.startswith(('UPDATE', 'DELETE', 'TRUNCATE')) for sql in statements))
        conn.commit.assert_not_called()

    def test_wrong_instance_lock_occupied_tables_and_readback_mismatch_block(self):
        for ones, lists in (([('other', 'other', 5432)], []),
                             ([IDENTITY, (False,)], []),
                             ([IDENTITY, (True,), (1,), (2,), (1,)], []),
                             ([IDENTITY, (True,), (0,), (0,), (0,)], [[]])):
            conn, _ = connection(ones, lists)
            with self.assertRaises(module.ImportErrorSafe):
                module.write_replication_catalog(conn, build())
            conn.commit.assert_not_called()

    def test_dry_run_never_connects_or_changes_source_and_sql_requires_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'replicacao.json'
            original = json.dumps(payload()).encode()
            source.write_bytes(original)
            args = ['--source', str(source), '--source-timezone', 'America/Sao_Paulo']
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

    def test_commit_failure_has_no_success_output_or_raw_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'replicacao.json'
            source.write_text(json.dumps(payload()), encoding='utf-8')
            args = ['--source', str(source), '--source-timezone', 'America/Sao_Paulo',
                    '--apply', '--expected-digest', build().digest]
            with patch.dict(os.environ, {'COMPUTERNAME': 'RIGEL'}), \
                    patch('services.operational_postgres.connect_collector') as connect, \
                    patch.object(module, 'write_replication_catalog'), \
                    redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
                connect.return_value.__exit__.side_effect = RuntimeError('SECRET_PRIVATE')
                self.assertEqual(module.main(args), 1)
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('SECRET_PRIVATE', err.getvalue())

    def test_ddl_has_restricted_reader_and_no_broad_grants_or_mutation_permissions(self):
        sql = (module.ROOT / 'scripts/database/sql/019_replication_catalog.sql').read_text()
        self.assertIn('CREATE ROLE sentinel_replicacao_reader NOLOGIN', sql)
        self.assertIn('TO sentinel_replicacao_reader', sql)
        self.assertIn('TO sentinel_collector', sql)
        self.assertNotIn('TO sentinel_reader', sql)
        self.assertNotIn('TO sentinel_api', sql)
        self.assertNotIn('GRANT UPDATE', sql)
        self.assertNotIn('GRANT DELETE', sql)
        self.assertIn('UNIQUE (fonte_id,nome_identidade,secao)', sql)


if __name__ == '__main__':
    unittest.main()
