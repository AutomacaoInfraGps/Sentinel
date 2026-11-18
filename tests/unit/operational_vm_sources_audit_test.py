from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.database import audit_vm_sources as module

REGIONS = {'REG_TEST': {'nome': 'Test', 'servidores': [{'id': 'SERVER_PRIVATE', 'ip': '192.0.2.1'}]}}


def vm(**changes):
    return {'id': 'VM_PRIVATE', 'name': 'NAME_PRIVATE', 'ip': '192.0.2.1',
            'regional': 'REG_TEST', 'username': 'ACCOUNT_PRIVATE', 'password': 'SECRET_PRIVATE',
            'status': 'Running', 'last_check': '2026-11-18T08:00:00', **changes}


class VmSourceAuditTests(unittest.TestCase):
    def test_default_output_does_not_export_names_addresses_accounts_or_raw_details(self):
        report = module.audit_records([vm(details={'secret': 'DETAIL_PRIVATE'})], REGIONS)
        encoded = json.dumps(report)
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn('192.0.2.1', encoded)
        self.assertEqual(report['registros'], 1)
        self.assertEqual(report['registros_com_campos_de_acesso_preenchidos'], 1)
        self.assertEqual(report['comparacao_com_cadastro_servidores'], {'candidato_unico_por_ip': 1})
        self.assertFalse(report['registros_fundidos_com_servidores'])

    def test_identifiers_and_duplicate_addresses_are_counted_without_merging(self):
        records = [vm(), vm(), vm(id=None), vm(id=12), vm(id=' padded ')]
        report = module.audit_records(records, REGIONS)
        self.assertEqual(report['registros'], 5)
        self.assertEqual(report['ids_repetidos'], 1)
        self.assertEqual(report['sem_id_textual'], 2)
        self.assertEqual(report['ids_nao_textuais'], 1)
        self.assertEqual(report['ids_com_espacos_externos'], 1)
        self.assertEqual(report['ips_presentes_em_varios_registros'], 1)

    def test_ip_lists_invalid_items_and_primary_conflicts(self):
        report = module.audit_records([vm(ipAddresses=['192.0.2.2', 'invalid', None]),
                                        vm(ip='SECRET_PRIVATE', ipAddresses={})], REGIONS)
        self.assertEqual(report['ip_principal_fora_da_lista'], 1)
        self.assertEqual(report['itens_ip_invalidos'], 2)
        self.assertEqual(report['listas_ip_invalidas'], 1)
        self.assertEqual(report['enderecos_principais_invalidos'], 1)
        self.assertNotIn('SECRET_PRIVATE', json.dumps(report))

    def test_exact_normalized_and_rg_bindings_remain_unapproved(self):
        records = [vm(), vm(regional='Test'), vm(regional='REG TEST'), vm(regional='RG_TEST'),
                   vm(regional='Unknown'), vm(regional='')]
        report = module.audit_records(records, REGIONS, unresolved=True)
        bindings = report['vinculo_regional_candidato']
        self.assertEqual(bindings['codigo_exato'], 1)
        self.assertEqual(bindings['nome_exato_candidato_unico'], 1)
        self.assertEqual(bindings['prefixo_rg_candidato_nao_aprovado'], 1)
        self.assertFalse(report['vinculos_aprovados_pela_auditoria'])
        self.assertNotIn('VM_PRIVATE', json.dumps(report['rotulos_regionais_pendentes']))

    def test_name_ambiguity_never_picks_first_match(self):
        regions = {'REG_ONE': {'nome': 'Same'}, 'REG_TWO': {'nome': 'Same'}}
        report = module.audit_records([vm(regional='Same')], regions, unresolved=True)
        self.assertEqual(report['vinculo_regional_candidato'], {'ambiguo': 1})
        self.assertEqual(report['rotulos_regionais_pendentes'][0]['candidatos_regionais'], ['REG_ONE', 'REG_TWO'])

    def test_ip_match_is_only_candidate_and_can_be_ambiguous(self):
        regions = deepcopy(REGIONS)
        regions['REG_TEST']['servidores'].append({'ip': '192.0.2.1'})
        report = module.audit_records([vm()], regions)
        self.assertEqual(report['comparacao_com_cadastro_servidores'], {'varios_candidatos_por_ip': 1})
        self.assertFalse(report['registros_fundidos_com_servidores'])

    def test_arbitrary_status_and_nontextual_fields_do_not_leak(self):
        report = module.audit_records([vm(status='TOKEN_PRIVATE', last_check={'secret': 'PRIVATE'},
                                         details='DETAIL_PRIVATE'), None, 'PRIVATE'], REGIONS)
        self.assertEqual(report['por_status_declarado'], {'outro_ou_ausente': 1})
        self.assertEqual(report['registros_invalidos'], 2)
        self.assertEqual(report['details_invalidos'], 1)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_time_coverage_does_not_infer_date_or_timezone(self):
        report = module.audit_records([vm(), vm(last_check=None), vm(last_check='08:00:00'),
                                        vm(last_check='2026-11-18T11:00:00+00:00')], REGIONS)
        self.assertEqual(report['horarios_ultima_verificacao'], {'sem_fuso': 1, 'ausente': 1,
                         'invalido_ou_nao_iso': 1, 'com_fuso': 1})
        self.assertEqual(report['horarios_coleta_explicita'], {'ausente': 4})

    def test_missing_vm_file_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'estrutura_regionais.json').write_text(json.dumps({'regionais': REGIONS}))
            report = module.audit_sources(root)
            self.assertEqual(report['fontes']['cadastro_vms']['situacao'], 'ausente_arquivo_nao_criado')
            self.assertFalse((root / 'data').exists())

    def test_sources_stay_byte_identical_and_no_runtime_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            paths = {root / 'estrutura_regionais.json': json.dumps({'regionais': REGIONS}).encode(),
                     root / 'data/vms.json': json.dumps([vm()]).encode()}
            for path, raw in paths.items():
                path.write_bytes(raw)
            report = module.audit_sources(root)
            self.assertEqual(report['fontes']['cadastro_vms']['registros'], 1)
            self.assertEqual(paths, {path: path.read_bytes() for path in paths})

    def test_bad_envelopes_and_duplicate_json_keys_are_not_empty_inventories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'estrutura_regionais.json').write_text(json.dumps({'regionais': REGIONS}))
            for raw in ('{}', '{"vms":[]}', '[{"id":"a","id":"b"}]', 'PRIVATE'):
                (root / 'data/vms.json').write_text(raw)
                report = module.audit_sources(root)
                self.assertEqual(report['fontes']['cadastro_vms']['situacao'], 'leitura_ou_estrutura_invalida')
                self.assertNotIn('PRIVATE', json.dumps(report))

    def test_empty_vm_inventory_is_reported_not_fabricated(self):
        report = module.audit_records([], REGIONS)
        self.assertEqual(report['registros'], 0)
        self.assertEqual(report['por_status_declarado'], {})

    def test_missing_or_bad_catalog_does_not_guess_regional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(module.audit_sources(root)['fontes']['catalogo_regional']['situacao'], 'ausente_ou_invalido')

    def test_cli_serializes_only_safe_summary(self):
        with patch.object(module, 'audit_sources', return_value={'modo': 'auditoria_vms_somente_leitura_sem_banco'}) as audit, \
                redirect_stdout(StringIO()) as out:
            self.assertEqual(module.main([]), 0)
        audit.assert_called_once_with(unresolved=False)
        self.assertEqual(json.loads(out.getvalue())['modo'], 'auditoria_vms_somente_leitura_sem_banco')


if __name__ == '__main__':
    unittest.main()
