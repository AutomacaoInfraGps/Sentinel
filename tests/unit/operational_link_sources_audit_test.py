import json
from pathlib import Path
import tempfile
import unittest

from scripts.database.audit_link_sources import audit_records, audit_sources, _time_kind, _ip_kind


class LinkSourcesAuditTest(unittest.TestCase):
    def test_never_exports_operational_values_secrets_or_arbitrary_keys(self):
        result = audit_records([('REG_PRIVATE', {'id': 'PRIVATE_ID', 'nome': 'PRIVATE_HOST',
            'fortigate_host': 'PRIVATE_IP', 'interface_monitorada': 'PRIVATE_INTERFACE',
            'password': 'PRIVATE_PASSWORD', 'origem_sync': 'PRIVATE_SOURCE',
            'status': 'PRIVATE_STATUS', 'modo_verificacao': 'PRIVATE_MODE'})], {'REG_PRIVATE'})
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(result['campos_presentes']['id'], 1)
        self.assertEqual(result['por_status'], {'outro_ou_ausente': 1})

    def test_identity_is_scoped_to_regional_not_global_id_or_interface_name(self):
        records = [('REG_A', {'id': '1', 'interface_monitorada': 'wan1'}),
                   ('REG_B', {'id': '1', 'interface_monitorada': 'wan1'})]
        report = audit_records(records, {'REG_A', 'REG_B'})
        self.assertEqual(report['ids_reutilizados_entre_regionais'], 1)
        self.assertEqual(report['identidades_regional_id_repetidas'], 0)
        self.assertEqual(report['interfaces_repetidas_na_regional'], 0)
        records.append(records[0])
        self.assertEqual(audit_records(records, {'REG_A'})['identidades_regional_id_repetidas'], 1)

    def test_endpoint_interface_requires_real_fields_and_does_not_guess_from_name(self):
        report = audit_records([('REG_A', {'nome': 'wan1', 'fortigate_host': '192.0.2.1'}),
                                ('REG_A', {'interface_monitorada': 'wan2', 'fortigate_host': '192.0.2.1'})],
                               {'REG_A'})
        self.assertEqual(report['identidades_regional_endpoint_interface_completas'], 1)

    def test_time_and_ip_formats_are_classified_without_timezone_inference(self):
        self.assertEqual(_time_kind('2026-11-16T16:00:00'), 'sem_fuso')
        self.assertEqual(_time_kind('2026-11-16T19:00:00Z'), 'com_fuso')
        self.assertEqual(_time_kind('16:00:00'), 'outro_formato')
        self.assertEqual(_time_kind(None), 'ausente')
        self.assertEqual(_ip_kind('192.0.2.1'), 'endereco_ip')
        self.assertEqual(_ip_kind('192.0.2.1/24'), 'ip_com_prefixo')
        self.assertEqual(_ip_kind('PRIVATE'), 'outro_formato')

    def test_invalid_records_and_booleans_do_not_become_identifiers(self):
        report = audit_records([('REG_A', None), ('REG_B', {'id': True}),
                                ('REG_A', {'id': 0, 'packet_loss_percent': 0})], {'REG_A'})
        self.assertEqual(report['registros_invalidos'], 1)
        self.assertEqual(report['sem_vinculo_exato_ao_catalogo'], 1)
        self.assertEqual(report['identidades_regional_id_completas'], 1)
        self.assertEqual(report['campos_presentes']['packet_loss_percent'], 1)

    def test_verification_time_is_not_explicit_collection_time(self):
        report = audit_records([('REG_A', {'ultima_verificacao': '2026-11-16T16:00:00',
                                          'origem_sync': 'fallback_local'})], {'REG_A'})
        self.assertEqual(report['horarios_verificacao'], {'sem_fuso': 1})
        self.assertEqual(report['horarios_coleta_explicita'], {'ausente': 1})
        self.assertEqual(report['por_origem_sync'], {'fallback_local': 1})

    def test_catalog_lists_are_separate_including_missing_empty_and_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = {'regionais': {
                'REG_A': {'links': [{'id': '1'}], 'links_internet_auto': [{'id': '1'}]},
                'REG_B': {'links': [], 'links_internet_auto': []},
                'REG_C': {'links_internet_auto': {}}, 'REG_D': {}}}
            (root / 'estrutura_regionais.json').write_text(json.dumps(payload), encoding='utf-8')
            result = audit_sources(root)['fontes']['catalogo_regional']
            self.assertEqual(result['ids_em_ambas_listas_na_mesma_regional'], 1)
            self.assertEqual(result['links']['registros'], 1)
            self.assertEqual(result['links_internet_auto']['registros'], 1)
            self.assertEqual(result['links']['regionais_sem_lista'], 2)
            self.assertEqual(result['links_internet_auto']['listas_ou_regionais_invalidas'], 1)
            self.assertEqual(result['links_internet_auto']['regionais_com_lista_vazia'], 1)

    def test_map_uses_envelope_regional_and_keeps_unmapped_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'output').mkdir()
            (root / 'estrutura_regionais.json').write_text(
                json.dumps({'regionais': {'REG_A': {}}}), encoding='utf-8')
            (root / 'output/mapa_monitoramento_cache.json').write_text(json.dumps({
                'regionais': [{'codigo': 'REG_A', 'links': [{'id': '1', 'regional': 'WRONG'}]}],
                'unmapped': {'links': [{'id': '2', 'regional': 'REG_A'}]}}), encoding='utf-8')
            report = audit_sources(root)['fontes']['mapa_consolidado']
            self.assertEqual(report['registros'], 2)
            self.assertEqual(report['sem_vinculo_exato_ao_catalogo'], 1)

    def test_native_missing_files_and_duplicate_json_do_not_write_or_export_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'estrutura_regionais.json'
            target.write_text('{"PRIVATE":1,"PRIVATE":2}', encoding='utf-8')
            before = target.read_bytes()
            result = audit_sources(root)
            self.assertEqual(result['fontes']['catalogo_regional']['situacao'], 'ausente_ou_invalido')
            self.assertEqual(result['fontes']['estado_operacional']['situacao'], 'ausente')
            self.assertEqual(target.read_bytes(), before)
            self.assertNotIn('PRIVATE', json.dumps(result))

    def test_operational_group_is_checked_without_importing_web_or_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'output').mkdir()
            target = root / 'output/sentinel_operational_state.json'
            target.write_text(json.dumps({'groups': {'links': {'updated_at': '2026-11-16T16:00:00',
                'records': [{'regional': 'REG_X', 'id': '1', 'origem_sync': 'fortimanager_config+proxy_monitor'}]}}}),
                encoding='utf-8')
            report = audit_sources(root)['fontes']['estado_operacional']
            self.assertEqual(report['publicacao'], 'sem_fuso')
            self.assertEqual(report['sem_vinculo_exato_ao_catalogo'], 1)
            self.assertEqual(report['por_origem_sync'], {'fortimanager_config+proxy_monitor': 1})


if __name__ == '__main__':
    unittest.main()
