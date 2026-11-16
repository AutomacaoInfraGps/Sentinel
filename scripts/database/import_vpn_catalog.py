"""Bootstrap verified SSH VPN records; simulation by default, no collector changes."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error
from scripts.database.import_server_catalog import _identity, _text
from scripts.database.import_switch_catalog import _load


@dataclass(frozen=True, repr=False)
class VPNCatalog:
    digest: str
    source_sha256: str
    regionals_sha256: str
    regional_codes: tuple = field(repr=False)
    rows: tuple = field(repr=False)

    def summary(self):
        return {'digest_carga': self.digest, 'sha256_estado_operacional': self.source_sha256,
                'sha256_catalogo_regionais': self.regionals_sha256,
                'regionais_no_catalogo': len(self.regional_codes), 'vpns': len(self.rows),
                'dispositivos': len({row[0] for row in self.rows}),
                'contextos_dispositivo_vdom': len({row[:2] for row in self.rows}),
                'vinculos': dict(Counter(row[7] for row in self.rows)),
                'por_status': dict(Counter(row[8] for row in self.rows)),
                'por_origem_vdom': dict(Counter(row[11] for row in self.rows)),
                'coletas_com_fuso': len(self.rows), 'sincronizacao_automatica_vpns': False}


def _aware_time(value):
    value = _text(value, 80, required=True)
    try:
        if 'T' not in value:
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise ImportErrorSafe('VPN exige data completa de coleta com fuso. Nenhuma data foi inferida.') from None


def build_vpn_catalog(raw_source, raw_regionals):
    payload, catalog = _load(raw_source), _load(raw_regionals)
    entries = catalog.get('regionais') if isinstance(catalog, dict) else None
    if not isinstance(entries, dict) or not entries:
        raise ImportErrorSafe('Catalogo regional ausente ou vazio.')
    for code, entry in entries.items():
        if (_text(code, 120, required=True) != code or code != code.upper()
                or not isinstance(entry, dict)):
            raise ImportErrorSafe('Catalogo regional invalido.')
    codes = tuple(sorted(entries))
    groups = payload.get('groups') if isinstance(payload, dict) else None
    group = groups.get('vpns') if isinstance(groups, dict) else None
    records = group.get('records') if isinstance(group, dict) else None
    if (not isinstance(records, list) or not records
            or group.get('source') not in ('vpn_manual', 'mapa')):
        raise ImportErrorSafe('Grupo operacional de VPNs ausente, vazio ou com origem nao reconhecida.')
    rows, identities = [], set()
    for record in records:
        if not isinstance(record, dict) or record.get('vpn_source') != 'fortigate_ssh':
            raise ImportErrorSafe('Carga inicial exige VPNs SSH com serial verificado. Fallback nao sera fundido por nome.')
        serial = _text(record.get('firewall_serial'), 120, required=True)
        vdom = _text(record.get('vdom'), 120, required=True)
        tunnel = _text(record.get('tunel'), required=True)
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+', serial)
                or not re.fullmatch(r'[A-Za-z0-9_.-]+', vdom)
                or vdom.casefold() in ('global', 'unknown', 'n/a')):
            raise ImportErrorSafe('Serial ou VDOM invalido.')
        identity = (serial, vdom, tunnel)
        if identity in identities:
            raise ImportErrorSafe('Identidade serial/VDOM/tunel duplicada. Nenhum registro foi descartado.')
        identities.add(identity)
        origin = record.get('vdom_origem')
        if origin not in ('resposta_equipamento', 'vdom_desabilitado'):
            raise ImportErrorSafe('Origem de resolucao do VDOM nao reconhecida.')
        if origin == 'vdom_desabilitado' and vdom != 'root':
            raise ImportErrorSafe('VDOM incoerente com modo desabilitado.')
        namespace = _text(record.get('device_namespace'), required=True)
        if not namespace.startswith('fortigate_ssh:') or not namespace.removeprefix('fortigate_ssh:').strip():
            raise ImportErrorSafe('Contexto da fonte SSH invalido.')
        regional = _text(record.get('regional'), 120)
        code = regional if regional in entries else None
        binding = ('vinculado' if code else 'ausente' if regional in (None, 'SEM_REGIONAL')
                   else 'nao_encontrado')
        status = record.get('status')
        if status not in ('online', 'offline'):
            raise ImportErrorSafe('Status operacional de VPN nao reconhecido.')
        legacy = _text(record.get('ultima_verificacao'), 8)
        if legacy:
            try:
                datetime.strptime(legacy, '%H:%M:%S')
            except ValueError:
                raise ImportErrorSafe('Hora legada de VPN invalida.') from None
        interface = _text(record.get('interface'))
        if interface in ('N/A', ''):
            interface = None
        rows.append((serial, vdom, tunnel, _text(record.get('device')), namespace,
                     code, regional, binding, status, _aware_time(record.get('coletado_em')),
                     'fortigate_ssh', origin, interface, legacy))
    rows.sort(key=lambda row: row[:3])
    source_hash = hashlib.sha256(raw_source).hexdigest()
    regionals_hash = hashlib.sha256(raw_regionals).hexdigest()
    canonical = json.dumps((source_hash, regionals_hash, codes, rows),
                           default=lambda value: value.isoformat(), separators=(',', ':'), ensure_ascii=True)
    return VPNCatalog(hashlib.sha256(canonical.encode()).hexdigest(), source_hash,
                      regionals_hash, codes, tuple(rows))


def inspect_vpn_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)',
                       (list(catalog.regional_codes),))
        missing = set(catalog.regional_codes) - {row[0] for row in cursor.fetchall()}
        cursor.execute('SELECT count(*) FROM operacional.vpns')
        count = cursor.fetchone()[0]
    return {'vpns_existentes': count, 'tabela_vpns_vazia': count == 0,
            'regionais_do_catalogo_ausentes_no_banco': len(missing)}


def write_vpn_catalog(connection, catalog, *, progress=None):
    """Caller owns commit/rollback; never update a previously loaded VPN table."""
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
        cursor.execute('LOCK TABLE operacional.vpns IN ROW EXCLUSIVE MODE')
        progress.phase = 'contagem_inicial'
        cursor.execute('SELECT count(*) FROM operacional.vpns')
        if cursor.fetchone() != (0,):
            raise ImportErrorSafe('VPNs ja cadastradas. Nao repetir esta carga inicial.')
        cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)',
                       (list(catalog.regional_codes),))
        if {row[0] for row in cursor.fetchall()} != set(catalog.regional_codes):
            raise ImportErrorSafe('Catalogo regional divergente do banco. Carga bloqueada.')
        for row in catalog.rows:
            progress.phase = 'insercao_vpns'
            cursor.execute('''INSERT INTO operacional.vpns
                (firewall_serial,vdom,tunel,dispositivo_nome,dispositivo_namespace,
                 codigo_regional,regional_origem,vinculo_regional,status,coletado_em,
                 via_coleta,vdom_origem,interface,hora_verificacao_legada,
                 arquivo_origem_sha256,catalogo_regionais_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (*row, catalog.source_sha256, catalog.regionals_sha256))
        progress.phase = 'contagem_final'
        cursor.execute('SELECT count(*) FROM operacional.vpns')
        if cursor.fetchone() != (len(catalog.rows),):
            raise ImportErrorSafe('Contagem de VPNs divergente. Transacao cancelada.')
        cursor.execute('SELECT vinculo_regional,count(*) FROM operacional.vpns GROUP BY vinculo_regional')
        if dict(cursor.fetchall()) != dict(Counter(row[7] for row in catalog.rows)):
            raise ImportErrorSafe('Contagem de vinculos divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'output/sentinel_operational_state.json')
    parser.add_argument('--regionals', type=Path, default=ROOT / 'estrutura_regionais.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        catalog = build_vpn_catalog(args.source.read_bytes(), args.regionals.read_bytes())
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao de banco somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato dos dois arquivos revisados.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_vpn_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_vpns_confirmada'
                else:
                    progress.phase = 'conferencia_somente_leitura'
                    result['banco'] = inspect_vpn_catalog(connection, catalog)
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
