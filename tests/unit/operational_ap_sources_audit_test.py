import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.database.audit_ap_sources import _mac, _time_kind, audit_sources, audit_unifi


class ApSourcesAuditTests(unittest.TestCase):
    def payload(self):
        return {
            'timestamp': '2026-11-17T08:00:00',
            'controller': {'ip': 'CONTROLLER_PRIVATE', 'porta': 8443, 'password': 'SECRET_MARKER'},
            'sites': [{'id': 'SITE_PRIVATE', 'nome': 'Regional A'}],
            'aps': [{'nome': 'AP_PRIVATE', 'mac': '00:11:22:33:44:55', 'ip': '192.0.2.1',
                     'site': 'Regional A', 'status': 'online', 'password': 'SECRET_MARKER'}],
        }

    def test_identity_coverage_without_export_or_mutation(self):
        payload = self.payload()
        before = copy.deepcopy(payload)
        result = audit_unifi(payload, {'REG_A': {'nome': 'Regional A'}})
        self.assertEqual(result['aps_com_site_e_mac_identificados'], 1)
        self.assertEqual(result['regional_por_texto_exato_sem_alias'], {'exato_unico': 1})
        self.assertEqual(result['publicacao'], 'sem_fuso')
        self.assertEqual(result['coleta_explicita_por_ap'], {'ausente': 1})
        for value in ('SECRET_MARKER', 'CONTROLLER_PRIVATE', 'SITE_PRIVATE', 'AP_PRIVATE', '192.0.2.1'):
            self.assertNotIn(value, json.dumps(result))
        self.assertEqual(before, payload)

    def test_mac_formats_and_invalid_values(self):
        for value in ('00:11:22:AA:BB:CC', '00-11-22-aa-bb-cc', '001122aabbcc'):
            self.assertEqual(_mac(value), '001122aabbcc')
        for value in (None, [], 5, 'garbage', '0:11:22:33:44:55', '00:00:00:00:00:00', 'ffffffffffff'):
            self.assertIsNone(_mac(value))

    def test_duplicate_labels_do_not_guess_site(self):
        payload = self.payload()
        payload['sites'].append({'id': 'second', 'nome': 'Regional A'})
        result = audit_unifi(payload, {})
        self.assertEqual(result['vinculo_ap_site'], {'nome_ambiguo': 1})
        self.assertEqual(result['aps_com_site_e_mac_identificados'], 0)

    def test_duplicate_and_cross_site_mac(self):
        payload = self.payload()
        payload['aps'].append(copy.deepcopy(payload['aps'][0]))
        result = audit_unifi(payload, {})
        self.assertEqual(result['macs_repetidos_na_controladora'], 1)
        self.assertEqual(result['identidades_site_mac_repetidas'], 1)
        payload['sites'].append({'id': 'second', 'nome': 'Second'})
        payload['aps'][1]['site'] = 'Second'
        result = audit_unifi(payload, {})
        self.assertEqual(result['macs_repetidos_na_controladora'], 1)
        self.assertEqual(result['identidades_site_mac_repetidas'], 0)

    def test_explicit_site_conflict_and_duplicate_id(self):
        payload = self.payload()
        payload['aps'][0]['site_id'] = 'wrong'
        self.assertEqual(audit_unifi(payload, {})['aps_com_site_e_mac_identificados'], 0)
        payload['aps'][0]['site_id'] = 'SITE_PRIVATE'
        payload['sites'].append({'id': 'SITE_PRIVATE', 'nome': 'Other'})
        self.assertEqual(audit_unifi(payload, {})['aps_com_site_e_mac_identificados'], 0)

    def test_regional_ambiguity_no_fuzzy_or_first_match(self):
        result = audit_unifi(self.payload(), {'A': {'nome': 'Regional A'}, 'B': {'nome': 'Regional A'}})
        self.assertEqual(result['regional_por_texto_exato_sem_alias'], {'ambiguo': 1})
        result = audit_unifi(self.payload(), {'A': {'nome': 'Regional'}})
        self.assertEqual(result['regional_por_texto_exato_sem_alias'], {'sem_correspondencia_exata': 1})

    def test_shared_unifi_rules_count_aps_and_sites_separately(self):
        payload = self.payload()
        payload['sites'][0]['nome'] = 'V021_SANTO_ANDRE'
        payload['aps'][0]['site'] = 'V021_SANTO_ANDRE'
        payload['aps'].append(copy.deepcopy(payload['aps'][0]))
        result = audit_unifi(payload, {'REG_ABC': {}})
        self.assertEqual(result['regional_por_texto_exato_sem_alias'], {'sem_correspondencia_exata': 2})
        self.assertEqual(result['regional_por_regras_unifi_sem_aproximacao'], {'alias_explicito': 2})
        self.assertEqual(result['sites_por_regras_unifi_sem_aproximacao'], {'alias_explicito': 1})
        self.assertEqual(audit_unifi(payload, {})['regional_por_regras_unifi_sem_aproximacao'],
                         {'destino_alias_ausente': 2})

    def test_unknown_status_is_redacted_and_invalid_records_counted(self):
        payload = self.payload()
        payload['aps'][0]['status'] = 'SECRET_MARKER'
        payload['aps'].extend([None, 'SECRET_MARKER'])
        payload['sites'].append(None)
        result = audit_unifi(payload, {})
        self.assertEqual(result['cobertura']['registros_invalidos'], 2)
        self.assertEqual(result['sites_invalidos'], 1)
        self.assertNotIn('SECRET_MARKER', json.dumps(result))

    def test_timestamp_not_inferred_from_publication(self):
        self.assertEqual(_time_kind(1234), 'invalido_ou_nao_iso')
        self.assertEqual(_time_kind('2026-11-17'), 'invalido_ou_nao_iso')
        self.assertEqual(_time_kind('2026-11-17T11:00:00Z'), 'com_fuso')
        self.assertEqual(_time_kind('2026-99-99T11:00:00'), 'invalido_ou_nao_iso')

    def test_fixed_files_and_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'estrutura_regionais.json').write_text('{"regionais":{"A":{}}}', encoding='utf-8')
            (root / 'data/unifi.json').write_text(json.dumps(self.payload()), encoding='utf-8')
            result = audit_sources(root)
            self.assertEqual(result['fontes']['unifi_nativo']['aps'], 1)
            (root / 'data/unifi.json').write_text('{"aps":[],"aps":[],"sites":[]}', encoding='utf-8')
            self.assertEqual(audit_sources(root)['fontes']['unifi_nativo']['situacao'], 'ausente_ou_invalido')


if __name__ == '__main__':
    unittest.main()
