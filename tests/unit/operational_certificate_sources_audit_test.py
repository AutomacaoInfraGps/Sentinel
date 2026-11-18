import ast
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import audit_certificate_sources as module

NOW = datetime(2026, 11, 18, 15, tzinfo=timezone.utc)


def record(**changes):
    return {'thumbprint': 'A' * 40, 'subject': 'SUBJECT_PRIVATE', 'issuer': 'ISSUER_PRIVATE',
            'notAfter': (NOW + timedelta(days=40)).isoformat(), **changes}


class CertificateAuditTests(unittest.TestCase):
    def test_safe_summary_does_not_export_subject_issuer_fingerprint_or_secret(self):
        report = module.audit_payload([record(password='SECRET_PRIVATE', privateKey='KEY_PRIVATE')], NOW)
        text = json.dumps(report)
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('A' * 40, text)
        self.assertEqual(report['registros_com_campos_potencialmente_sensiveis'], 1)

    def test_list_single_object_empty_and_invalid_envelopes(self):
        self.assertEqual(module.audit_payload(record(), NOW)['formato'], 'objeto_unico')
        self.assertEqual(module.audit_payload([], NOW)['registros'], 0)
        self.assertEqual(module.audit_payload([None, 1, []], NOW)['registros_invalidos'], 3)
        for value in (None, 1, 'PRIVATE'):
            with self.assertRaises(ValueError):
                module.audit_payload(value, NOW)

    def test_aliases_mirror_page_and_conflicts_are_detected(self):
        entry = {'Thumbprint': 'B' * 40, 'Subject': 'PRIVATE', 'Issuer': 'PRIVATE',
                 'NotAfter': '2026-12-31T00:00:00Z'}
        report = module.audit_payload([entry], NOW)
        self.assertEqual(report['campos_textuais_preenchidos'], dict.fromkeys(module.ALIASES, 1))
        entry['subject'] = 'OTHER_PRIVATE'
        self.assertEqual(module.audit_payload([entry], NOW)['conflitos_entre_aliases'], 1)

    def test_nontext_fields_are_not_coerced_into_identities_or_dates(self):
        report = module.audit_payload([record(thumbprint=1, subject={}, issuer=True, notAfter={'PRIVATE': 1})], NOW)
        self.assertEqual(report['campos_nao_textuais']['notAfter'], 1)
        self.assertEqual(report['thumbprints_distintos_reconhecidos'], 0)
        self.assertEqual(report['vencimentos_por_formato'], {'invalido_ou_nao_iso': 1})

    def test_thumbprints_normalize_whitespace_case_and_classify_other_shapes(self):
        values = [record(thumbprint='aa ' * 20), record(thumbprint='A' * 40),
                  record(thumbprint='b' * 64), record(thumbprint='SECRET_PRIVATE'), record(thumbprint=None)]
        report = module.audit_payload(values, NOW)
        self.assertEqual(report['thumbprints_distintos_reconhecidos'], 2)
        self.assertEqual(report['thumbprints_repetidos'], 1)
        self.assertEqual(report['formato_thumbprint']['hex_64'], 1)
        self.assertEqual(report['formato_thumbprint']['ausente'], 1)

    def test_same_subject_is_not_identity_and_fingerprint_conflicts_not_merged(self):
        values = [record(), record(thumbprint='B' * 40), record(issuer='OTHER_PRIVATE')]
        report = module.audit_payload(values, NOW)
        self.assertEqual(report['registros'], 3)
        self.assertEqual(report['thumbprints_com_metadados_divergentes'], 1)
        self.assertEqual(report['assuntos_repetidos_sem_fusao'], 1)

    def test_aware_expiration_boundaries(self):
        moments = [NOW - timedelta(microseconds=1), NOW,
                   NOW + timedelta(days=30) - timedelta(microseconds=1), NOW + timedelta(days=30)]
        report = module.audit_payload([record(notAfter=value.isoformat()) for value in moments], NOW)
        self.assertEqual(report['validade_apenas_datas_com_fuso'],
                         {'expirado': 1, 'a_vencer_menos_30_dias': 2, 'valido_30_dias_ou_mais': 1})

    def test_expiration_offsets_z_and_naive_values_are_not_assumed_utc(self):
        values = ['2026-11-18T12:00:00-03:00', '2026-11-18T15:00:00Z',
                  '2026-11-18T15:00:00', '2026-11-18', None, '/Date(1234)/']
        report = module.audit_payload([record(notAfter=value) for value in values], NOW)
        self.assertEqual(report['validade_apenas_datas_com_fuso']['a_vencer_menos_30_dias'], 2)
        self.assertEqual(report['validade_apenas_datas_com_fuso']['nao_classificada_sem_data_com_fuso'], 4)

    def test_missing_host_store_and_collection_are_not_invented(self):
        report = module.audit_payload([record()], NOW)
        self.assertEqual(report['registros_com_host_explicito'], 0)
        self.assertEqual(report['registros_com_repositorio_explicito'], 0)
        self.assertEqual(report['coleta_explicita_por_registro'], {'ausente': 1})

    def test_explicit_host_store_and_collection_are_counted_not_exported(self):
        report = module.audit_payload([record(host='HOST_PRIVATE', store='STORE_PRIVATE',
                                              coletado_em=NOW.isoformat(), HasPrivateKey=True)], NOW)
        self.assertEqual(report['registros_com_host_explicito'], 1)
        self.assertEqual(report['registros_com_repositorio_explicito'], 1)
        self.assertEqual(report['registros_com_indicador_de_chave_privada'], 1)
        self.assertEqual(report['registros_com_campos_potencialmente_sensiveis'], 0)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_read_only_file_hash_no_raw_data_no_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'certificate_disk_report_acrab.json'
            original = json.dumps([record()]).encode()
            source.write_bytes(original)
            report = module.audit_sources(root, NOW)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(report['fontes']['relatorio_certificados']['situacao'], 'lido')
            self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertNotIn(str(root), json.dumps(report))

    def test_bom_diagnosed_duplicate_keys_and_broken_json_block(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'certificate_disk_report_acrab.json'
            source.write_bytes(b'\xef\xbb\xbf' + json.dumps([record()]).encode())
            self.assertTrue(module.audit_sources(root, NOW)['fontes']['relatorio_certificados']['bom_utf8_presente'])
            for raw in (b'[{"subject":"a","subject":"b"}]', b'{PRIVATE'):
                source.write_bytes(raw)
                report = module.audit_sources(root, NOW)
                self.assertEqual(report['fontes']['relatorio_certificados']['situacao'], 'leitura_ou_estrutura_invalida')

    def test_missing_source_creates_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(module.audit_sources(root, NOW)['fontes']['relatorio_certificados']['situacao'], 'ausente')
            self.assertEqual(list(root.iterdir()), [])

    def test_source_changing_during_read_is_not_reported_as_stable(self):
        raw = json.dumps([record()]).encode()
        with patch.object(Path, 'read_bytes', side_effect=[raw, b'[]']):
            report = module.audit_sources(Path('unused'), NOW)
        self.assertEqual(report['fontes']['relatorio_certificados']['situacao'], 'alterado_durante_leitura')
        self.assertNotIn('sha256_arquivo', report['fontes']['relatorio_certificados'])

    def test_no_runtime_collector_vault_sql_or_network_imports(self):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'web_config', 'config', 'subprocess', 'requests', 'psycopg',
                                    'coleta_dados_acraby', 'core.secret_store', 'gerenciar_regionais'})

    def test_cli_only_safe_json(self):
        with patch.object(module, 'audit_sources', return_value={'modo': 'audit'}), redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main([]), 0)
        self.assertEqual(json.loads(out.getvalue()), {'modo': 'audit'})


if __name__ == '__main__':
    unittest.main()
