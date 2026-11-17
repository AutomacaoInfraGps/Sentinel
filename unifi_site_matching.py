"""UniFi site naming rules shared by the map and read-only migration audit."""

import re
import unicodedata


UNIFI_SITE_ALIASES = {
    'BH': 'REG_REGIONAL BELO HORIZONTE',
    'PARA': 'REG_PARA',
    'ORMEC_PARA': 'REG_ORMEC_PARA',
    'REGIONAL_BH': 'REG_REGIONAL BELO HORIZONTE',
    'SAO_JOSE_DOS_CAMPOS': 'REG_SJC',
    'SANTO_ANDRE': 'REG_ABC',
    'REGALAGOAS': 'REG_ALAGOAS',
    'REGMARANHAO': 'REG_MARANHAO',
    'REG_S_LEOPOLDO': 'REG_SAO_LEOPOLDO',
    'S_LEOPOLDO': 'REG_SAO_LEOPOLDO',
    'S_LEOPOLDO_2': 'REG_LEOPOLDO_B2',
    'TLSV_PORTO_ALEGRE': 'REG_TLSV_POA',
    'TRADE_POP': None,
    'TAGG': None,
    'CONTROL_MACEIO': 'REG_CONTROL_MCO',
    'CEARA1': 'REG_CEARA',
    'MACAE_MARFOOD': 'REG_MACAE',
}


def normalize_regional_token(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'[^A-Z0-9]+', '_', text.upper().replace('&', 'E'))
    text = re.sub(r'_+', '_', text).strip('_')
    if text.startswith('REG_'):
        text = text[4:]
    for word in ('REGIONAL_', '_MATRIZ', '_REGIONAL', '_SWITCH'):
        text = text.replace(word, '_')
    return re.sub(r'_+', '_', text).strip('_')


def normalize_unifi_site(value):
    token = re.sub(r'^V\d+_', '', normalize_regional_token(value))
    return normalize_regional_token(token)


def resolve_unifi_site_for_catalog(regionals, site_name):
    """Return a code and fixed reason; never select the first ambiguous match."""
    target = normalize_unifi_site(site_name)
    if not target:
        return None, 'sem_referencia'
    if target in UNIFI_SITE_ALIASES:
        code = UNIFI_SITE_ALIASES[target]
        if code is None:
            return None, 'alias_sem_regional'
        return (code, 'alias_explicito') if code in regionals else (None, 'destino_alias_ausente')
    matches = set()
    for code, entry in regionals.items():
        candidates = {normalize_regional_token(value) for value in
                      (code, entry.get('nome'), entry.get('descricao'))}
        candidates = {value[4:] if value.startswith('REG_') else value for value in candidates if value}
        if target in candidates:
            matches.add(code)
    if len(matches) == 1:
        return next(iter(matches)), 'identidade_normalizada_unica'
    return None, 'ambiguo' if matches else 'nao_encontrado'
