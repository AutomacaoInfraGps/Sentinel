import ast
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import audit_switch_sources as module


def switch(**changes):
    return {'hostid': '123', 'ip': '192.0.2.1', 'regional': 'REG_PRIVATE', 'status': 'online',
            'em_manutencao': False, 'is_core': False, 'ultima_verificacao': '2026-11-18T10:00:00',
            'warning_problemas': [], **changes}


class SwitchSourceAuditTests(unittest.TestCase):
    def test_summary_never_exports_identity_diagnostics_firmware_or_secret(self):
        report = module.audit_records([('NAME_PRIVATE', switch(status='STATUS_PRIVATE',
            status_reason='REASON_PRIVATE', status_details='DETAIL_PRIVATE', firmware_version='VERSION_PRIVATE',
            warning_problemas=['WARNING_PRIVATE'], password='SECRET_PRIVATE'))])
        encoded = json.dumps(report)
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn('192.0.2.1', encoded)
        self.assertEqual(report['por_status_declarado'], {'ausente_ou_outro': 1})
        self.assertEqual(report['alertas_declarados'], 1)
        self.assertEqual(report['registros_com_campos_de_acesso_preenchidos'], 1)

    def test_false_and_zero_are_present_not_claims_of_active_maintenance(self):
        report = module.audit_records([('SW', switch(maintenance_status=0))])
        self.assertEqual(report['cobertura_campos_da_projecao_sql_atual']['em_manutencao'], 1)
        self.assertEqual(report['cobertura_campos_da_projecao_sql_atual']['is_core'], 1)
        self.assertEqual(report['cobertura_campos_da_projecao_sql_atual']['maintenance_status'], 1)
        self.assertEqual(report['listas_alertas_vazias'], 1)

    def test_identity_is_origin_hostid_or_explicit_local_name_not_ip(self):
        records = [('ONE', switch()), ('TWO', switch(hostid=123)),
                   ('LOCAL_PRIVATE', switch(hostid=None, local_only=True)), ('MISSING', switch(hostid=None))]
        report = module.audit_records(records)
        self.assertEqual(report['identidades_tipo_origem_id_repetidas'], 1)
        self.assertEqual(report['sem_identidade_tipo_origem_id'], 1)
        self.assertEqual(report['ips_repetidos_sem_fusao'], 1)
        self.assertIsNone(module._hostid(True))
        self.assertIsNone(module._hostid('00123'))

    def test_invalid_records_flags_and_warning_lists_are_counted(self):
        report = module.audit_records([('A', None), ('B', switch(local_only='true', is_core=1,
                                                               warning_problemas={})),
                                       ('C', switch(warning_problemas=[None, {'PRIVATE': 1}]))])
        self.assertEqual(report['registros_invalidos'], 1)
        self.assertEqual(report['indicadores_booleanos_invalidos'], 2)
        self.assertEqual(report['listas_alertas_invalidas'], 1)
        self.assertEqual(report['alertas_nao_textuais'], 2)

    def test_dates_keep_naive_and_update_time_is_not_collection(self):
        report = module.audit_records([('A', switch(updated_at='2026-11-18T12:00:00Z'))])
        self.assertEqual(report['horarios_ultima_verificacao'], {'sem_fuso': 1})
        self.assertEqual(report['horarios_coleta_explicita'], {'ausente': 1})

    def test_non_ip_addresses_are_not_resolved_or_exported(self):
        report = module.audit_records([('A', switch(ip='HOST_PRIVATE.example.test'))])
        self.assertEqual(report['enderecos_nao_ip_sem_validacao_dns'], 1)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_operational_group_selection_does_not_access_other_records(self):
        rows, metadata = module.operational_records({'groups': {
            'switches': {'records': [switch(host='PRIVATE')], 'updated_at': '2026-11-18T10:00:00Z'},
            'admins': {'records': ['SECRET_PRIVATE']}}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(metadata['horario_publicacao_grupo'], 'com_fuso')
        with self.assertRaises(ValueError):
            module.operational_records({'groups': {'switches': {}}})

    def test_metadata_priority_candidates_conflicts_and_unmatched_entries(self):
        metadata = {'hostid:123': {'modelo': 'MODEL_PRIVATE', 'is_core': False},
                    'host:sw': {'modelo': 'OTHER_PRIVATE'}, 'unknown_private': None}
        report = module.audit_metadata(metadata, [('SW', switch())])
        self.assertEqual(report['switches_com_metadado_candidato'], 1)
        self.assertEqual(report['conflitos_entre_metadado_id_e_nome'], 1)
        self.assertEqual(report['metadados_sem_uso_por_chave_prioritaria'], 2)
        self.assertEqual(report['registros_invalidos'], 1)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_metadata_host_fallback_and_invalid_core_flag(self):
        report = module.audit_metadata({'host:sw': {'local': 'PRIVATE', 'is_core': 'false'}}, [('SW', switch())])
        self.assertEqual(report['switches_com_metadado_candidato'], 1)
        self.assertEqual(report['indicadores_core_invalidos'], 1)

    def test_comparison_never_matches_by_ip_or_silently_removes_duplicates(self):
        left = [('A', switch()), ('B', switch())]
        right = [('C', switch(hostid='456'))]
        report = module.compare_records(left, right)
        self.assertEqual(report['identidades_em_comum'], 0)
        self.assertEqual(report['identidades_duplicadas_cache_status'], 1)

    def test_source_files_remain_unchanged_and_sqlite_is_not_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'output').mkdir()
            (root / 'data/switch_updates').mkdir(parents=True)
            files = {
                root / 'output/switches_status_cache.json': json.dumps({'PRIVATE': switch()}),
                root / 'output/switches_metadata.json': json.dumps({'hostid:123': {'modelo': 'PRIVATE'}}),
                root / 'output/sentinel_operational_state.json': json.dumps({'groups': {'switches': {'records': [switch(host='PRIVATE')]}}}),
                root / 'data/switch_updates/scheduled_updates.sqlite3': 'NOT_A_DATABASE_PRIVATE'}
            for path, value in files.items():
                path.write_text(value, encoding='utf-8')
            original = {path: path.read_bytes() for path in files}
            report = module.audit_sources(root)
            self.assertTrue(report['comparacao_identidades']['comparavel'])
            self.assertFalse(report['fontes']['inventario_firmware_sqlite']['banco_aberto'])
            self.assertEqual(report['fontes']['inventario_firmware_sqlite']['situacao'], 'presente_conteudo_nao_auditado')
            self.assertEqual(original, {path: path.read_bytes() for path in files})
            self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertNotIn(str(root), json.dumps(report))

    def test_missing_sources_empty_cache_and_malformed_envelopes_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = module.audit_sources(root)
            self.assertEqual(report['fontes']['cache_status']['situacao'], 'ausente')
            self.assertEqual(list(root.iterdir()), [])
            (root / 'output').mkdir()
            path = root / 'output/switches_status_cache.json'
            path.write_text('{}')
            self.assertEqual(module.audit_sources(root)['fontes']['cache_status']['registros'], 0)
            path.write_text('[]')
            self.assertEqual(module.audit_sources(root)['fontes']['cache_status']['situacao'], 'estrutura_de_switches_invalida')

    def test_no_runtime_managers_sqlite_postgres_or_jobs_imported(self):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'sqlite3', 'psycopg', 'subprocess', 'web_config', 'config', 'gerenciar_switches',
                                    'services.switch_update_v01.scheduler', 'core.secret_store'})
        with patch.object(module, 'audit_sources', return_value={'modo': 'audit'}), redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main([]), 0)
        self.assertEqual(json.loads(out.getvalue()), {'modo': 'audit'})


if __name__ == '__main__':
    unittest.main()
