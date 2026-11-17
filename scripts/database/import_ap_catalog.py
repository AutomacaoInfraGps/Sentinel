"""Bootstrap native UniFi APs into empty tables; simulation is the default."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _mac
from scripts.database.import_firewall_cache import (
    DatabaseProgress, ImportErrorSafe, _database_error, _observation,
)
from scripts.database.import_link_catalog import _endpoint, _integer
from scripts.database.import_server_catalog import _identity, _text
from scripts.database.import_switch_catalog import _load
from scripts.database.import_vpn_catalog import _aware_time
from unifi_site_matching import resolve_unifi_site_for_catalog

CONTROLLER_ID = 'sentinel_unifi_principal'
STATUSES = {'online', 'offline', 'warning', 'unknown', 'maintenance', 'inativo'}
SITE_COLUMNS = ('controladora_id', 'id_origem', 'nome', 'codigo_regional', 'vinculo_regional')
AP_COLUMNS = ('controladora_id', 'mac', 'site_id', 'nome', 'ip', 'modelo_codigo', 'modelo',
              'firmware', 'status', 'clientes', 'uptime_segundos', 'coletado_em', 'em_manutencao')


@dataclass(frozen=True, repr=False)
class ApCatalog:
    digest: str
    source_sha256: str
    regionals_sha256: str
    source_timezone: str
    regional_codes: tuple = field(repr=False)
    controller: tuple = field(repr=False)
    sites: tuple = field(repr=False)
    aps: tuple = field(repr=False)

    def summary(self):
        by_site = {row[1]: row for row in self.sites}
        return {
            'digest_carga': self.digest, 'sha256_unifi': self.source_sha256,
            'sha256_catalogo_regionais': self.regionals_sha256, 'fuso_publicacao_legada': self.source_timezone,
            'publicacao_da_fonte': 'ausente' if self.controller[3] is None else
                'sem_fuso_convertida' if self.controller[4] else 'com_fuso',
            'controladoras': 1, 'regionais_no_catalogo': len(self.regional_codes),
            'sites': len(self.sites), 'sites_com_regional': sum(row[3] is not None for row in self.sites),
            'aps': len(self.aps), 'aps_com_regional': sum(by_site[row[2]][3] is not None for row in self.aps),
            'aps_sem_regional': sum(by_site[row[2]][3] is None for row in self.aps),
            'por_vinculo_regional': dict(Counter(by_site[row[2]][4] for row in self.aps)),
            'por_status': dict(Counter(row[8] for row in self.aps)),
            'sem_coleta_explicita_por_ap': sum(row[11] is None for row in self.aps),
            'sincronizacao_automatica_aps': False,
        }


def _site_id(value):
    result = _text(value, 120, required=True)
    if result != value or not re.fullmatch(r'[A-Za-z0-9_.-]+', result):
        raise ImportErrorSafe('Identidade de site invalida.')
    return result


def build_ap_catalog(raw_unifi, raw_regionals, source_timezone):
    try:
        zone = ZoneInfo(source_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ImportErrorSafe('Fuso IANA indisponivel. Confira tzdata.') from None
    payload, catalog = _load(raw_unifi), _load(raw_regionals)
    regions = catalog.get('regionais') if isinstance(catalog, dict) else None
    if not isinstance(regions, dict) or not regions:
        raise ImportErrorSafe('Catalogo regional ausente ou vazio.')
    for code, entry in regions.items():
        if (_text(code, 120, required=True) != code or code != code.upper() or not isinstance(entry, dict)):
            raise ImportErrorSafe('Cadastro regional invalido.')
        for key in ('nome', 'descricao'):
            _text(entry.get(key))
    if not isinstance(payload, dict) or not isinstance(payload.get('controller'), dict):
        raise ImportErrorSafe('Controladora UniFi ausente ou invalida.')
    source_controller = payload['controller']
    host = _endpoint(source_controller.get('ip'))
    port = _integer(source_controller.get('porta'), 1, 65535)
    if port is None:
        raise ImportErrorSafe('Porta da controladora ausente.')
    published = _observation(payload.get('timestamp'), zone)
    naive = bool(published is not None and datetime.fromisoformat(
        payload['timestamp'].strip().replace('Z', '+00:00')).utcoffset() is None)
    controller = (CONTROLLER_ID, host, port, published, naive)
    source_sites, source_aps = payload.get('sites'), payload.get('aps')
    if not isinstance(source_sites, list) or not source_sites or not isinstance(source_aps, list) or not source_aps:
        raise ImportErrorSafe('Inventario UniFi ausente, vazio ou invalido. Carga bloqueada.')
    sites, site_ids, labels = [], set(), defaultdict(list)
    for site in source_sites:
        if not isinstance(site, dict):
            raise ImportErrorSafe('Registro de site invalido.')
        site_id = _site_id(site.get('id'))
        if site_id in site_ids:
            raise ImportErrorSafe('ID de site duplicado. Nenhum registro foi fundido.')
        site_ids.add(site_id)
        name = _text(site.get('nome'), required=True)
        labels[name].append(site_id)
        regional, reason = resolve_unifi_site_for_catalog(regions, name)
        sites.append((CONTROLLER_ID, site_id, name, regional, reason))
    aps, macs = [], set()
    for ap in source_aps:
        if not isinstance(ap, dict):
            raise ImportErrorSafe('Registro de AP invalido.')
        mac = _mac(ap.get('mac'))
        if mac is None or int(mac[:2], 16) & 1:
            raise ImportErrorSafe('MAC do AP ausente, invalido ou nao unicast.')
        if mac in macs:
            raise ImportErrorSafe('MAC duplicado na controladora. Nenhum AP foi fundido.')
        macs.add(mac)
        mac = ':'.join(mac[index:index + 2] for index in range(0, 12, 2))
        label = _text(ap.get('site'))
        explicit = ap.get('site_id')
        if explicit not in (None, ''):
            site_id = _site_id(explicit)
            if site_id not in site_ids or (label and site_id not in labels.get(label, [])):
                raise ImportErrorSafe('Site do AP desconhecido ou conflitante.')
        else:
            matches = labels.get(label, [])
            if len(matches) != 1:
                raise ImportErrorSafe('Nome de site do AP ausente, desconhecido ou ambiguo.')
            site_id = matches[0]
        status = _text(ap.get('status'), 40, required=True).lower()
        if status not in STATUSES:
            raise ImportErrorSafe('Status de AP nao reconhecido; revise a origem.')
        address = _text(ap.get('ip'), 80)
        if address:
            try:
                address = str(ipaddress.ip_address(address))
            except ValueError:
                raise ImportErrorSafe('IP do AP invalido.') from None
        collected = ap.get('coletado_em')
        collected = _aware_time(collected) if collected not in (None, '') else None
        maintenance = ap.get('em_manutencao')
        if maintenance is not None and type(maintenance) is not bool:
            raise ImportErrorSafe('Indicador de manutencao invalido.')
        aps.append((CONTROLLER_ID, mac, site_id, _text(ap.get('nome'), required=True), address,
                    _text(ap.get('modelo_codigo')), _text(ap.get('modelo')), _text(ap.get('firmware')),
                    status, _integer(ap.get('clientes')), _integer(ap.get('uptime'), maximum=9223372036854775807),
                    collected, maintenance))
    sites.sort(key=lambda row: row[1])
    aps.sort(key=lambda row: row[1])
    hashes = hashlib.sha256(raw_unifi).hexdigest(), hashlib.sha256(raw_regionals).hexdigest()
    codes = tuple(sorted(regions))
    canonical = json.dumps((hashes, source_timezone, codes, controller, sites, aps),
                           default=lambda value: value.isoformat(), ensure_ascii=True, separators=(',', ':'))
    return ApCatalog(hashlib.sha256(canonical.encode()).hexdigest(), *hashes, source_timezone,
                     codes, controller, tuple(sites), tuple(aps))


def _table_counts(cursor):
    cursor.execute('SELECT (SELECT count(*) FROM operacional.controladoras_unifi), '
                   '(SELECT count(*) FROM operacional.sites_unifi), '
                   '(SELECT count(*) FROM operacional.aps_unifi)')
    return cursor.fetchone()


def _missing_regionals(cursor, catalog):
    cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(catalog.regional_codes),))
    return set(catalog.regional_codes) - {row[0] for row in cursor.fetchall()}


def inspect_ap_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        counts = _table_counts(cursor)
        missing = _missing_regionals(cursor, catalog)
    return {'controladoras_existentes': counts[0], 'sites_existentes': counts[1],
            'aps_existentes': counts[2], 'tabelas_unifi_vazias': counts == (0, 0, 0),
            'regionais_do_catalogo_ausentes_no_banco': len(missing)}


def write_ap_catalog(connection, catalog, *, progress=None):
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
        cursor.execute('LOCK TABLE operacional.controladoras_unifi IN ROW EXCLUSIVE MODE')
        cursor.execute('LOCK TABLE operacional.sites_unifi IN ROW EXCLUSIVE MODE')
        cursor.execute('LOCK TABLE operacional.aps_unifi IN ROW EXCLUSIVE MODE')
        progress.phase = 'validacao_carga_inicial'
        if _table_counts(cursor) != (0, 0, 0):
            raise ImportErrorSafe('Tabelas UniFi nao estao vazias. Nao repetir a carga inicial.')
        if _missing_regionals(cursor, catalog):
            raise ImportErrorSafe('Catalogo regional divergente do banco. Carga bloqueada.')
        progress.phase = 'insercao_controladora'
        cursor.execute('INSERT INTO operacional.controladoras_unifi '
                       '(id,host,porta,publicacao_fonte_em,publicacao_sem_fuso_na_origem,'
                       'arquivo_origem_sha256,catalogo_regionais_sha256,fuso_publicacao_legada) '
                       'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                       (*catalog.controller, catalog.source_sha256, catalog.regionals_sha256, catalog.source_timezone))
        progress.phase = 'insercao_sites'
        statement = ('INSERT INTO operacional.sites_unifi (' + ','.join(SITE_COLUMNS) + ') VALUES ('
                     + ','.join(['%s'] * len(SITE_COLUMNS)) + ')')
        for row in catalog.sites:
            cursor.execute(statement, row)
        progress.phase = 'insercao_aps'
        statement = ('INSERT INTO operacional.aps_unifi (' + ','.join(AP_COLUMNS) + ') VALUES ('
                     + ','.join(['%s'] * len(AP_COLUMNS)) + ')')
        for row in catalog.aps:
            cursor.execute(statement, row)
        progress.phase = 'conferencia_final'
        if _table_counts(cursor) != (1, len(catalog.sites), len(catalog.aps)):
            raise ImportErrorSafe('Contagens UniFi divergentes. Transacao cancelada.')
        cursor.execute('SELECT status,count(*) FROM operacional.aps_unifi GROUP BY status')
        if dict(cursor.fetchall()) != dict(Counter(row[8] for row in catalog.aps)):
            raise ImportErrorSafe('Contagem por status divergente. Transacao cancelada.')
        cursor.execute('SELECT count(*) FROM operacional.aps_unifi a JOIN operacional.sites_unifi s '
                       'ON s.controladora_id=a.controladora_id AND s.id_origem=a.site_id '
                       'WHERE s.codigo_regional IS NOT NULL')
        if cursor.fetchone() != (catalog.summary()['aps_com_regional'],):
            raise ImportErrorSafe('Contagem de vinculos regionais divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/unifi.json')
    parser.add_argument('--regionals', type=Path, default=ROOT / 'estrutura_regionais.json')
    parser.add_argument('--source-timezone', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        catalog = build_ap_catalog(args.source.read_bytes(), args.regionals.read_bytes(), args.source_timezone)
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
                    write_ap_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_aps_confirmada'
                else:
                    progress.phase = 'conferencia_somente_leitura'
                    result['banco'] = inspect_ap_catalog(connection, catalog)
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
