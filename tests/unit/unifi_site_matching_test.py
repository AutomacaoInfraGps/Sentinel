import ast
from pathlib import Path
import re
import unicodedata
import unittest

from unifi_site_matching import (
    UNIFI_SITE_ALIASES, normalize_regional_token, normalize_unifi_site,
    resolve_unifi_site_for_catalog,
)


class UnifiSiteMatchingTests(unittest.TestCase):
    def test_aliases_and_prefix(self):
        for value in ('V021_SANTO_ANDRE', 'Santo Andre', 'REG_SANTO_ANDRE'):
            self.assertEqual(resolve_unifi_site_for_catalog({'REG_ABC': {}}, value),
                             ('REG_ABC', 'alias_explicito'))
        self.assertEqual(normalize_unifi_site('V021_BAHIA'), 'BAHIA')

    def test_alias_target_must_exist(self):
        self.assertEqual(resolve_unifi_site_for_catalog({}, 'V021_SANTO_ANDRE'),
                         (None, 'destino_alias_ausente'))

    def test_explicit_unassigned_site_stays_unassigned(self):
        self.assertEqual(resolve_unifi_site_for_catalog({'REG_TAGG': {}}, 'TAGG'),
                         (None, 'alias_sem_regional'))

    def test_normalized_unique_and_ambiguous(self):
        self.assertEqual(resolve_unifi_site_for_catalog({'REG_BAHIA': {}}, 'V021_Bahia'),
                         ('REG_BAHIA', 'identidade_normalizada_unica'))
        for entries in ({'A': {'nome': 'Bahia'}, 'B': {'nome': 'Bahia'}},
                        {'B': {'nome': 'Bahia'}, 'A': {'nome': 'Bahia'}}):
            self.assertEqual(resolve_unifi_site_for_catalog(entries, 'V021_Bahia'), (None, 'ambiguo'))

    def test_no_partial_match_or_empty_description_match(self):
        self.assertEqual(resolve_unifi_site_for_catalog({'REG_BAHIA': {}}, 'V021_BAHIA_NOVA'),
                         (None, 'nao_encontrado'))
        self.assertEqual(resolve_unifi_site_for_catalog({'REG_BAHIA': {}}, None), (None, 'sem_referencia'))

    def test_normalization_parity_with_map(self):
        source = Path(__file__).resolve().parents[2] / 'web_config.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        names = {'_mapa_normalizar_token', '_mapa_normalizar_site_unifi', '_mapa_encontrar_regional_unifi'}
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        namespace = {'re': re, 'unicodedata': unicodedata, 'normalize_unifi_site': normalize_unifi_site,
                     '_MAPA_UNIFI_SITE_ALIAS': UNIFI_SITE_ALIASES}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)
        for value in (None, '', 'V001_Bahia', 'REG_MATRIZ_SWITCH', 'REGIONAL_BH',
                      'S\u00e3o Jos\u00e9 dos Campos', 'A & B', 'REG_REGIONAL BELO HORIZONTE', 'REG_REG_ALAGOAS'):
            self.assertEqual(namespace['_mapa_normalizar_token'](value), normalize_regional_token(value))
            old_site = namespace['_mapa_normalizar_token'](
                re.sub(r'^V\d+_', '', namespace['_mapa_normalizar_token'](value)))
            self.assertEqual(old_site, normalize_unifi_site(value))
        regionals = {'REG_ABC': {}, 'REG_BAHIA': {}, 'REG_TLSV_POA': {}}
        for value in ('V021_SANTO_ANDRE', 'V021_BAHIA', 'TLSV_PORTO_ALEGRE', 'TAGG', 'unknown'):
            self.assertEqual(namespace['_mapa_encontrar_regional_unifi'](regionals, value),
                             resolve_unifi_site_for_catalog(regionals, value)[0])


if __name__ == '__main__':
    unittest.main()
