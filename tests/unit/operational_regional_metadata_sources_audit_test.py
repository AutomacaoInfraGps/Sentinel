import ast
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import audit_regional_metadata_sources as module


def payload(**entry):
    return {'regionais': {'REG_PRIVATE': {'nome': 'NAME_PRIVATE', 'descricao': 'ADDRESS_PRIVATE',
                                        'estado': 'SP', 'uf': 'SP', 'password': 'SECRET_PRIVATE', **entry}},
            'configuracao': {'ultima_atualizacao': '2026-11-19T09:00:00-03:00'}}


class RegionalMetadataAuditTests(unittest.TestCase):
    def test_counts_without_exporting_labels_descriptions_secrets_or_unknown_keys(self):
        report = module.audit_catalog(payload())
        self.assertEqual(report['regionais'], 1)
        self.assertEqual(report['campos_por_situacao']['descricao'], {'texto_preenchido': 1})
        self.assertEqual(report['formato_estado_uf']['estado'], {'sigla_reconhecida': 1})
        self.assertEqual(report['publicacao_cadastro'], 'com_fuso')
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_absent_null_empty_whitespace_nontext_and_zero_are_distinct(self):
        entries = [{}, {'descricao': None}, {'descricao': ''}, {'descricao': '  '},
                   {'descricao': False}, {'descricao': 0}, {'descricao': 'PRIVATE'}]
        report = module.audit_catalog({'regionais': {f'REG_{i}': record for i, record in enumerate(entries)}})
        self.assertEqual(report['campos_por_situacao']['descricao'],
                         {'ausente': 1, 'nulo': 1, 'texto_vazio': 1, 'somente_espacos': 1,
                          'nao_textual': 2, 'texto_preenchido': 1})

    def test_state_conflict_never_resolved_or_inferred(self):
        report = module.audit_catalog(payload(estado='SP', uf='RJ'))
        self.assertEqual(report['estado_uf_preenchidos_divergentes_apos_normalizacao'], 1)
        report = module.audit_catalog(payload(estado=' sp ', uf='SP'))
        self.assertEqual(report['estado_uf_preenchidos_divergentes_apos_normalizacao'], 0)
        self.assertEqual(report['estado_uf_preenchidos_textualmente_diferentes'], 1)
        self.assertEqual(report['formato_estado_uf']['estado'], {'sigla_reconhecida_apos_normalizacao': 1})

    def test_unknown_state_values_do_not_become_output_keys(self):
        report = module.audit_catalog(payload(estado='STATE_PRIVATE', uf={'secret': 'PRIVATE'}))
        self.assertEqual(report['formato_estado_uf']['estado'], {'texto_fora_das_siglas': 1})
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_invalid_records_codes_normalized_duplicates_and_names(self):
        report = module.audit_catalog({'regionais': {'REG_A': {'nome': 'NAME_PRIVATE'},
                                                     'reg_a': {'nome': 'name_private'}, 'REG_BAD': None}})
        self.assertEqual(report['registros_invalidos'], 1)
        self.assertEqual(report['codigos_fora_do_padrao_sql_atual'], 1)
        self.assertEqual(report['codigos_repetidos_apos_normalizacao'], 1)
        self.assertEqual(report['nomes_repetidos_sem_fusao'], 1)

    def test_lengths_and_padding_diagnosed_without_truncation_or_raw_output(self):
        report = module.audit_catalog(payload(nome='X' * 241, descricao='Y' * 501 + ' '))
        self.assertEqual(report['limites_da_tela_e_projecao_atual'], {'nome_acima_240': 1, 'descricao_acima_500': 1})
        self.assertEqual(report['espacos_externos_por_campo']['descricao'], 1)

    def test_invalid_envelope_is_not_successful_empty_inventory(self):
        for value in (None, [], {}, {'regionais': []}):
            self.assertFalse(module.audit_catalog(value)['estrutura_valida'])
        self.assertEqual(module.audit_catalog({'regionais': {}})['regionais'], 0)

    def test_source_hash_and_stable_read_without_writes_or_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.json'
            original = json.dumps(payload()).encode()
            path.write_bytes(original)
            report = module.audit_sources(path)
            self.assertEqual(report['fontes']['cadastro_regional']['situacao'], 'lido')
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertNotIn(str(path), json.dumps(report))
            with patch.object(Path, 'read_bytes', side_effect=[original, b'{}']):
                self.assertEqual(module.audit_sources(path)['fontes']['cadastro_regional']['situacao'], 'alterado_durante_leitura')

    def test_invalid_json_duplicate_keys_or_missing_source_fail_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.json'
            self.assertEqual(module.audit_sources(path)['fontes']['cadastro_regional']['situacao'], 'ausente')
            for raw in (b'PRIVATE', b'{"regionais":{},"regionais":{}}'):
                path.write_bytes(raw)
                self.assertEqual(module.audit_sources(path)['fontes']['cadastro_regional']['situacao'], 'leitura_ou_estrutura_invalida')

    def test_cli_and_no_side_effectful_imports(self):
        with patch.object(module, 'audit_sources', return_value={'modo': 'audit'}) as audit, redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main(['--source', 'unused.json']), 0)
            audit.assert_called_once_with(Path('unused.json'))
        self.assertEqual(json.loads(out.getvalue()), {'modo': 'audit'})
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imports & {'gerenciar_regionais', 'web_config', 'config', 'psycopg', 'core.secret_store'})


if __name__ == '__main__':
    unittest.main()
