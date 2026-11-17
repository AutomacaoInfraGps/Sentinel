"""Bootstrap confirmed configured WLANs; never import the SSID display merge."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_ap_catalog import CONTROLLER_ID, _site_id
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from scripts.database.import_link_catalog import _endpoint, _integer
from scripts.database.import_server_catalog import _identity, _text
from scripts.database.import_switch_catalog import _load
from scripts.database.import_vpn_catalog import _aware_time
from services.unifi_wlan_collection import _identifier
from unifi_site_matching import resolve_unifi_site_for_catalog

COLUMNS = ('controladora_id', 'site_id', 'id_origem', 'nome', 'networkconf_id',
           'ativo', 'bandas', 'coletado_em', 'origem')


@dataclass(frozen=True, repr=False)
class WlanCatalog:
    digest: str
    source_sha256: str
    regionals_sha256: str
    regional_codes: tuple = field(repr=False)
    controller: tuple = field(repr=False)
    sites: tuple = field(repr=False)
    rows: tuple = field(repr=False)

    def summary(self):
        sites = {row[0]: row for row in self.sites}
        return {
            'digest_carga': self.digest, 'sha256_unifi': self.source_sha256,
            'sha256_catalogo_regionais': self.regionals_sha256,
            'fonte': 'wlans_configuradas', 'horarios_coleta': 'UTC',
            'regionais_no_catalogo': len(self.regional_codes), 'sites_com_coleta_confirmada': len(self.sites),
            'sites_com_lista_vazia': sum(not any(row[1] == site[0] for row in self.rows) for site in self.sites),
            'wlans': len(self.rows), 'wlans_com_regional': sum(sites[row[1]][2] is not None for row in self.rows),
            'wlans_sem_regional': sum(sites[row[1]][2] is None for row in self.rows),
            'por_vinculo_regional': dict(Counter(sites[row[1]][3] for row in self.rows)),
            'por_ativo': dict(Counter('ativa' if row[5] is True else 'inativa' if row[5] is False else
                                     'desconhecido' for row in self.rows)),
            'sem_id_rede': sum(row[4] is None for row in self.rows),
            'coleta_mais_antiga': min(row[7] for row in self.rows).isoformat(),
            'coleta_mais_recente': max(row[7] for row in self.rows).isoformat(),
            'lista_de_exibicao_importada': False, 'sincronizacao_automatica_wlans': False,
        }


def _wlan_time(value):
    try:
        return _aware_time(value)
    except ImportErrorSafe:
        raise ImportErrorSafe('WLAN exige coleta explicita com data completa e fuso.') from None


def build_wlan_catalog(raw_unifi, raw_regionals):
    payload, catalog = _load(raw_unifi), _load(raw_regionals)
    regions = catalog.get('regionais') if isinstance(catalog, dict) else None
    if not isinstance(regions, dict) or not regions:
        raise ImportErrorSafe('Catalogo regional ausente ou vazio.')
    for code, entry in regions.items():
        if (_text(code, 120, required=True) != code or code != code.upper() or not isinstance(entry, dict)):
            raise ImportErrorSafe('Cadastro regional invalido.')
        _text(entry.get('nome'))
    if not isinstance(payload, dict) or not isinstance(payload.get('controller'), dict):
        raise ImportErrorSafe('Controladora UniFi ausente ou invalida.')
    controller = (CONTROLLER_ID, _endpoint(payload['controller'].get('ip')),
                  _integer(payload['controller'].get('porta'), 1, 65535))
    if controller[2] is None:
        raise ImportErrorSafe('Porta da controladora ausente.')
    source_sites = payload.get('sites')
    if not isinstance(source_sites, list) or not source_sites:
        raise ImportErrorSafe('Sites UniFi ausentes ou invalidos.')
    sites, rows, site_ids, identities = [], [], set(), set()
    for site in source_sites:
        if (not isinstance(site, dict) or site.get('coleta_wlans_confirmada') is not True
                or site.get('wlans_situacao') != 'confirmada' or not isinstance(site.get('wlans_configuradas'), list)):
            raise ImportErrorSafe('Carga inicial exige configuracao WLAN confirmada em todos os sites publicados.')
        site_id = _site_id(site.get('id'))
        if site_id in site_ids:
            raise ImportErrorSafe('ID de site duplicado.')
        site_ids.add(site_id)
        name = _text(site.get('nome'), required=True)
        collected = _wlan_time(site.get('wlans_coletadas_em'))
        code, reason = resolve_unifi_site_for_catalog(regions, name)
        sites.append((site_id, name, code, reason, collected))
        for wlan in site['wlans_configuradas']:
            if not isinstance(wlan, dict) or wlan.get('origem') != 'configuracao_unifi':
                raise ImportErrorSafe('Registro WLAN invalido ou sem origem de configuracao.')
            try:
                identity = _identifier(wlan.get('wlan_id'), required=True)
                network_id = _identifier(wlan.get('networkconf_id'))
            except ValueError:
                raise ImportErrorSafe('Identidade nativa de WLAN ou rede invalida.') from None
            if (site_id, identity) in identities:
                raise ImportErrorSafe('ID de WLAN duplicado no site. Nenhuma rede foi fundida.')
            identities.add((site_id, identity))
            wlan_name = wlan.get('nome')
            if (not isinstance(wlan_name, str) or not wlan_name.strip() or len(wlan_name) > 240
                    or '\x00' in wlan_name):
                raise ImportErrorSafe('Nome de WLAN invalido.')
            active = wlan.get('ativo')
            if active is not None and type(active) is not bool:
                raise ImportErrorSafe('Indicador ativo de WLAN invalido.')
            bands = wlan.get('bandas')
            if not isinstance(bands, list) or any(not isinstance(band, str) or not band.strip()
                                                  or len(band) > 40 or '\x00' in band for band in bands):
                raise ImportErrorSafe('Lista de bandas WLAN invalida.')
            observed = _wlan_time(wlan.get('coletado_em'))
            if observed != collected:
                raise ImportErrorSafe('Horario da WLAN diverge da coleta do site.')
            rows.append((CONTROLLER_ID, site_id, identity, wlan_name, network_id, active,
                         tuple(dict.fromkeys(bands)), observed, 'configuracao_unifi'))
    if not rows:
        raise ImportErrorSafe('Nenhuma WLAN configurada. Carga inicial vazia bloqueada.')
    rows.sort(key=lambda row: row[:3])
    sites.sort(key=lambda row: row[0])
    hashes = hashlib.sha256(raw_unifi).hexdigest(), hashlib.sha256(raw_regionals).hexdigest()
    codes = tuple(sorted(regions))
    canonical = json.dumps((hashes, codes, controller, sites, rows), ensure_ascii=True,
                           default=lambda item: item.isoformat(), separators=(',', ':'))
    return WlanCatalog(hashlib.sha256(canonical.encode()).hexdigest(), *hashes,
                       codes, controller, tuple(sites), tuple(rows))


def _inspect_parents(cursor, catalog):
    cursor.execute('SELECT host,porta FROM operacional.controladoras_unifi WHERE id=%s', (catalog.controller[0],))
    compatible = cursor.fetchone() == catalog.controller[1:]
    cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(catalog.regional_codes),))
    missing_regions = set(catalog.regional_codes) - {row[0] for row in cursor.fetchall()}
    cursor.execute('SELECT id_origem,nome,codigo_regional FROM operacional.sites_unifi '
                   'WHERE controladora_id=%s AND id_origem=ANY(%s)',
                   (catalog.controller[0], [site[0] for site in catalog.sites]))
    stored = {row[0]: row[1:] for row in cursor.fetchall()}
    return {'controladora_compativel': compatible,
            'regionais_do_catalogo_ausentes_no_banco': len(missing_regions),
            'sites_ausentes_no_banco': sum(site[0] not in stored for site in catalog.sites),
            'sites_com_nome_divergente': sum(site[0] in stored and stored[site[0]][0] != site[1] for site in catalog.sites),
            'sites_com_regional_divergente': sum(site[0] in stored and stored[site[0]][1] != site[2] for site in catalog.sites)}


def inspect_wlan_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        result = _inspect_parents(cursor, catalog)
        cursor.execute('SELECT count(*) FROM operacional.wlans_unifi')
        count = cursor.fetchone()[0]
    return {**result, 'wlans_existentes': count, 'tabela_wlans_vazia': count == 0}


def write_wlan_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'configuracao_transacao'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        progress.phase = 'validacao_destino'
        _identity(cursor)
        progress.phase = 'bloqueio_tabelas'
        for table in ('regionais', 'controladoras_unifi', 'sites_unifi'):
            cursor.execute('LOCK TABLE operacional.' + table + ' IN SHARE ROW EXCLUSIVE MODE')
        cursor.execute('LOCK TABLE operacional.wlans_unifi IN ROW EXCLUSIVE MODE')
        progress.phase = 'contagem_inicial'
        cursor.execute('SELECT count(*) FROM operacional.wlans_unifi')
        if cursor.fetchone() != (0,):
            raise ImportErrorSafe('WLANs ja cadastradas. Nao repetir a carga inicial.')
        progress.phase = 'validacao_pais'
        parents = _inspect_parents(cursor, catalog)
        if not parents['controladora_compativel'] or any(value for key, value in parents.items() if key != 'controladora_compativel'):
            raise ImportErrorSafe('Controladora, sites ou vinculos regionais divergentes. Carga bloqueada.')
        columns = (*COLUMNS, 'arquivo_origem_sha256', 'catalogo_regionais_sha256')
        sql = ('INSERT INTO operacional.wlans_unifi (' + ','.join(columns) + ') VALUES ('
               + ','.join(['%s'] * len(columns)) + ')')
        progress.phase = 'insercao_wlans'
        for row in catalog.rows:
            values = (*row[:6], list(row[6]), *row[7:], catalog.source_sha256, catalog.regionals_sha256)
            cursor.execute(sql, values)
        progress.phase = 'conferencia_final'
        cursor.execute('SELECT count(*) FROM operacional.wlans_unifi')
        if cursor.fetchone() != (len(catalog.rows),):
            raise ImportErrorSafe('Contagem WLAN divergente. Transacao cancelada.')
        cursor.execute('SELECT ativo,count(*) FROM operacional.wlans_unifi GROUP BY ativo')
        if dict(cursor.fetchall()) != dict(Counter(row[5] for row in catalog.rows)):
            raise ImportErrorSafe('Contagem por ativo divergente. Transacao cancelada.')
        cursor.execute('SELECT count(*) FROM operacional.wlans_unifi w JOIN operacional.sites_unifi s '
                       'ON s.controladora_id=w.controladora_id AND s.id_origem=w.site_id '
                       'WHERE s.codigo_regional IS NOT NULL')
        if cursor.fetchone() != (catalog.summary()['wlans_com_regional'],):
            raise ImportErrorSafe('Contagem de vinculos WLAN divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/unifi.json')
    parser.add_argument('--regionals', type=Path, default=ROOT / 'estrutura_regionais.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        catalog = build_wlan_catalog(args.source.read_bytes(), args.regionals.read_bytes())
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
                    write_wlan_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_wlans_confirmada'
                else:
                    progress.phase = 'conferencia_somente_leitura'
                    result['banco'] = inspect_wlan_catalog(connection, catalog)
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
