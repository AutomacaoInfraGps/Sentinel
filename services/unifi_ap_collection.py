"""Validate the native device response before attaching collection evidence."""

from datetime import datetime, timezone


def confirmed_device_response(response):
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('Resposta de dispositivos UniFi invalida.')
    meta = payload.get('meta')
    if meta is not None and (not isinstance(meta, dict) or meta.get('rc') != 'ok'):
        raise ValueError('Consulta de dispositivos UniFi nao confirmada.')
    if any(not isinstance(device, dict) for device in payload['data']):
        raise ValueError('Lista de dispositivos UniFi invalida.')
    return payload['data'], datetime.now(timezone.utc).isoformat()


def ap_collection_evidence(ap, site_id, collected_at):
    return {'site_id': site_id, 'coletado_em': collected_at,
            'coleta_status_confirmada': type(ap.get('state')) is int and ap['state'] >= 0}
