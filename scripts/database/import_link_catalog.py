"""Bootstrap links_internet_auto only; no legacy merge, collection or UI changes."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import (
    DatabaseProgress, ImportErrorSafe, _database_error, _observation,
)
from scripts.database.import_server_catalog import _identity, _text
from scripts.database.import_switch_catalog import _load
from scripts.database.import_vpn_catalog import _aware_time

STATUSES = {'online', 'offline', 'unknown', 'warning', 'inativo', 'maintenance', 'up', 'down', 'unavailable'}
ORIGINS = {'fortigate', 'fortimanager', 'fortimanager_config+proxy_monitor',
           'fortimanager_proxy_monitor', 'fallback_local'}
MODES = {'sla', 'interface', 'fortimanager_device_offline', 'ping', 'fisico',
         'monitor_zabbix_packet_loss', 'link_mode'}
COLUMNS = ('codigo_regional', 'id_origem', 'nome', 'interface_monitorada', 'fortigate_host',
           'fortigate_porta', 'firewall_serial', 'vdom', 'provedor', 'ip', 'mascara', 'velocidade',
           'status', 'ativo', 'origem_sync', 'modo_verificacao', 'sla_status', 'link_mode_status',
           'sdwan_member_id', 'prioridade', 'packet_loss_percent', 'verificado_em', 'coletado_em',
           'verificacao_sem_fuso_na_origem')


def _counts(rows, index, allowed):
    return dict(Counter(row[index] if row[index] in allowed else 'outro_ou_ausente' for row in rows))


@dataclass(frozen=True, repr=False)
class LinkCatalog:
    digest: str
    source_sha256: str
    source_timezone: str
    regional_codes: tuple = field(repr=False)
    rows: tuple = field(repr=False)
    missing_lists: int
    empty_lists: int

    def summary(self):
        return {'digest_carga': self.digest, 'sha256_catalogo': self.source_sha256,
                'fonte': 'links_internet_auto', 'fuso_verificacao_legada': self.source_timezone,
                'regionais_no_catalogo': len(self.regional_codes),
                'regionais_com_links_automaticos': len({row[0] for row in self.rows}),
                'regionais_sem_lista_automatica': self.missing_lists,
                'regionais_com_lista_automatica_vazia': self.empty_lists,
                'links': len(self.rows), 'por_status': _counts(self.rows, 12, STATUSES),
                'por_origem_sync': _counts(self.rows, 14, ORIGINS),
                'por_modo_verificacao': _counts(self.rows, 15, MODES),
                'sem_serial': sum(row[6] is None for row in self.rows),
                'sem_vdom': sum(row[7] is None for row in self.rows),
                'sem_coleta_explicita': sum(row[22] is None for row in self.rows),
                'verificacoes_sem_fuso_na_origem': sum(row[23] for row in self.rows),
                'verificacoes_ausentes': sum(row[21] is None for row in self.rows),
                'legado_links_importado': False, 'sincronizacao_automatica_links': False}


def _identifier(value):
    return _text(str(value) if type(value) is int else value, required=True)


def _integer(value, minimum=0, maximum=2147483647):
    if value is None or value == '':
        return None
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ImportErrorSafe('Valor inteiro invalido no link.')
    return value


def _loss(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ImportErrorSafe('Perda de pacotes invalida.')
    try:
        value = float(value)
    except ValueError:
        raise ImportErrorSafe('Perda de pacotes invalida.') from None
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ImportErrorSafe('Perda de pacotes invalida.')
    return value


def _endpoint(value):
    value = _text(value, 253, required=True)
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if (re.fullmatch(r'[0-9.]+', value)
                or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?', value)):
            raise ImportErrorSafe('Endpoint do firewall invalido.') from None
    return value


def build_link_catalog(raw, source_timezone):
    try:
        zone = ZoneInfo(source_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ImportErrorSafe('Fuso IANA indisponivel. Confira tzdata.') from None
    payload = _load(raw)
    regions = payload.get('regionais') if isinstance(payload, dict) else None
    if not isinstance(regions, dict) or not regions:
        raise ImportErrorSafe('Catalogo regional ausente ou vazio.')
    rows, codes, identities, interface_keys = [], [], set(), set()
    missing = empty = 0
    for code, entry in sorted(regions.items()):
        if (_text(code, 120, required=True) != code or code != code.upper()
                or not isinstance(entry, dict)):
            raise ImportErrorSafe('Cadastro regional invalido.')
        codes.append(code)
        if 'links_internet_auto' not in entry:
            missing += 1
            continue
        links = entry['links_internet_auto']
        if not isinstance(links, list):
            raise ImportErrorSafe('Lista automatica de links invalida.')
        empty += not links
        for record in links:
            if not isinstance(record, dict):
                raise ImportErrorSafe('Registro de link invalido.')
            link_id = _identifier(record.get('id'))
            interface = _text(record.get('interface_monitorada'), required=True)
            host = _endpoint(record.get('fortigate_host'))
            if (code, link_id) in identities or (code, host, interface) in interface_keys:
                raise ImportErrorSafe('ID ou endpoint/interface duplicado na regional. Nenhum link foi fundido.')
            identities.add((code, link_id))
            interface_keys.add((code, host, interface))
            status = _text(record.get('status'), 40)
            status = status.lower() if status else None
            if status not in STATUSES:
                raise ImportErrorSafe('Status do link nao reconhecido; revise a origem.')
            active = record.get('ativo')
            if active is not None and type(active) is not bool:
                raise ImportErrorSafe('Indicador ativo invalido.')
            ip = _text(record.get('ip'), 80)
            if ip:
                try:
                    ip = str(ipaddress.ip_interface(ip)) if '/' in ip else str(ipaddress.ip_address(ip))
                except ValueError:
                    raise ImportErrorSafe('IP do link invalido.') from None
            verified = _observation(record.get('ultima_verificacao'), zone)
            naive = bool(verified is not None and datetime.fromisoformat(
                record['ultima_verificacao'].strip().replace('Z', '+00:00')).utcoffset() is None)
            collected = record.get('coletado_em')
            try:
                collected = _aware_time(collected) if collected not in (None, '') else None
            except ImportErrorSafe:
                raise ImportErrorSafe('Coleta explicita do link exige data completa com fuso.') from None
            serial = _text(record.get('firewall_serial'), 120)
            vdom = _text(record.get('vdom'), 120)
            if ((serial and not re.fullmatch(r'[A-Za-z0-9_.-]+', serial))
                    or (vdom and (not re.fullmatch(r'[A-Za-z0-9_.-]+', vdom)
                                  or vdom.lower() in ('global', 'unknown')))):
                raise ImportErrorSafe('Serial ou VDOM invalido.')
            rows.append((code, link_id, _text(record.get('nome'), required=True), interface, host,
                         _integer(record.get('fortigate_porta'), 1, 65535), serial, vdom,
                         _text(record.get('provedor')), ip, _text(record.get('mascara'), 80),
                         _text(record.get('velocidade'), 120), status, active,
                         _text(record.get('origem_sync'), 120), _text(record.get('modo_verificacao'), 120),
                         _text(record.get('sla_status'), 120), _text(record.get('link_mode_status'), 120),
                         _identifier(record['sdwan_member_id']) if record.get('sdwan_member_id') not in (None, '') else None,
                         _integer(record.get('priority')), _loss(record.get('packet_loss_percent')),
                         verified, collected, naive))
    if not rows:
        raise ImportErrorSafe('Nenhum link automatico. Carga vazia bloqueada.')
    rows.sort(key=lambda row: row[:2])
    source_hash = hashlib.sha256(raw).hexdigest()
    canonical = json.dumps((source_hash, source_timezone, codes, rows),
                           default=lambda value: value.isoformat(), separators=(',', ':'), ensure_ascii=True)
    return LinkCatalog(hashlib.sha256(canonical.encode()).hexdigest(), source_hash,
                       source_timezone, tuple(codes), tuple(rows), missing, empty)


def inspect_link_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)',
                       (list(catalog.regional_codes),))
        missing = set(catalog.regional_codes) - {row[0] for row in cursor.fetchall()}
        cursor.execute('SELECT count(*) FROM operacional.links_internet')
        count = cursor.fetchone()[0]
    return {'links_existentes': count, 'tabela_links_vazia': count == 0,
            'regionais_do_catalogo_ausentes_no_banco': len(missing)}


def write_link_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'configuracao_transacao'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        progress.phase = 'validacao_destino'
        _identity(cursor)
        progress.phase = 'bloqueio_tabelas'
        cursor.execute('LOCK TABLE operacional.regionais IN SHARE ROW EXCLUSIVE MODE')
        cursor.execute('LOCK TABLE operacional.links_internet IN ROW EXCLUSIVE MODE')
        progress.phase = 'contagem_inicial'
        cursor.execute('SELECT count(*) FROM operacional.links_internet')
        if cursor.fetchone() != (0,):
            raise ImportErrorSafe('Links ja cadastrados. Nao repetir a carga inicial.')
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)',
                       (list(catalog.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(catalog.regional_codes):
            raise ImportErrorSafe('Catalogo regional divergente do banco. Carga bloqueada.')
        columns = (*COLUMNS, 'arquivo_origem_sha256', 'fuso_verificacao_legada')
        statement = ('INSERT INTO operacional.links_internet (' + ','.join(columns) + ') VALUES ('
                     + ','.join(['%s'] * len(columns)) + ')')
        for row in catalog.rows:
            progress.phase = 'insercao_links'
            cursor.execute(statement, (*row, catalog.source_sha256, catalog.source_timezone))
        progress.phase = 'contagem_final'
        cursor.execute('SELECT count(*) FROM operacional.links_internet')
        if cursor.fetchone() != (len(catalog.rows),):
            raise ImportErrorSafe('Contagem de links divergente. Transacao cancelada.')
        cursor.execute('SELECT status,count(*) FROM operacional.links_internet GROUP BY status')
        if dict(cursor.fetchall()) != dict(Counter(row[12] for row in catalog.rows)):
            raise ImportErrorSafe('Contagem por status divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'estrutura_regionais.json')
    parser.add_argument('--source-timezone', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        catalog = build_link_catalog(args.source.read_bytes(), args.source_timezone)
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao de banco somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato da simulacao revisada.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_link_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_links_confirmada'
                else:
                    progress.phase = 'conferencia_somente_leitura'
                    result['banco'] = inspect_link_catalog(connection, catalog)
                    result['modo'] = 'conferencia_somente_leitura'
                progress.phase = 'finalizacao_transacao'
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(str(_database_error(progress.phase, exc)), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
