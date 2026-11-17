from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts.database import audit_administrative_sources as module

REGIONS = {'REG_BAHIA': {'nome': 'Bahia', 'descricao': 'PRIVATE', 'senha': 'SECRET_PRIVATE'}}


class AdministrativeSourcesTest(unittest.TestCase):
    def test_admin_baseline_and_observation_are_separate_counts(self):
        cache = {'atualizado_em': '2026-11-17T12:00:00', 'dispositivos': {
            'FGT_PRIVATE': {'nome': 'FGT_PRIVATE', 'tipo': 'fortigate', 'admins': ['ACCOUNT_PRIVATE'],
                            'consulta_valida': False, 'consulta_indisponivel': True,
                            'ultima_coleta_valida': '2026-11-10T12:00:00', 'motivo': 'SECRET_PRIVATE'},
            '__fortimanager__': {'nome': 'FortiManager', 'tipo': 'fortimanager', 'admins': []}}}
        baseline = {'FGT_PRIVATE': ['APPROVED_PRIVATE'], 'OLD_PRIVATE': ['APPROVED_PRIVATE']}
        firewalls = {'firewalls_por_regional': {'REG_BAHIA': [{'nome': 'FGT_PRIVATE'}]}}
        before = deepcopy((cache, baseline, firewalls))
        report = module.audit_admins(cache, baseline, firewalls, REGIONS)
        self.assertEqual(before, (cache, baseline, firewalls))
        self.assertEqual(report['baseline_contas'], 2)
        self.assertEqual(report['contas_no_cache_incluindo_dados_anteriores'], 1)
        self.assertEqual(report['baseline_dispositivos_fora_do_cache'], 1)
        self.assertEqual(report['consulta_valida_declarada'], {'nao': 1, 'ausente_ou_invalida': 1})
        self.assertEqual(report['vinculo_por_nome_exato_firewall'], {'unico': 1, 'central_sem_regional': 1})
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_bad_lists_and_ambiguous_equipment_are_not_silently_resolved(self):
        regions = {**REGIONS, 'REG_OTHER': {}}
        report = module.audit_admins({'dispositivos': {'d': {'tipo': 'fortigate', 'nome': 'FGT', 'admins': 'bad'}}},
                                     {'d': ['u', 'u', None]},
                                     {'firewalls_por_regional': {code: [{'nome': 'FGT'}] for code in regions}}, regions)
        self.assertEqual(report['listas_admins_invalidas'], 1)
        self.assertEqual(report['baseline_contas_invalidas'], 1)
        self.assertEqual(report['baseline_duplicados_exatos'], 1)
        self.assertEqual(report['vinculo_por_nome_exato_firewall'], {'ambiguo': 1})

    def test_contacts_count_roles_without_disclosing_or_approving_links(self):
        rows = [{'NOME_REGIONAL': 'V021_BAHIA', 'NOME_DIRETOR_1': 'NAME_PRIVATE',
                 'EMAIL_DIRETOR': 'EMAIL_PRIVATE@example.test', 'NOME_GERENTE': 'SEM_GERENTE',
                 'EMAIL_APOIO_1': 'EMAIL_PRIVATE@example.test'}]
        before = deepcopy(rows)
        report = module.audit_contacts(rows, REGIONS)
        self.assertEqual(before, rows)
        self.assertEqual(report['por_papel']['diretor']['com_email'], 1)
        self.assertEqual(report['por_papel']['gerente']['com_nome'], 0)
        self.assertEqual(report['por_papel']['apoio_1']['email_sem_nome'], 1)
        self.assertEqual(report['candidatos_regionais_por_codigo_ou_nome_sem_aproximacao'], {'candidato_unico': 1})
        self.assertFalse(report['vinculos_aprovados_pela_auditoria'])
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_contact_duplicates_ambiguity_and_description_never_become_a_link(self):
        regions = {'REG_ONE': {'nome': 'Same', 'descricao': 'PRIVATE'}, 'REG_TWO': {'nome': 'Same'}}
        report = module.audit_contacts([{'NOME_REGIONAL': 'Same'}, {'NOME_REGIONAL': 'SAME'},
                                        {'NOME_REGIONAL': 'PRIVATE'}], regions)
        self.assertEqual(report['rotulos_regionais_duplicados_normalizados'], 1)
        self.assertEqual(report['candidatos_regionais_por_codigo_ou_nome_sem_aproximacao'], {'ambiguo': 2, 'nao_encontrado': 1})

    def test_file_reader_never_saves_and_rejects_formulas_or_wrong_sheet(self):
        workbook = MagicMock()
        workbook.sheetnames = ['Contacts']
        cells = [SimpleNamespace(value=column, data_type='s') for column in module.CONTACT_COLUMNS]
        data = [SimpleNamespace(value='V021_BAHIA' if i == 0 else '', data_type='s') for i in range(len(cells))]
        workbook.__getitem__.return_value.iter_rows.side_effect = lambda: iter([cells, data])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.xlsx'
            path.touch()
            with patch('openpyxl.load_workbook', return_value=workbook) as load:
                self.assertEqual(module._contacts_from_workbook(path, 'Contacts', REGIONS)['linhas'], 1)
                self.assertTrue(load.call_args.kwargs['read_only'])
                self.assertFalse(load.call_args.kwargs['data_only'])
                workbook.save.assert_not_called()
                workbook.close.assert_called()
                self.assertEqual(module._contacts_from_workbook(path, 'Missing', REGIONS)['situacao'], 'aba_configurada_ausente')
                data[1] = SimpleNamespace(value='=PRIVATE()', data_type='f')
                result = module._contacts_from_workbook(path, 'Contacts', REGIONS)
                self.assertEqual(result['situacao'], 'formulas_exigem_revisao')
                self.assertNotIn('PRIVATE', json.dumps(result))
                workbook.save.assert_not_called()

    def test_reader_duplicate_header_is_blocked(self):
        workbook = MagicMock()
        workbook.sheetnames = ['Contacts']
        headers = [SimpleNamespace(value=column) for column in (*module.CONTACT_COLUMNS, 'NOME_REGIONAL')]
        workbook.__getitem__.return_value.iter_rows.return_value = iter([headers])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.xlsx'
            path.touch()
            with patch('openpyxl.load_workbook', return_value=workbook):
                result = module._contacts_from_workbook(path, '', REGIONS)
                self.assertEqual(result['situacao'], 'colunas_obrigatorias_ausentes_ou_duplicadas')

    def test_missing_config_or_sources_report_safe_status_not_exception_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = module.audit_sources(root)
            self.assertEqual(report['fontes']['configuracao']['situacao'], 'configuracao_ou_catalogo_invalido')
            (root / 'environment.json').write_text(json.dumps({'password': 'SECRET_PRIVATE'}), encoding='utf-8')
            (root / 'estrutura_regionais.json').write_text(json.dumps({'regionais': REGIONS}), encoding='utf-8')
            report = module.audit_sources(root)
            self.assertEqual(report['fontes']['monitor_admins']['situacao'], 'fonte_ausente_ou_invalida')
            self.assertEqual(report['fontes']['contatos_sla']['situacao'], 'planilha_nao_configurada')
            self.assertNotIn('PRIVATE', json.dumps(report))

    def test_configured_external_sources_are_used_and_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'output').mkdir()
            files = {'environment.json': {'fortianalyzer': {'admin_baseline_file': 'custom.json'},
                                         'email_contatos': {'xlsx_path': str(root / 'external.xlsx'), 'sheet_name': 'Contacts'}},
                     'estrutura_regionais.json': {'regionais': REGIONS}, 'custom.json': {'old': []},
                     'output/dashboard_admins_cache.json': {'dispositivos': {}},
                     'output/dashboard_firewalls_cache.json': {'firewalls_por_regional': {}}}
            for name, payload in files.items():
                (root / name).write_text(json.dumps(payload), encoding='utf-8')
            before = {name: (root / name).read_bytes() for name in files}
            with patch.object(module, '_contacts_from_workbook', return_value={'situacao': 'lido'}) as contacts:
                report = module.audit_sources(root)
                self.assertEqual(report['fontes']['monitor_admins']['baseline_dispositivos'], 1)
                contacts.assert_called_once_with(root / 'external.xlsx', 'Contacts', REGIONS, unresolved=False)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in files})

    def test_unresolved_admin_details_only_export_device_identifiers(self):
        cache = {'dispositivos': {'DEVICE_01': {'nome': 'FGT_UNKNOWN', 'tipo': 'fortigate',
                'admins': ['ACCOUNT_PRIVATE'], 'motivo': 'SECRET_PRIVATE'}}}
        baseline = {'DEVICE_01': ['APPROVED_PRIVATE'], 'DEVICE_OLD': ['APPROVED_PRIVATE']}
        firewalls = {'firewalls_por_regional': {}}
        default = module.audit_admins(cache, baseline, firewalls, REGIONS)
        self.assertNotIn('pendencias_identidade', default)
        result = module.audit_admins(cache, baseline, firewalls, REGIONS, unresolved=True)
        self.assertEqual(result['pendencias_identidade']['chaves_baseline_fora_do_cache'], ['DEVICE_OLD'])
        self.assertEqual(result['pendencias_identidade']['equipamentos_sem_vinculo_unico'][0]['nome_dispositivo'], 'FGT_UNKNOWN')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_unresolved_contact_details_exclude_people_and_resolved_rows(self):
        records = [{'NOME_REGIONAL': 'V001_UNKNOWN', 'NOME_REG_FORTI': 'REPORT_UNKNOWN',
                    'NOME_GERENTE': 'PERSON_PRIVATE', 'EMAIL_GERENTE': 'EMAIL_PRIVATE@example.test'},
                   {'NOME_REGIONAL': 'V021_BAHIA', 'NOME_DIRETOR_1': 'PERSON_PRIVATE'}]
        self.assertNotIn('rotulos_sem_vinculo_unico', module.audit_contacts(records, REGIONS))
        result = module.audit_contacts(records, REGIONS, unresolved=True)
        self.assertEqual(result['rotulos_sem_vinculo_unico'], [
            {'rotulo_regional_sla': 'V001_UNKNOWN', 'rotulo_fortianalyzer': 'REPORT_UNKNOWN',
             'motivo': 'nao_encontrado', 'candidatos_regionais': []}])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_unresolved_keeps_all_ambiguous_candidates_without_approving(self):
        regions = {'REG_ONE': {'nome': 'Same'}, 'REG_TWO': {'nome': 'Same'}}
        result = module.audit_contacts([{'NOME_REGIONAL': 'Same'}], regions, unresolved=True)
        self.assertEqual(result['rotulos_sem_vinculo_unico'][0]['candidatos_regionais'], ['REG_ONE', 'REG_TWO'])
        self.assertFalse(result['vinculos_aprovados_pela_auditoria'])

    def test_confirmed_sla_aliases_have_unique_candidates_without_person_data(self):
        from services.sla_contact_matching import VERIFIED_ALIASES
        regions = {code: {'nome': code} for code, _ in VERIFIED_ALIASES.values()}
        regions['REG_GRSA_MACAE'] = {'nome': 'GRSA Macae'}
        rows = [{'NOME_REGIONAL': label, 'NOME_REG_FORTI': report}
                for label, (code, report) in VERIFIED_ALIASES.items()]
        report = module.audit_contacts(rows, regions, unresolved=True)
        self.assertEqual(report['candidatos_regionais_por_codigo_ou_nome_sem_aproximacao'], {'candidato_unico': 4})
        self.assertEqual(report['por_regra_vinculo_regional'], {'alias_sla_verificado': 4})
        self.assertEqual(report['rotulos_sem_vinculo_unico'], [])
        self.assertFalse(report['vinculos_aprovados_pela_auditoria'])

    def test_alias_report_mismatch_or_missing_target_remains_unresolved(self):
        row = {'NOME_REGIONAL': 'V049_REGIONAL_MACAE01', 'NOME_REG_FORTI': 'REPORT DE SEGURANCA-FGT_GRSA_MACAE'}
        report = module.audit_contacts([row], {'REG_MACAE': {}, 'REG_GRSA_MACAE': {}}, unresolved=True)
        self.assertEqual(report['rotulos_sem_vinculo_unico'][0]['motivo'], 'rotulo_fortianalyzer_divergente_do_alias')
        row['NOME_REG_FORTI'] = 'REPORT DE SEGURANCA-FTG_REGMACAE01'
        report = module.audit_contacts([row], {'REG_GRSA_MACAE': {}}, unresolved=True)
        self.assertEqual(report['rotulos_sem_vinculo_unico'][0]['motivo'], 'destino_alias_ausente')

    def test_aliases_do_not_modify_general_unifi_rules(self):
        from services.sla_contact_matching import resolve_sla_contact_regional
        regions = {'REG_MACAE': {}, 'REG_GRSA_MACAE': {}}
        code, reason, _ = resolve_sla_contact_regional(regions, 'V049_REGIONAL_MACAE01',
                                                      'REPORT DE SEGURANCA-FTG_REGMACAE01')
        self.assertEqual(code, 'REG_MACAE')
        self.assertEqual(reason, 'alias_sla_verificado')
        self.assertIsNone(resolve_sla_contact_regional(regions, 'V999_REGIONAL_MACAE01',
                                                     'REPORT DE SEGURANCA-FTG_REGMACAE01')[0])


if __name__ == '__main__':
    unittest.main()
