import ast
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import audit_replication_sources as module


def record(**changes):
    return {'nome': 'HOST_PRIVATE.example.test', 'tipo': 'Origem', 'status': 'OK',
            'delta': '00:10:00', 'parceiros': 4, 'falhas': 0, 'erros': 0,
            'ultima_replicacao': '2026-11-18T08:00:00', 'detalhes': 'ERROR_PRIVATE', **changes}


def payload(**changes):
    return {'timestamp': '2026-11-18T08:00:00', 'total_servidores': 1,
            'servidores': [record()], 'erros_operacionais': ['1722 - HOST_PRIVATE'], **changes}


class ReplicationAuditTests(unittest.TestCase):
    def test_summary_does_not_echo_hosts_errors_unknown_statuses_or_secrets(self):
        value = payload(password='SECRET_PRIVATE', servidores=[record(status='STATUS_PRIVATE')])
        report = module.audit_payload(value)
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertEqual(report['erros_operacionais'], 1)
        self.assertEqual(report['por_status_declarado'], {'ausente_ou_outro': 1})

    def test_source_destination_for_same_host_are_not_duplicate_identity(self):
        report = module.audit_payload(payload(servidores=[record(), record(tipo='Destino')]))
        self.assertEqual(report['registros'], 2)
        self.assertEqual(report['controladores_distintos_por_nome_completo'], 1)
        self.assertEqual(report['nomes_em_varias_linhas'], 1)
        self.assertEqual(report['identidades_nome_secao_repetidas'], 0)
        self.assertTrue(report['total_declarado_difere_de_linhas'])

    def test_same_host_and_direction_repeated_detected(self):
        report = module.audit_payload(payload(servidores=[record(), record()]))
        self.assertEqual(report['identidades_nome_secao_repetidas'], 1)

    def test_legacy_envelope_does_not_invent_destination_status_or_date(self):
        value = {'controladores': 1, 'detalhes': {'controladores': [
            {'nome': 'HOST_PRIVATE', 'latencia': '10m', 'sucesso_total': '0 / 4', 'erros': 0}],
            'erros_operacionais': []}}
        report = module.audit_payload(value)
        self.assertEqual(report['formato'], 'detalhes_controladores')
        self.assertEqual(report['por_secao_declarada'], {'ausente_ou_outro': 1})
        self.assertEqual(report['horarios_ultima_replicacao_declarada'], {'ausente': 1})
        self.assertEqual(report['por_status_declarado'], {'ausente_ou_outro': 1})

    def test_modern_envelope_has_precedence_like_ui(self):
        value = payload(detalhes={'controladores': [record(), record()]})
        self.assertEqual(module.audit_payload(value)['registros'], 1)

    def test_invalid_lists_are_not_reported_as_empty_healthy_inventory(self):
        for value in (payload(servidores={}), {}, payload(servidores=None)):
            report = module.audit_payload(value)
            self.assertFalse(report['lista_registros_valida'])
            self.assertNotIn('registros', report)
        report = module.audit_payload(payload(servidores=[]))
        self.assertEqual(report['registros'], 0)

    def test_invalid_rows_counters_ratios_and_errors_are_counted_without_echo(self):
        value = payload(servidores=[record(falhas=5, erros=4), record(parceiros=True, erros=-1,
                        sucesso_total='SECRET_PRIVATE'), None], erros_operacionais=[None, {'secret': 'PRIVATE'}])
        report = module.audit_payload(value)
        self.assertEqual(report['registros_invalidos'], 1)
        self.assertEqual(report['contadores_invalidos'], 2)
        self.assertEqual(report['linhas_falhas_erros_divergentes'], 1)
        self.assertEqual(report['linhas_falhas_maiores_total'], 1)
        self.assertEqual(report['sucesso_total_invalido'], 1)
        self.assertEqual(report['erros_operacionais_nao_textuais'], 2)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_full_names_are_not_merged_by_short_name(self):
        value = payload(servidores=[record(nome='DC.a.test'), record(nome='DC.b.test')])
        report = module.audit_payload(value)
        self.assertEqual(report['controladores_distintos_por_nome_completo'], 2)
        self.assertEqual(report['nomes_curtos_com_varias_identidades_completas'], 1)

    def test_time_coverage_is_not_synthesized(self):
        value = payload(servidores=[record(), record(ultima_replicacao=None),
                                   record(ultima_replicacao='08:00:00')])
        report = module.audit_payload(value)
        self.assertEqual(report['horarios_ultima_replicacao_declarada'], {'sem_fuso': 1, 'ausente': 1, 'invalido_ou_nao_iso': 1})
        self.assertEqual(report['horarios_coleta_explicita'], {'ausente': 3})

    def test_selector_mirrors_total_rule_and_not_freshness(self):
        local = payload(total_servidores=1, timestamp='2026-11-18T12:00:00')
        public = payload(total_servidores=2, timestamp='2025-01-01T12:00:00')
        self.assertEqual(module.predict_selection(local, public), 'publica')
        public['total_servidores'] = 1
        self.assertEqual(module.predict_selection(local, public), 'local')
        self.assertEqual(module.predict_selection(None, public), 'publica')
        self.assertEqual(module.predict_selection(local, None), 'local')
        self.assertEqual(module.predict_selection(None, None), 'nenhuma')
        public['total_servidores'] = 'PRIVATE'
        self.assertEqual(module.predict_selection(local, public), 'nao_reproduzivel_com_seguranca')

    def test_totals_with_booleans_negative_or_float_are_not_silently_coerced(self):
        for total in (True, -1, 1.5, 'PRIVATE'):
            report = module.audit_payload(payload(total_servidores=total))
            self.assertEqual(report['totais_declarados_invalidos'], 1)
            self.assertIsNone(report['total_usado_pela_selecao_da_tela'])

    def test_public_path_respects_config_environment_without_importing_config(self):
        with patch.dict(os.environ, {'AUTOMACAO_PUBLIC_BASE': 'C:/Custom', 'PUBLIC': 'C:/Public'}):
            path, origin = module.public_source_path()
            self.assertEqual(path, Path('C:/Custom/data/replicacao.json'))
            self.assertEqual(origin, 'AUTOMACAO_PUBLIC_BASE')
        with patch.dict(os.environ, {'AUTOMACAO_PUBLIC_BASE': '', 'PUBLIC': 'C:/Public'}):
            self.assertEqual(module.public_source_path()[0], Path('C:/Public/Automacao/data/replicacao.json'))

    def test_missing_sources_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = module.audit_sources(root, root / 'public/data/replicacao.json')
            self.assertEqual(report['selecao_prevista_pela_regra_da_tela'], 'nenhuma')
            self.assertEqual(list(root.iterdir()), [])

    def test_source_encodings_match_runtime_and_duplicate_keys_block(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'replicacao.json'
            value = payload(servidores=[record(detalhes='a\u00e7ao')])
            path.write_bytes(json.dumps(value, ensure_ascii=False).encode('latin1'))
            _, info = module._read_source(path)
            self.assertEqual(info['codificacao'], 'latin1')
            _, local = module._read_source(path)
            self.assertEqual(local['situacao'], 'lido')
            path.write_bytes(b'{"servidores":[],"servidores":[]}')
            self.assertEqual(module._read_source(path)[1]['situacao'], 'leitura_ou_estrutura_invalida')

    def test_audit_never_changes_source_bytes_or_exposes_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            path = root / 'data/replicacao.json'
            raw = json.dumps(payload()).encode()
            path.write_bytes(raw)
            report = module.audit_sources(root, path)
            self.assertEqual(path.read_bytes(), raw)
            self.assertNotIn(str(root), json.dumps(report))
            self.assertNotIn('PRIVATE', json.dumps(report))

    def test_no_runtime_config_subprocess_sql_or_network_imports(self):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'data_store', 'core.data_store', 'subprocess', 'requests', 'psycopg', 'socket'})

    def test_cli_prints_only_safe_report(self):
        with patch.object(module, 'audit_sources', return_value={'modo': 'auditoria_replicacao_ad_somente_leitura_sem_banco'}), \
                redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main([]), 0)
        self.assertEqual(json.loads(out.getvalue())['modo'], 'auditoria_replicacao_ad_somente_leitura_sem_banco')


if __name__ == '__main__':
    unittest.main()
