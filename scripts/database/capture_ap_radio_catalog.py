"""Simulate or freeze a whitelisted native RF projection; no SQL operations."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _time_kind, _unique_object
from services.unifi_radio_collection import _channel, _identifier, _mac, _percent, _received_at

SOURCE = 'sentinel_radios_unifi_nativos'
CONTROLLER = 'sentinel_unifi_principal'
METRICS = ('cu_total', 'cu_self_tx', 'cu_self_rx', 'tx_retry')
RADIO_FIELDS = {'version', 'origem', 'mac', 'site_id', 'identidade_ap_informada',
                'recebido_em', 'recebimento_com_fuso', 'medido_em', 'data_medicao_confirmada',
                'ap_online_declarado', 'configuracoes', 'estatisticas'}
ENVELOPE = {'version', 'fonte', 'capturado_em', 'publicacao_textual', 'sha256_arquivo_origem',
            'sha256_projecao', 'digest_carga', 'controladora', 'aps'}


class CaptureError(ValueError):
    """Fixed messages only: never include source values or credentials."""


def _encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_encode(value)).hexdigest()


def _reject_constant(value):
    raise ValueError('Non-finite JSON number')


def _json(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise CaptureError('Arquivo acima do limite de leitura.')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise CaptureError('JSON invalido, nao finito ou com chaves duplicadas.') from None


def _time(value):
    result = _received_at(value)
    if result is None:
        raise CaptureError('Horario completo com fuso obrigatorio.')
    return result


def _controller(value):
    if not isinstance(value, dict):
        raise CaptureError('Controladora ausente.')
    host, port = value.get('host'), value.get('porta')
    if not isinstance(host, str) or host != host.strip() or not 0 < len(host) <= 253:
        raise CaptureError('Endpoint da controladora invalido.')
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        if re.fullmatch(r'[0-9.]+', host) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?', host):
            raise CaptureError('Endpoint da controladora invalido.') from None
    if type(port) is not int or not 1 <= port <= 65535:
        raise CaptureError('Porta da controladora invalida.')
    return {'id': CONTROLLER, 'host': host, 'porta': port}


def _table(table, statistics=False):
    if not isinstance(table, dict) or set(table) != {'situacao', 'registros', 'registros_invalidos'}:
        raise CaptureError('Envelope de tabela RF invalido.')
    if table['situacao'] not in ('presente', 'ausente', 'nulo') or type(table['registros_invalidos']) is not int or table['registros_invalidos'] != 0:
        raise CaptureError('Tabela RF com estrutura invalida exige revisao.')
    rows = table['registros']
    if not isinstance(rows, list) or len(rows) > 1000 or (table['situacao'] != 'presente' and rows):
        raise CaptureError('Lista RF invalida ou incoerente.')
    validators = {'nome_interface': lambda v: _identifier(v) is not None,
                  'banda_declarada': lambda v: _identifier(v) is not None, 'canal': _channel}
    if statistics:
        validators.update({key: _percent for key in METRICS})
    names = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(validators) | {'situacao_campos', 'interface_unica_na_tabela'}:
            raise CaptureError('Campos RF fora do escopo permitido.')
        states = row['situacao_campos']
        if not isinstance(states, dict) or set(states) != set(validators):
            raise CaptureError('Situacoes dos campos RF invalidas.')
        for field, validator in validators.items():
            state, value = states[field], row[field]
            if state == 'informado' and validator(value):
                continue
            if isinstance(state, str) and state in ('ausente', 'nulo', 'invalido') and value is None:
                continue
            raise CaptureError('Valor RF diverge da situacao declarada.')
        name = row['nome_interface']
        if not name or name in names or row['interface_unica_na_tabela'] is not True:
            raise CaptureError('Interface RF ausente ou repetida; nao sera inferida pela banda ou posicao.')
        names.add(name)
    return {**table, 'registros': sorted(rows, key=lambda row: row['nome_interface'])}


def _radios(records, captured_at):
    if not isinstance(records, list) or not 0 < len(records) <= 10000:
        raise CaptureError('Lista de APs nativa vazia ou invalida.')
    result, identities = [], set()
    for row in records:
        if not isinstance(row, dict) or set(row) != RADIO_FIELDS:
            raise CaptureError('Envelope RF fora do escopo permitido.')
        if type(row['version']) is not int or row['version'] != 1 or row['origem'] != 'resposta_stat_device_unifi':
            raise CaptureError('Fonte ou versao RF invalida.')
        if not _mac(row['mac']) or row['mac'] != _mac(row['mac']) or not _identifier(row['site_id']):
            raise CaptureError('Identidade nativa do AP invalida.')
        if row['mac'] in identities:
            raise CaptureError('AP repetido na controladora; nenhum vinculo sera escolhido.')
        identities.add(row['mac'])
        if row['identidade_ap_informada'] is not True or row['recebimento_com_fuso'] is not True:
            raise CaptureError('Identidade ou recebimento RF nao confirmado.')
        received = _time(row['recebido_em'])
        if datetime.fromisoformat(received) > datetime.fromisoformat(captured_at):
            raise CaptureError('Recebimento da resposta posterior a captura.')
        if row['medido_em'] is not None or row['data_medicao_confirmada'] is not False:
            raise CaptureError('Data de medicao nao comprovada nesta versao.')
        if row['ap_online_declarado'] is not None and type(row['ap_online_declarado']) is not bool:
            raise CaptureError('Estado declarado do AP invalido.')
        result.append({**row, 'recebido_em': received,
                       'configuracoes': _table(row['configuracoes']),
                       'estatisticas': _table(row['estatisticas'], statistics=True)})
    return sorted(result, key=lambda row: row['mac'])


def capture_payload(raw, now=None):
    original = _json(raw)
    if not isinstance(original, dict) or not isinstance(original.get('controller'), dict):
        raise CaptureError('Envelope UniFi invalido.')
    timestamp = now or datetime.now(timezone.utc)
    captured = _time(timestamp.isoformat())
    publication = original.get('timestamp')
    if _time_kind(publication) not in ('sem_fuso', 'com_fuso'):
        raise CaptureError('Publicacao textual invalida; nenhum fuso sera inferido.')
    sites, aps = original.get('sites'), original.get('aps')
    if not isinstance(sites, list) or not isinstance(aps, list):
        raise CaptureError('Inventario UniFi invalido.')
    site_times = {}
    for site in sites:
        if not isinstance(site, dict) or not _identifier(site.get('id')) or site['id'] in site_times:
            raise CaptureError('Site invalido ou repetido.')
        if site.get('coleta_aps_confirmada') is not True:
            raise CaptureError('Resposta do site sem confirmacao.')
        site_times[site['id']] = _time(site.get('coletado_em'))
    records = []
    for ap in aps:
        native = ap.get('radios_nativos') if isinstance(ap, dict) else None
        if not isinstance(native, dict) or set(native) != RADIO_FIELDS:
            raise CaptureError('Projecao nativa ausente ou invalida; aguarde nova coleta.')
        mac, site = _mac(ap.get('mac')), ap.get('site_id')
        if not mac or not _identifier(site) or native['mac'] != mac or native['site_id'] != site:
            raise CaptureError('Identidade RF diverge do inventario; nenhum nome sera usado como fallback.')
        received = _time(native['recebido_em'])
        if site_times.get(site) != received or _time(ap.get('coletado_em')) != received:
            raise CaptureError('Recebimento RF diverge da resposta de dispositivos do site.')
        records.append(native)
    controller = _controller({'host': original['controller'].get('ip'), 'porta': original['controller'].get('porta')})
    records = _radios(records, captured)
    projection = {'controladora': controller, 'aps': records}
    payload = {'version': 1, 'fonte': SOURCE, 'capturado_em': captured, 'publicacao_textual': publication,
               'sha256_arquivo_origem': hashlib.sha256(raw).hexdigest(),
               'sha256_projecao': _hash(projection), **projection}
    payload['digest_carga'] = _hash(payload)
    return payload


def validate_capture(raw):
    payload = _json(raw)
    if not isinstance(payload, dict) or set(payload) != ENVELOPE:
        raise CaptureError('Formato de captura invalido.')
    if type(payload['version']) is not int or payload['version'] != 1 or payload['fonte'] != SOURCE:
        raise CaptureError('Fonte ou versao de captura invalida.')
    for key in ('sha256_arquivo_origem', 'sha256_projecao', 'digest_carga'):
        if not isinstance(payload[key], str) or not re.fullmatch(r'[0-9a-f]{64}', payload[key]):
            raise CaptureError('Hash invalido.')
    if _time_kind(payload['publicacao_textual']) not in ('sem_fuso', 'com_fuso'):
        raise CaptureError('Publicacao textual invalida.')
    controller = _controller(payload['controladora'])
    records = _radios(payload['aps'], _time(payload['capturado_em']))
    if payload['controladora'] != controller or payload['aps'] != records:
        raise CaptureError('Captura nao canonica.')
    if _hash({'controladora': controller, 'aps': records}) != payload['sha256_projecao'] or _hash(
            {key: value for key, value in payload.items() if key != 'digest_carga'}) != payload['digest_carga']:
        raise CaptureError('Captura alterada; hashes divergentes.')
    return payload


def summary(payload):
    aps = payload['aps']
    configs = [row for ap in aps for row in ap['configuracoes']['registros']]
    stats = [row for ap in aps for row in ap['estatisticas']['registros']]
    return {key: payload[key] for key in ('version', 'fonte', 'capturado_em', 'digest_carga',
                                         'sha256_arquivo_origem', 'sha256_projecao')} | {
        'publicacao_fonte': _time_kind(payload['publicacao_textual']),
        'aps': len(aps), 'sites_dos_aps': len({ap['site_id'] for ap in aps}),
        'configuracoes_radio': len(configs), 'estatisticas_radio': len(stats),
        'metricas_por_situacao': {key: dict(Counter(row['situacao_campos'][key] for row in stats)) for key in METRICS},
        'sem_data_de_medicao': sum(ap['medido_em'] is None for ap in aps),
        'tabelas_associadas_automaticamente': False, 'vinculos_sql_conferidos': False,
        'credenciais_exportadas': False, 'coletor_executado': False,
        'postgresql_acessado': False, 'arquivo_origem_modificado': False,
        'sincronizacao_automatica_radios': False,
    }


def inspect_destination(connection, payload):
    from services.operational_postgres import _identity

    controller = payload['controladora']
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        cursor.execute('SELECT host,porta FROM operacional.controladoras_unifi WHERE id=%s', (controller['id'],))
        endpoint = cursor.fetchone()
        cursor.execute('SELECT id_origem FROM operacional.sites_unifi WHERE controladora_id=%s', (controller['id'],))
        sites = {row[0] for row in cursor.fetchall()}
        cursor.execute('SELECT mac,site_id FROM operacional.aps_unifi WHERE controladora_id=%s', (controller['id'],))
        aps = dict(cursor.fetchall())
    missing_sites = len({ap['site_id'] for ap in payload['aps']} - sites)
    missing_aps = sum(ap['mac'] not in aps for ap in payload['aps'])
    moved_aps = sum(ap['mac'] in aps and aps[ap['mac']] != ap['site_id'] for ap in payload['aps'])
    matches = endpoint == (controller['host'], controller['porta'])
    return {
        'controladora_encontrada': endpoint is not None,
        'endpoint_controladora_confere': matches,
        'sites_da_captura_ausentes': missing_sites,
        'aps_da_captura_ausentes': missing_aps,
        'aps_com_site_divergente': moved_aps,
        'destino_compativel': bool(matches and not (missing_sites or missing_aps or moved_aps)),
        'tabelas_rf_conferidas': False,
        'vinculos_existentes_modificados': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Simula novamente uma captura RF congelada, nao o JSON bruto.')
    parser.add_argument('--capture', type=Path, help='Cria uma captura nova sem sobrescrever; sem SQL.')
    parser.add_argument('--check-database', action='store_true', help='Com --source, confere somente leitura dos vinculos de APs existentes no Rigel.')
    args = parser.parse_args(argv)
    phase = 'leitura_captura'
    try:
        if args.source and args.capture:
            raise CaptureError('--source e --capture nao podem ser combinados.')
        if args.check_database and (args.source is None or args.capture):
            raise CaptureError('Conferencia SQL exige --source congelado e nao aceita --capture.')
        if args.check_database and os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
            raise CaptureError('Execute a conferencia SQL somente no Rigel.')
        path = args.source or ROOT / 'data/unifi.json'
        raw = path.read_bytes()
        payload = validate_capture(raw) if args.source else capture_payload(raw)
        validate_capture(_encode(payload))
        if path.read_bytes() != raw:
            raise CaptureError('Fonte mudou durante a leitura. Repita a simulacao.')
        if args.capture:
            with args.capture.open('xb') as stream:
                stream.write(_encode(payload))
        result = {'modo': 'captura_congelada_sem_postgresql' if args.capture else 'simulacao_sem_conexao_ao_banco', **summary(payload)}
        if args.check_database:
            from services.operational_postgres import connect_collector

            phase = 'conexao'
            with connect_collector(read_only=True) as connection:
                phase = 'conferencia_destino'
                result['banco'] = inspect_destination(connection, payload)
            result.update(modo='conferencia_destino_somente_leitura', postgresql_acessado=True,
                          vinculos_sql_conferidos=True)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except CaptureError as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        if args.check_database and phase in ('conexao', 'conferencia_destino'):
            from scripts.database.import_firewall_cache import _database_error

            print(str(_database_error(phase, exc)), file=sys.stderr)
        else:
            print('Falha na leitura ou captura RF. Mensagem e valores foram omitidos.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
