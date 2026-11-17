from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.database.audit_wlan_sources import audit_sources, audit_unifi_wlans


def network(**changes):
    return {'nome': 'SSID_PRIVATE', 'rede': 'NETWORK_PRIVATE', 'bandas': ['5 GHz'],
            'transmissao': ['AP_PRIVATE'], 'ativo': True, 'x_passphrase': 'SECRET_PRIVATE', **changes}


def payload():
    return {'timestamp': '2026-11-17T10:00:00',
            'controller': {'ip': 'IP_PRIVATE', 'porta': 8443, 'password': 'SECRET_PRIVATE'},
            'sites': [{'id': 'SITE_PRIVATE', 'nome': 'V021_BAHIA', 'coletado_em': '2026-11-17T13:00:00Z',
                       'coleta_aps_confirmada': True, 'redes_wifi': [network()]}]}


REGIONS = {'REG_BAHIA': {'nome': 'Bahia'}}


class WlanSourcesAuditTests(unittest.TestCase):
    def test_summary_does_not_export_names_credentials_or_mutate_source(self):
        source = payload()
        before = deepcopy(source)
        result = audit_unifi_wlans(source, REGIONS)
        self.assertEqual(before, source)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(result['registros_wifi'], 1)
        self.assertEqual(result['ids_wlan'], {'ausente': 1})
        self.assertEqual(result['por_ativo'], {'ativa': 1})
        self.assertEqual(result['regional_por_regras_unifi_sem_aproximacao'], {'identidade_normalizada_unica': 1})

    def test_ap_and_file_timestamps_do_not_become_wlan_evidence(self):
        result = audit_unifi_wlans(payload(), REGIONS)
        self.assertEqual(result['publicacao'], 'sem_fuso')
        self.assertEqual(result['coleta_wlan_por_site'], {'ausente': 1})
        self.assertEqual(result['coleta_explicita_por_rede'], {'ausente': 1})
        self.assertEqual(result['sites_com_coleta_wlan_confirmada'], 0)

    def test_identity_is_site_wlan_id_not_ssid(self):
        source = payload()
        source['sites'][0]['redes_wifi'] = [network(_id='id1'), network(_id='id2')]
        result = audit_unifi_wlans(source, REGIONS)
        self.assertEqual(result['redes_com_site_e_id_wlan'], 2)
        self.assertEqual(result['identidades_site_wlan_repetidas'], 0)
        self.assertEqual(result['nomes_repetidos_no_mesmo_site'], 1)
        source['sites'][0]['redes_wifi'][1]['_id'] = 'id1'
        self.assertEqual(audit_unifi_wlans(source, REGIONS)['identidades_site_wlan_repetidas'], 1)

    def test_same_id_and_ssid_in_different_sites_are_not_identity_duplicates(self):
        source = payload()
        source['sites'][0]['redes_wifi'][0]['wlan_id'] = 'id1'
        second = deepcopy(source['sites'][0])
        second['id'] = 'site2'
        source['sites'].append(second)
        result = audit_unifi_wlans(source, REGIONS)
        self.assertEqual(result['identidades_site_wlan_repetidas'], 0)
        self.assertEqual(result['nomes_presentes_em_mais_de_um_site'], 1)
        self.assertEqual(result['redes_com_site_e_id_wlan'], 2)

    def test_case_variants_are_not_silently_merged(self):
        source = payload()
        source['sites'][0]['redes_wifi'] = [network(nome='Guest'), network(nome='guest')]
        result = audit_unifi_wlans(source, REGIONS)
        self.assertEqual(result['nomes_repetidos_no_mesmo_site'], 0)
        self.assertEqual(result['nomes_repetidos_no_mesmo_site_ignorando_maiusculas'], 1)
        self.assertEqual(result['registros_wifi'], 2)

    def test_invalid_or_conflicting_ids_and_duplicate_site_are_not_complete_identity(self):
        for values in ({'id': True}, {'id': []}, {'id': 'a', '_id': 'b'}, {'id': '  '}):
            source = payload()
            source['sites'][0]['redes_wifi'][0].update(values)
            result = audit_unifi_wlans(source, REGIONS)
            self.assertEqual(result['ids_wlan'], {'invalido_ou_conflitante': 1})
            self.assertEqual(result['redes_com_site_e_id_wlan'], 0)
        source = payload()
        source['sites'][0]['redes_wifi'][0]['id'] = 'id1'
        source['sites'].append(deepcopy(source['sites'][0]))
        result = audit_unifi_wlans(source, REGIONS)
        self.assertEqual(result['ids_de_site_repetidos'], 1)
        self.assertEqual(result['redes_com_site_e_id_wlan'], 0)

    def test_missing_empty_invalid_lists_and_records_stay_distinct(self):
        source = payload()
        source['sites'].extend([{'id': 'a'}, {'id': 'b', 'redes_wifi': []},
                                {'id': 'c', 'redes_wifi': {}}, None,
                                {'redes_wifi': [None, 'PRIVATE']}])
        result = audit_unifi_wlans(source, REGIONS)
        self.assertEqual(result['sites_sem_lista_wifi'], 1)
        self.assertEqual(result['sites_com_lista_wifi_vazia'], 1)
        self.assertEqual(result['listas_wifi_invalidas'], 1)
        self.assertEqual(result['sites_invalidos'], 1)
        self.assertEqual(result['registros_wifi_invalidos'], 2)
        self.assertEqual(result['sites_sem_id'], 1)

    def test_source_status_and_transmission_are_not_inferred(self):
        source = payload()
        source['sites'][0]['redes_wifi'] = [network(ativo=False, origem='PRIVATE'),
                                            network(ativo='false', bandas='5g', transmissao=[{}])]
        result = audit_unifi_wlans(source, REGIONS)
        self.assertEqual(result['por_ativo'], {'inativa': 1, 'ausente_ou_nao_booleano': 1})
        self.assertEqual(result['por_origem_declarada'], {'outro_ou_ausente': 2})
        self.assertEqual(result['listas_bandas_ausentes_ou_invalidas'], 1)
        self.assertEqual(result['listas_transmissao_ausentes_ou_invalidas'], 1)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_fixed_files_duplicate_keys_and_invalid_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'estrutura_regionais.json').write_text(json.dumps({'regionais': REGIONS}), encoding='utf-8')
            (root / 'data/unifi.json').write_text(json.dumps(payload()), encoding='utf-8')
            self.assertEqual(audit_sources(root)['fontes']['unifi_nativo']['registros_wifi'], 1)
            (root / 'data/unifi.json').write_text('{"sites":[],"sites":[]}', encoding='utf-8')
            self.assertEqual(audit_sources(root)['fontes']['unifi_nativo']['situacao'], 'ausente_ou_invalido')
            (root / 'estrutura_regionais.json').write_text('{}', encoding='utf-8')
            self.assertEqual(audit_sources(root)['fontes']['catalogo_regional']['situacao'], 'ausente_ou_invalido')

    def test_separate_configuration_is_audited_without_changing_display_counts(self):
        source = payload()
        source['sites'][0].update({
            'coleta_wlans_confirmada': True, 'wlans_coletadas_em': '2026-11-17T13:00:00Z',
            'wlans_situacao': 'confirmada',
            'wlans_configuradas': [network(wlan_id='a', origem='configuracao_unifi', coletado_em='2026-11-17T13:00:00Z'),
                                   network(wlan_id='b', origem='configuracao_unifi', coletado_em='2026-11-17T13:00:00Z')],
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'estrutura_regionais.json').write_text(json.dumps({'regionais': REGIONS}), encoding='utf-8')
            (root / 'data/unifi.json').write_text(json.dumps(source), encoding='utf-8')
            result = audit_sources(root)
        self.assertEqual(result['fontes']['unifi_nativo']['registros_wifi'], 1)
        separate = result['fontes']['unifi_configuracao_separada']
        self.assertEqual(separate['registros_wifi'], 2)
        self.assertEqual(separate['ids_wlan'], {'presente': 2})
        self.assertEqual(separate['coleta_explicita_por_rede'], {'com_fuso': 2})
        self.assertEqual(separate['sites_por_situacao'], {'confirmada': 1})
        self.assertNotIn('PRIVATE', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
