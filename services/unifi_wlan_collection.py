"""Safe configured-WLAN evidence, independent of the SSID presentation merge."""

from datetime import datetime, timezone
import re


def confirmed_wlan_receipt(response, payload):
    response.raise_for_status()
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if payload.get('error') or payload.get('errors') or payload.get('success') is False:
            raise ValueError('Consulta WLAN retornou erro.')
        meta = payload.get('meta')
        if meta is not None and (not isinstance(meta, dict) or meta.get('rc') != 'ok'):
            raise ValueError('Consulta WLAN nao confirmada.')
        lists = [payload[key] for key in ('data', 'items', 'results') if isinstance(payload.get(key), list)]
        if len(lists) != 1:
            raise ValueError('Envelope WLAN invalido ou ambiguo.')
        items = lists[0]
    else:
        raise ValueError('Resposta WLAN invalida.')
    if any(not isinstance(item, dict) for item in items):
        raise ValueError('Lista WLAN invalida.')
    return {'coletado_em': datetime.now(timezone.utc).isoformat(), 'origem': 'configuracao_unifi'}


def _identifier(value, required=False):
    if value is None or value == '':
        if required:
            raise ValueError('Identidade WLAN ausente.')
        return None
    if (not isinstance(value, str) or len(value) > 120
            or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value)):
        raise ValueError('Identidade WLAN invalida.')
    return value


def _collection_time(value):
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('Coleta WLAN sem horario completo.')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('Coleta WLAN sem fuso.')
    return parsed.astimezone(timezone.utc).isoformat()


def configured_wlan_catalog(wlans, receipt):
    empty = {'coleta_wlans_confirmada': False, 'wlans_coletadas_em': None,
             'wlans_configuradas': [], 'wlans_situacao': 'sem_confirmacao_api'}
    if not isinstance(receipt, dict) or receipt.get('origem') != 'configuracao_unifi':
        return empty
    try:
        at = _collection_time(receipt.get('coletado_em'))
        if not isinstance(wlans, list):
            raise ValueError('Lista WLAN invalida.')
        result, identities = [], set()
        for wlan in wlans:
            if not isinstance(wlan, dict):
                raise ValueError('Registro WLAN invalido.')
            candidates = [_identifier(wlan[key], required=True) for key in ('_id', 'id', 'wlan_id')
                          if wlan.get(key) not in (None, '')]
            if not candidates or len(set(candidates)) != 1:
                raise ValueError('Identidade WLAN ausente ou conflitante.')
            identity = candidates[0]
            if identity in identities:
                raise ValueError('Identidade WLAN duplicada.')
            identities.add(identity)
            name = wlan.get('name') or wlan.get('essid')
            if not isinstance(name, str) or not name.strip() or len(name) > 240 or '\x00' in name:
                raise ValueError('Nome WLAN invalido.')
            bands = wlan.get('wlan_bands') or wlan.get('wlan_band') or []
            if isinstance(bands, str):
                bands = [bands]
            if not isinstance(bands, list) or any(not isinstance(band, str) or not band.strip()
                                                  or len(band) > 40 or '\x00' in band for band in bands):
                raise ValueError('Bandas WLAN invalidas.')
            enabled = wlan.get('enabled')
            result.append({'wlan_id': identity, 'nome': name,
                           'networkconf_id': _identifier(wlan.get('networkconf_id')),
                           'ativo': enabled if type(enabled) is bool else None,
                           'bandas': list(dict.fromkeys(bands)), 'origem': 'configuracao_unifi',
                           'coletado_em': at})
        return {'coleta_wlans_confirmada': True, 'wlans_coletadas_em': at,
                'wlans_configuradas': sorted(result, key=lambda item: item['wlan_id']),
                'wlans_situacao': 'confirmada'}
    except (ValueError, TypeError, OverflowError):
        return {**empty, 'wlans_situacao': 'identidade_ou_estrutura_invalida'}
