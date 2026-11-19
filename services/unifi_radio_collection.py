"""Whitelist radio configuration and statistics from an existing device response."""

from collections import Counter
from datetime import datetime, timezone
import math
import re

METRICS = {'cu_total': 'cu_total', 'cu_self_tx': 'cu_self_tx',
           'cu_self_rx': 'cu_self_rx', 'tx_retry': 'tx_retries_pct'}


def _identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', value) else None


def _mac(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', value):
        value = value.replace(':', '')
    elif re.fullmatch(r'(?:[0-9a-f]{2}-){5}[0-9a-f]{2}', value):
        value = value.replace('-', '')
    if not re.fullmatch(r'[0-9a-f]{12}', value) or value in ('000000000000', 'ffffffffffff'):
        return None
    return ':'.join(value[i:i + 2] for i in range(0, 12, 2))


def _received_at(value):
    try:
        if not isinstance(value, str) or 'T' not in value:
            return None
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _percent(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 100 and math.isfinite(value))


def _channel(value):
    return ((type(value) is int and 0 <= value <= 1000)
            or (isinstance(value, str) and (
                value == 'auto' or bool(re.fullmatch(r'[0-9]{1,4}', value)) and int(value) <= 1000)))


def _field(row, key, validator):
    if key not in row:
        return None, 'ausente'
    value = row[key]
    if value is None:
        return None, 'nulo'
    return (value, 'informado') if validator(value) else (None, 'invalido')


def _table(ap, key, statistics=False):
    result = {'situacao': 'ausente', 'registros': [], 'registros_invalidos': 0}
    if key not in ap:
        return result
    values = ap[key]
    if values is None:
        return {**result, 'situacao': 'nulo'}
    if not isinstance(values, list):
        return {**result, 'situacao': 'estrutura_invalida'}
    result['situacao'] = 'presente'
    for row in values:
        if not isinstance(row, dict):
            result['registros_invalidos'] += 1
            continue
        projected = {'situacao_campos': {}}
        fields = {'nome_interface': ('name', lambda v: _identifier(v) is not None),
                  'banda_declarada': ('radio', lambda v: _identifier(v) is not None),
                  'canal': ('channel', _channel)}
        if statistics:
            fields.update({target: (source, _percent) for target, source in METRICS.items()})
        for target, (source, validator) in fields.items():
            projected[target], projected['situacao_campos'][target] = _field(row, source, validator)
        result['registros'].append(projected)
    names = Counter(row['nome_interface'] for row in result['registros'] if row['nome_interface'])
    for row in result['registros']:
        row['interface_unica_na_tabela'] = bool(row['nome_interface'] and names[row['nome_interface']] == 1)
    return result


def ap_radio_evidence(ap, site_id, received_at):
    """Receipt time is not a measurement time; tables are never joined by band."""
    ap = ap if isinstance(ap, dict) else {}
    mac, site, at = _mac(ap.get('mac')), _identifier(site_id), _received_at(received_at)
    state = ap.get('state')
    return {
        'version': 1, 'origem': 'resposta_stat_device_unifi',
        'mac': mac, 'site_id': site, 'identidade_ap_informada': bool(mac and site),
        'recebido_em': at, 'recebimento_com_fuso': at is not None,
        'medido_em': None, 'data_medicao_confirmada': False,
        'ap_online_declarado': state == 1 if type(state) is int and state >= 0 else None,
        'configuracoes': _table(ap, 'radio_table'),
        'estatisticas': _table(ap, 'radio_table_stats', statistics=True),
    }
