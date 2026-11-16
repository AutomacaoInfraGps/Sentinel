import json
from pathlib import Path
import tempfile
import unittest

from scripts.database.audit_vpn_sources import audit_records, audit_sources, time_kind


class VPNSourcesAuditTest(unittest.TestCase):
    def test_does_not_export_private_values(self):
        records = [{'tunel': 'PRIVATE_TUNNEL', 'device': 'PRIVATE_DEVICE',
                    'vdom': 'PRIVATE_VDOM', 'regional': 'PRIVATE_REGION',
                    'status': 'PRIVATE_STATUS', 'password': 'PRIVATE_SECRET'}]
        report = audit_records(records, regional_codes={'PRIVATE_REGION'})
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertEqual(report['identidade_dispositivo_vdom_tunel_completa'], 1)

    def test_collection_time_and_source_remain_distinct_from_display_time(self):
        report = audit_records([{'ultima_verificacao': '15:00:00',
                                 'coletado_em': '2026-11-16T18:00:00+00:00',
                                 'vpn_source': 'fortigate_ssh'},
                                {'vpn_source': 'PRIVATE_SOURCE'}])
        self.assertEqual(report['horarios_coleta'], {'com_fuso': 1, 'ausente': 1})
        self.assertEqual(report['por_fonte_coleta'],
                         {'fortigate_ssh': 1, 'outro_ou_ausente': 1})
        self.assertEqual(report['horarios_observacao']['somente_hora_sem_data'], 1)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_time_only_is_not_assigned_today(self):
        self.assertEqual(time_kind('23:59:59'), 'somente_hora_sem_data')
        self.assertEqual(time_kind('25:00:00'), 'invalido')
        self.assertEqual(time_kind('2026-11-16T15:00:00'), 'sem_fuso')
        self.assertEqual(time_kind('2026-11-16T18:00:00Z'), 'com_fuso')
        self.assertEqual(time_kind('2026-11-16'), 'invalido')
        self.assertEqual(time_kind(None), 'ausente')
        self.assertEqual(time_kind(123), 'invalido')

    def test_tunnel_name_alone_does_not_establish_identity(self):
        records = [{'tunel': 'T1', 'device': 'D1', 'vdom': 'root'},
                   {'tunel': 'T1', 'device': 'D2', 'vdom': 'root'},
                   {'tunel': 'T1'}]
        result = audit_records(records)
        self.assertEqual(result['nomes_de_tunel_repetidos'], 1)
        self.assertEqual(result['identidades_compostas_repetidas'], 0)
        self.assertEqual(result['identidade_dispositivo_vdom_tunel_completa'], 2)

    def test_duplicate_composite_and_invalid_records(self):
        record = {'tunel': 'T1', 'device': 'D1', 'vdom': 'root', 'regional': 'REG_A'}
        result = audit_records([record, record, None], regional_codes={'REG_A'})
        self.assertEqual(result['identidades_compostas_repetidas'], 1)
        self.assertEqual(result['registros_invalidos'], 1)
        self.assertEqual(result['sem_vinculo_exato_ao_catalogo'], 0)

    def test_does_not_infer_scope_from_tunnel_name(self):
        result = audit_records([{'tunel': 'REG_A', 'regional': 'A'},
                                {'tunel': 'REG_A', 'regional': 'SEM_REGIONAL'}],
                               regional_codes={'REG_A'})
        self.assertEqual(result['sem_vinculo_exato_ao_catalogo'], 2)

    def test_missing_files_and_invalid_json_do_not_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'output/sentinel_operational_state.json'
            target.parent.mkdir()
            target.write_text('{PRIVATE_BROKEN', encoding='utf-8')
            before = target.read_bytes()
            report = audit_sources(root)
            self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertEqual(report['fontes']['estado_operacional']['situacao'],
                             'leitura_ou_estrutura_invalida')
            self.assertEqual(report['fontes']['mapa_consolidado']['situacao'], 'ausente')
            self.assertEqual(target.read_bytes(), before)

    def test_group_publication_is_not_individual_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'output').mkdir()
            (root / 'estrutura_regionais.json').write_text(
                json.dumps({'regionais': {'REG_A': {}}}), encoding='utf-8')
            (root / 'output/sentinel_operational_state.json').write_text(json.dumps({
                'groups': {'vpns': {'updated_at': '2026-11-16T15:00:00-03:00',
                                   'records': [{'regional': 'REG_A', 'tunel': 'T1',
                                                'ultima_verificacao': '14:55:00'}]}}}),
                encoding='utf-8')
            report = audit_sources(root)['fontes']['estado_operacional']
            self.assertEqual(report['publicacao'], 'com_fuso')
            self.assertEqual(report['horarios_observacao'], {'somente_hora_sem_data': 1})
            self.assertEqual(report['identidade_dispositivo_vdom_tunel_completa'], 0)

    def test_map_uses_explicit_envelope_scope_and_includes_unmapped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'output').mkdir()
            (root / 'estrutura_regionais.json').write_text(
                json.dumps({'regionais': {'REG_A': {}}}), encoding='utf-8')
            (root / 'output/mapa_monitoramento_cache.json').write_text(json.dumps({
                'regionais': [{'codigo': 'REG_A', 'vpns': [{'tunel': 'T1'}]}],
                'unmapped': {'vpns': [{'tunel': 'T2'}]}}), encoding='utf-8')
            report = audit_sources(root)['fontes']['mapa_consolidado']
            self.assertEqual(report['registros'], 2)
            self.assertEqual(report['sem_vinculo_exato_ao_catalogo'], 1)


if __name__ == '__main__':
    unittest.main()
