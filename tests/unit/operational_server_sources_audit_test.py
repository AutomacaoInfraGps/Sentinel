import ast
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import audit_server_sources as module


def server(**changes):
    return {'id': 'SERVER_PRIVATE', 'nome': 'NAME_PRIVATE', 'ip': '192.0.2.1',
            'status': 'online', 'ativo': False, 'tempo_resposta': 0,
            'ultima_verificacao': '2026-11-18T10:00:00', **changes}


class ServerSourceAuditTests(unittest.TestCase):
    def test_summary_never_exports_names_addresses_errors_secrets_or_unknown_status(self):
        record = server(senha='SECRET_PRIVATE', erro='ERROR_PRIVATE', status='STATUS_PRIVATE')
        report = module.audit_records([('REG_PRIVATE', record)])
        encoded = json.dumps(report)
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn('192.0.2.1', encoded)
        self.assertEqual(report['por_status_declarado'], {'ausente_ou_outro': 1})
        self.assertEqual(report['registros_com_campos_de_acesso_preenchidos'], 1)

    def test_zero_false_and_maintenance_fields_are_present_without_coercing(self):
        report = module.audit_records([('REG', server(em_manutencao=False, maintenanceid=0))])
        self.assertEqual(report['cobertura_campos_da_projecao_sql_atual']['ativo'], 1)
        self.assertEqual(report['cobertura_campos_da_projecao_sql_atual']['tempo_resposta'], 1)
        self.assertEqual(report['cobertura_campos_fora_da_projecao_sql_atual']['em_manutencao'], 1)

    def test_ids_are_scoped_to_region_and_duplicate_normalization_is_diagnostic(self):
        values = [('A', server()), ('B', server()), ('A', server(id='server_private'))]
        report = module.audit_records(values)
        self.assertEqual(report['identidades_regional_id_repetidas_normalizadas'], 1)
        self.assertEqual(report['ips_repetidos_na_mesma_regional'], 1)

    def test_invalid_records_ids_and_addresses_counted(self):
        values = [('A', None), ('A', server(id=3, ip='PRIVATE')), ('A', server(id=' padded '))]
        report = module.audit_records(values)
        self.assertEqual(report['registros_invalidos'], 1)
        self.assertEqual(report['ids_nao_textuais'], 1)
        self.assertEqual(report['ids_com_espacos_externos'], 1)
        self.assertEqual(report['enderecos_ip_invalidos'], 1)

    def test_dates_not_synthesized_and_update_time_not_used_as_collection(self):
        report = module.audit_records([('A', server(updated_at='2026-11-18T12:00:00Z'))])
        self.assertEqual(report['horarios_ultima_verificacao'], {'sem_fuso': 1})
        self.assertEqual(report['horarios_coleta_explicita'], {'ausente': 1})

    def test_hardware_presence_does_not_validate_or_export_measurements(self):
        values = [('A', server(hardware={'cpu': {'model': 'PRIVATE'}, 'memoria_gib': 0,
                                        'discos': [{'drive': 'PRIVATE'}]}, details={'password': 'PRIVATE'})),
                  ('A', server(hardware='PRIVATE'))]
        report = module.audit_records(values)
        self.assertEqual(report['registros_com_hardware'], 2)
        self.assertEqual(report['objetos_hardware_invalidos'], 1)
        self.assertEqual(report['campos_hardware_presentes_sem_validacao_de_medicao']['cpu'], 1)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_catalog_lists_empty_invalid_and_metadata_handled_separately(self):
        value = {'regionais': {'A': {'servidores': []}, 'B': {}, 'C': {'servidores': [server()]}},
                 'configuracao': {'ultima_atualizacao': '2026-11-18T12:00:00Z'}}
        records, info = module.catalog_records(value)
        self.assertEqual(len(records), 1)
        self.assertEqual(info['listas_servidores_invalidas_ou_ausentes'], 1)
        self.assertEqual(info['horario_publicacao_cadastro'], 'com_fuso')
        with self.assertRaises(ValueError):
            module.catalog_records({})

    def test_operational_group_does_not_read_other_domains(self):
        value = {'groups': {'servidores': {'updated_at': '2026-11-18T12:00:00Z',
                                         'records': [server(regional='A'), None]},
                            'admins': {'records': ['PRIVATE']}}}
        records, info = module.operational_records(value)
        self.assertEqual(len(records), 2)
        self.assertEqual(info['registros_sem_regional_textual'], 1)
        with self.assertRaises(ValueError):
            module.operational_records({'groups': {'servidores': {'records': None}}})

    def test_matching_by_exact_id_is_scoped_and_ip_only_not_approved(self):
        catalog = [('A', server()), ('B', server(id='OTHER'))]
        operational = [('A', server(status='offline')), ('A', server(id='MISSING')),
                       ('C', server()), ('A', None)]
        result = module.compare_records(catalog, operational)
        self.assertEqual(result['vinculos_candidatos'], {
            'id_exato_na_regional': 1, 'apenas_ip_na_regional_candidato_nao_aprovado': 1,
            'sem_correspondencia_na_regional': 1, 'registro_invalido': 1})
        self.assertEqual(result['divergencias_em_pares_por_id_exato']['status'], 1)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_ambiguous_ip_or_conflicting_id_ip_never_gets_first_candidate(self):
        catalog = [('A', server()), ('A', server(id='OTHER', ip='192.0.2.2'))]
        result = module.compare_records(catalog, [('A', server(ip='192.0.2.2'))])
        self.assertEqual(result['vinculos_candidatos'], {'id_e_ip_apontam_cadastros_diferentes': 1})
        catalog.append(('A', server(id='THIRD')))
        result = module.compare_records(catalog, [('A', server())])
        self.assertEqual(result['vinculos_candidatos'], {'ambiguo_nao_aprovado': 1})

    def test_sources_not_modified_and_only_safe_data_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'output').mkdir()
            catalog = root / 'estrutura_regionais.json'
            cache = root / 'output/sentinel_operational_state.json'
            catalog.write_text(json.dumps({'regionais': {'A': {'servidores': [server(senha='PRIVATE')]}}}))
            cache.write_text(json.dumps({'groups': {'servidores': {'records': [server(regional='A')]}}}))
            originals = {path: path.read_bytes() for path in (catalog, cache)}
            report = module.audit_sources(root)
            self.assertTrue(report['comparacao_cache_cadastro']['comparavel'])
            self.assertEqual(originals, {path: path.read_bytes() for path in originals})
            self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertNotIn(str(root), json.dumps(report))

    def test_missing_sources_do_not_create_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = module.audit_sources(root)
            self.assertEqual(report['fontes']['cadastro_regional']['situacao'], 'ausente')
            self.assertFalse(report['comparacao_cache_cadastro']['comparavel'])
            self.assertEqual(list(root.iterdir()), [])

    def test_duplicate_keys_and_concurrent_change_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.json'
            path.write_bytes(b'{"regionais":{},"regionais":{}}')
            self.assertEqual(module._read_source(path)[1]['situacao'], 'leitura_ou_estrutura_invalida')
            with patch.object(Path, 'read_bytes', side_effect=[b'{}', b'[]']):
                self.assertEqual(module._read_source(path)[1]['situacao'], 'alterado_durante_leitura')

    def test_cli_safe_and_no_runtime_collectors_vault_or_sql_imports(self):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'operational_state', 'subprocess', 'requests',
                                    'gerenciar_regionais', 'gerenciar_servidores', 'psycopg', 'core.secret_store'})
        with patch.object(module, 'audit_sources', return_value={'modo': 'audit'}), redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main([]), 0)
        self.assertEqual(json.loads(out.getvalue()), {'modo': 'audit'})


if __name__ == '__main__':
    unittest.main()
