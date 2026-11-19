import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.database.audit_ap_radio_sources import audit_radio, audit_sources


class ApRadioSourcesAuditTests(unittest.TestCase):
    def payload(self):
        return {
            'timestamp': '2026-11-19T12:00:00',
            'password': 'PRIVATE_SECRET',
            'aps': [{'site': 'PRIVATE_SITE', 'nome': 'PRIVATE_AP',
                     'mac': '00:11:22:33:44:55', 'site_id': 'PRIVATE_ID'}],
            'interferencia_5ghz_por_site': {'PRIVATE_SITE': [{
                'canal': 36, 'qtd_aps': 1, 'aps': [{
                    'nome': 'PRIVATE_AP', 'cu_total': 50, 'cu_self_tx': 10,
                    'cu_self_rx': 20, 'tx_retry': 0, 'risco': 'OK',
                }],
            }]},
        }

    def test_counts_without_export_mutation_or_inferred_measurement(self):
        payload = self.payload()
        original = copy.deepcopy(payload)
        result = audit_radio(payload)
        self.assertEqual(result['candidatos_por_site_nome'], {
            'candidato_unico_por_site_nome_sem_aprovacao': 1})
        self.assertEqual(result['coleta_explicita_por_registro_radio'], {'ausente': 1})
        self.assertEqual(result['metricas']['tx_retry']['zeros_sem_comprovacao_de_medicao'], 1)
        self.assertEqual(result['contagens']['com_mac_valido_no_registro_radio'], 0)
        for value in ('PRIVATE', '00:11:22:33:44:55'):
            self.assertNotIn(value, json.dumps(result))
        self.assertEqual(payload, original)

    def test_ambiguous_names_not_approved(self):
        payload = self.payload()
        payload['aps'].append(copy.deepcopy(payload['aps'][0]))
        self.assertEqual(audit_radio(payload)['candidatos_por_site_nome'], {'ambiguo_por_site_nome': 1})

    def test_missing_inventory_identity_and_unmatched_radio(self):
        payload = self.payload()
        payload['aps'][0]['mac'] = 'invalid'
        self.assertEqual(audit_radio(payload)['candidatos_por_site_nome'], {
            'inventario_sem_mac_ou_site_id_validos': 1})
        payload['aps'][0]['nome'] = 'other'
        result = audit_radio(payload)
        self.assertEqual(result['candidatos_por_site_nome'], {'sem_correspondencia': 1})
        self.assertEqual(result['identidades_inventario_sem_linha_radio'], 1)

    def test_invalid_numbers_and_empty_projection(self):
        for value in (True, -1, 101, 10**400, '20', float('inf'), float('nan'), [], {}):
            payload = self.payload()
            payload['interferencia_5ghz_por_site']['PRIVATE_SITE'][0]['aps'][0]['cu_total'] = value
            self.assertEqual(audit_radio(payload)['metricas']['cu_total'], {'invalido': 1})
        payload['interferencia_5ghz_por_site'] = {}
        result = audit_radio(payload)
        self.assertEqual(result['identidades_inventario_sem_linha_radio'], 1)
        self.assertEqual(result['contagens'], {})

    def test_invalid_structures_and_fixed_risk_categories(self):
        payload = self.payload()
        groups = payload['interferencia_5ghz_por_site']['PRIVATE_SITE']
        groups[0]['qtd_aps'] = 9
        groups[0]['canal'] = True
        groups[0]['aps'][0].update(risco='PRIVATE_SECRET', cu_self_tx=90)
        groups[0]['aps'].append(None)
        groups.extend([None, {'aps': None}])
        payload['aps'].extend([None, {}])
        result = audit_radio(payload)
        self.assertEqual(result['contagens']['quantidades_declaradas_divergentes'], 1)
        self.assertEqual(result['contagens']['registros_radio_invalidos'], 1)
        self.assertEqual(result['contagens']['tx_rx_proprios_maiores_que_total'], 1)
        self.assertEqual(result['riscos_declarados_sem_recalculo'], {'ausente_ou_outro': 1})
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_read_only_same_bytes_hash_and_safe_errors(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            path = root / 'data/unifi.json'
            raw = json.dumps(self.payload()).encode('utf-8-sig')
            path.write_bytes(raw)
            result = audit_sources(root)
            self.assertEqual(result['fontes']['projecao_radio_unifi']['sha256_arquivo'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse(result['postgresql_acessado'])
            self.assertFalse(result['coletor_executado'])
            self.assertNotIn('PRIVATE', json.dumps(result))
            for raw in (b'{"aps": [], "aps": []}', b'{}', b'[]', b'PRIVATE_SECRET'):
                path.write_bytes(raw)
                self.assertEqual(audit_sources(root)['fontes']['projecao_radio_unifi'], {'situacao': 'ausente_ou_invalido'})


if __name__ == '__main__':
    unittest.main()
