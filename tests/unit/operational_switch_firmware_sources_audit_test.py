import ast
from contextlib import closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import audit_switch_firmware_sources as module


def firmware(**changes):
    return {'host': '192.0.2.1', 'switch_name': 'NAME_PRIVATE', 'regional': 'REG_PRIVATE',
            'ip_address': '192.0.2.1', 'model': 'MODEL_PRIVATE', 'current_version': 'VERSION_PRIVATE',
            'checked_at_utc': '2026-11-18T16:00:00Z', 'source': 'webui', **changes}


def cache_record(**changes):
    return {'hostid': '123', 'ip': '192.0.2.1', **changes}


def create_database(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('CREATE TABLE switch_firmware_inventory (' + ','.join(key + ' TEXT' for key in module.COLUMNS) + ')')
        connection.execute('CREATE TABLE scheduled_updates (password TEXT)')
        connection.execute("INSERT INTO scheduled_updates VALUES ('SECRET_PRIVATE')")
        connection.execute('INSERT INTO switch_firmware_inventory VALUES (?,?,?,?,?,?,?,?)', tuple(firmware().values()))


class FirmwareSourceAuditTests(unittest.TestCase):
    def test_safe_summary_never_exports_identity_model_version_source_or_secret(self):
        report = module.audit_inventory([firmware(source='SOURCE_PRIVATE')])
        encoded = json.dumps(report)
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn('192.0.2.1', encoded)
        self.assertEqual(report['por_origem_declarada'], {'ausente_ou_outro': 1})

    def test_duplicate_names_addresses_and_missing_dates_are_diagnostics_not_merge(self):
        report = module.audit_inventory([firmware(), firmware(host='192.0.2.2', checked_at_utc=None)])
        self.assertEqual(report['registros'], 2)
        self.assertEqual(report['nomes_repetidos_sem_fusao'], 1)
        self.assertEqual(report['ips_repetidos_sem_fusao'], 1)
        self.assertEqual(report['host_ip_e_ip_address_divergentes'], 1)
        self.assertEqual(report['horarios_consulta_firmware'], {'com_fuso': 1, 'ausente': 1})

    def test_naive_dates_and_nontext_fields_not_coerced(self):
        report = module.audit_inventory([firmware(checked_at_utc='2026-11-18T10:00:00', model=1)])
        self.assertEqual(report['campos_nao_textuais'], 1)
        self.assertEqual(report['horarios_consulta_firmware'], {'sem_fuso': 1})

    def test_ip_and_name_agreement_is_only_candidate(self):
        result = module.compare_with_cache([firmware()], {'NAME_PRIVATE': cache_record()})
        self.assertEqual(result['candidatos_sem_aprovacao'], {'ip_e_nome_concordantes_candidato': 1})
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_shared_ip_never_chooses_first_even_when_name_matches(self):
        cache = {'NAME_PRIVATE': cache_record(), 'OTHER_PRIVATE': cache_record(hostid='456')}
        self.assertEqual(module.compare_with_cache([firmware()], cache)['candidatos_sem_aprovacao'],
                         {'ambiguo_nao_aprovado': 1})

    def test_conflicting_host_ip_or_name_identity_blocks_candidate(self):
        first = module.compare_with_cache([firmware(host='192.0.2.2')], {'NAME_PRIVATE': cache_record()})
        self.assertEqual(first['candidatos_sem_aprovacao'], {'enderecos_da_fonte_conflitantes': 1})
        cache = {'NAME_PRIVATE': cache_record(ip='192.0.2.2'), 'OTHER_PRIVATE': cache_record(hostid='456')}
        self.assertEqual(module.compare_with_cache([firmware()], cache)['candidatos_sem_aprovacao'],
                         {'ip_e_nome_apontam_identidades_diferentes': 1})

    def test_missing_ids_ip_only_and_missing_matches_not_approved(self):
        for cache, expected in (({'NAME_PRIVATE': cache_record(hostid=None)}, 'candidato_sem_identidade_valida'),
                                ({'OTHER_PRIVATE': cache_record()}, 'apenas_ip_candidato_nao_aprovado'),
                                ({}, 'sem_correspondencia')):
            self.assertEqual(module.compare_with_cache([firmware()], cache)['candidatos_sem_aprovacao'], {expected: 1})

    def test_database_missing_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'missing.sqlite3'
            rows, info = module.read_inventory(path)
            self.assertIsNone(rows)
            self.assertEqual(info['situacao'], 'arquivo_ausente')
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_unresolved_lists_only_pending_with_whitelisted_candidates(self):
        rows = [firmware(switch_name='GOOD', host='192.0.2.9', ip_address='192.0.2.9'),
                firmware(switch_name='SHARED'),
                firmware(switch_name='CONFLICT', host='192.0.2.3', ip_address='192.0.2.3'),
                firmware(switch_name='MISSING', host='192.0.2.8', ip_address='192.0.2.8')]
        cache = {'GOOD': cache_record(hostid='9', ip='192.0.2.9'),
                 'SHARED': cache_record(password='SECRET_PRIVATE', model='MODEL_PRIVATE'),
                 'OTHER': cache_record(hostid='2', status_details='ERROR_PRIVATE'),
                 'CONFLICT': cache_record(hostid='3', ip='192.0.2.4'),
                 'IP_TARGET': cache_record(hostid='4', ip='192.0.2.3')}
        report = module.compare_with_cache(rows, cache, unresolved=True)
        pending = report['pendencias_identidade']
        self.assertEqual([item['switch_name'] for item in pending], ['SHARED', 'CONFLICT', 'MISSING'])
        self.assertEqual(len(pending[0]['candidatos_por_ip']), 2)
        self.assertEqual(pending[0]['motivo'], 'ambiguo_nao_aprovado')
        self.assertEqual(pending[1]['motivo'], 'ip_e_nome_apontam_identidades_diferentes')
        self.assertEqual(pending[1]['candidatos_por_ip'][0]['id_origem'], '4')
        self.assertEqual(pending[1]['candidatos_por_nome'][0]['id_origem'], '3')
        self.assertEqual(pending[2]['candidatos_por_ip'], [])
        self.assertEqual(pending[2]['candidatos_por_nome'], [])
        for forbidden in ('MODEL_PRIVATE', 'VERSION_PRIVATE', 'SECRET_PRIVATE', 'ERROR_PRIVATE'):
            self.assertNotIn(forbidden, json.dumps(report))
        self.assertNotIn('pendencias_identidade', module.compare_with_cache(rows, cache))

    def test_unresolved_source_conflict_and_invalid_candidate_are_not_approved(self):
        report = module.compare_with_cache([firmware(host='192.0.2.2'), firmware()],
                                           {'NAME_PRIVATE': cache_record(hostid=None)}, unresolved=True)
        pending = report['pendencias_identidade']
        self.assertEqual(pending[0]['motivo'], 'enderecos_da_fonte_conflitantes')
        self.assertEqual(pending[1]['motivo'], 'candidato_sem_identidade_valida')
        self.assertIsNone(pending[1]['candidatos_por_nome'][0]['id_origem'])

    def test_unresolved_cli_forwards_explicit_flag(self):
        with patch.object(module, 'audit_sources', return_value={}) as audit, redirect_stdout(StringIO()):
            self.assertEqual(module.main(['--unresolved']), 0)
        audit.assert_called_once_with(database=None, unresolved=True)

    def test_unresolved_full_report_remains_read_only_and_limits_labels(self):
        with patch.object(module, 'read_inventory', return_value=([firmware(switch_name='X' * 300)], {})), \
                patch.object(module, '_read_source', return_value=({}, {'situacao': 'lido'})):
            report = module.audit_sources(unresolved=True)
        self.assertTrue(report['diagnostico_de_identidades_solicitado'])
        self.assertFalse(report['modelos_versoes_erros_e_credenciais_exportados'])
        self.assertFalse(report['escrita_sql_habilitada'])
        self.assertEqual(len(report['comparacao_com_cache']['pendencias_identidade'][0]['switch_name']), 255)

    def test_read_only_mode_preserves_data_and_never_selects_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data with spaces.sqlite3'
            create_database(path)
            original = path.read_bytes()
            rows, info = module.read_inventory(path)
            self.assertEqual(info['situacao'], 'lido_somente_leitura')
            self.assertEqual(rows, [firmware()])
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn('SECRET_PRIVATE', str(rows))

    def test_authorizer_denies_jobs_mutations_and_functions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.sqlite3'
            create_database(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.set_authorizer(module._authorize)
                for sql in ('SELECT password FROM scheduled_updates', 'DELETE FROM switch_firmware_inventory',
                            'CREATE TABLE danger (value)', 'SELECT load_extension(1)'):
                    with self.assertRaises(sqlite3.DatabaseError):
                        connection.execute(sql)
                self.assertEqual(len(connection.execute('SELECT host FROM switch_firmware_inventory').fetchall()), 1)

    def test_active_wal_committed_inventory_is_read_not_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.sqlite3'
            create_database(path)
            with closing(sqlite3.connect(path)) as writer, writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('UPDATE switch_firmware_inventory SET current_version=?', ('NEW_PRIVATE',))
                writer.commit()
                self.assertTrue(Path(str(path) + '-wal').exists())
                rows, info = module.read_inventory(path)
                self.assertEqual(info['situacao'], 'lido_somente_leitura')
                self.assertEqual(rows[0]['current_version'], 'NEW_PRIVATE')

    def test_missing_table_view_and_invalid_sqlite_fail_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.sqlite3'
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('CREATE TABLE jobs (secret TEXT)')
            self.assertEqual(module.read_inventory(path)[1]['situacao'], 'tabela_inventario_ausente')
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('CREATE VIEW switch_firmware_inventory AS SELECT secret FROM jobs')
            self.assertEqual(module.read_inventory(path)[1]['situacao'], 'objeto_inventario_nao_e_tabela')
            path.write_bytes(b'NOT_A_DATABASE_PRIVATE')
            info = module.read_inventory(path)[1]
            self.assertEqual(info['situacao'], 'leitura_sqlite_ou_schema_indisponivel')
            self.assertNotIn('PRIVATE', json.dumps(info))

    def test_full_report_and_cli_have_no_raw_data_or_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / 'data.sqlite3'
            create_database(database)
            (root / 'output').mkdir()
            (root / 'output/switches_status_cache.json').write_text(json.dumps({'NAME_PRIVATE': cache_record()}))
            report = module.audit_sources(root, database)
            self.assertTrue(report['comparacao_com_cache']['comparavel'])
            self.assertFalse(report['tabelas_de_jobs_consultadas'])
            self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertNotIn(str(root), json.dumps(report))
        with patch.object(module, 'audit_sources', return_value={'modo': 'audit'}), redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main([]), 0)
        self.assertEqual(json.loads(out.getvalue()), {'modo': 'audit'})

    def test_no_scheduler_postgres_runtime_or_network_imports(self):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'psycopg', 'subprocess', 'requests',
                                    'services.switch_update_v01.scheduler', 'core.secret_store'})


if __name__ == '__main__':
    unittest.main()
