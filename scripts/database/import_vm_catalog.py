"""Bootstrap only the reviewed RJ VM registration, without credentials or telemetry."""

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_vm_sources import STATUSES
from scripts.database.import_firewall_cache import DatabaseProgress, ImportErrorSafe, _database_error, _observation
from scripts.database.import_server_catalog import _identity, _text
from scripts.database.import_switch_catalog import _load

SOURCE_ID = 'sentinel_vm_cadastro'
APPROVED_REGIONAL = 'REG_RIO_DE_JANEIRO'
TABLES = ('fontes_cadastro_vms', 'maquinas_virtuais')
BOOTSTRAP_LOCK = (0x564D5301, 18)
EXCLUDED_FIELDS = ('host_id', 'host_name', 'operatingSystem', 'processors', 'memory',
                   'uptime', 'details', 'coletado_em')


@dataclass(frozen=True, repr=False)
class VMCatalog:
    digest: str
    source_sha256: str
    regionals_sha256: str
    source_timezone: str | None
    regional_codes: tuple
    rows: tuple
    excluded_counts: tuple

    def summary(self):
        return {'digest_carga': self.digest, 'sha256_cadastro_vms': self.source_sha256,
                'sha256_catalogo_regionais': self.regionals_sha256,
                'fuso_verificacao_legada': self.source_timezone, 'vm_cadastradas': len(self.rows),
                'regionais_das_vms': len({row[3] for row in self.rows}),
                'por_status_declarado': dict(Counter(row[7].lower() for row in self.rows)),
                'por_regra_vinculo': dict(Counter(row[5] for row in self.rows)),
                'sem_data_de_verificacao': sum(row[8] is None for row in self.rows),
                'campos_tecnicos_nao_importados': dict(self.excluded_counts),
                'status_eh_declaracao_do_cadastro': True, 'credenciais_importadas': False,
                'telemetria_importada': False, 'servidores_fundidos': False,
                'arquivo_origem_modificado': False, 'sincronizacao_automatica_vms': False}


def _check_time(value, zone):
    value = _text(value, 80)
    if value is None:
        return None
    try:
        if 'T' not in value and ' ' not in value:
            raise ValueError()
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ImportErrorSafe('Verificacao exige data completa valida; nenhuma data sera inferida.') from None
    if moment.utcoffset() is None and zone is None:
        raise ImportErrorSafe('Data legada sem fuso exige --source-timezone explicito.')
    return _observation(value, zone)


def build_vm_catalog(raw_source, raw_regionals, source_timezone=None):
    zone = None
    if source_timezone is not None:
        if not isinstance(source_timezone, str) or not source_timezone:
            raise ImportErrorSafe('Fuso IANA invalido ou indisponivel.')
        try:
            zone = ZoneInfo(source_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ImportErrorSafe('Fuso IANA invalido ou indisponivel.') from None
    records, catalog = _load(raw_source), _load(raw_regionals)
    regions = catalog.get('regionais') if isinstance(catalog, dict) else None
    if not isinstance(regions, dict) or not regions:
        raise ImportErrorSafe('Catalogo regional ausente ou invalido.')
    if not isinstance(regions.get(APPROVED_REGIONAL), dict):
        raise ImportErrorSafe('Regional RJ aprovada ausente no catalogo.')
    if not isinstance(records, list) or not records:
        raise ImportErrorSafe('Cadastro de VMs vazio ou invalido. Carga bloqueada.')
    rows, ids, addresses = [], set(), set()
    excluded = Counter({field: 0 for field in EXCLUDED_FIELDS})
    for record in records:
        if not isinstance(record, dict):
            raise ImportErrorSafe('Registro de VM invalido.')
        identifier = _text(record.get('id'), 240, required=True)
        if identifier != record.get('id') or identifier in ids:
            raise ImportErrorSafe('ID de VM repetido ou com espacos externos. Nenhuma linha foi fundida.')
        ids.add(identifier)
        name = _text(record.get('name'), 240, required=True)
        address = _text(record.get('ip'), 120, required=True)
        try:
            parsed_address = ipaddress.ip_address(address)
            if getattr(parsed_address, 'scope_id', None):
                raise ValueError()
            address = str(parsed_address)
        except ValueError:
            raise ImportErrorSafe('VM exige endereco IP valido. Nenhuma consulta DNS foi realizada.') from None
        if address in addresses:
            raise ImportErrorSafe('IP repetido entre VMs. Revise a identidade antes da carga.')
        addresses.add(address)
        listed = record.get('ipAddresses')
        if listed is not None:
            if not isinstance(listed, list):
                raise ImportErrorSafe('Lista de IPs invalida.')
            try:
                listed_ips = {str(ipaddress.ip_address(_text(item, 120, required=True))) for item in listed}
            except (ValueError, TypeError):
                raise ImportErrorSafe('Lista de IPs invalida.') from None
            if listed_ips and listed_ips != {address}:
                raise ImportErrorSafe('Multiplos IPs ou endereco divergente exigem revisao; nenhum endereco sera descartado.')
        label = _text(record.get('regional'), 240, required=True)
        if label == APPROVED_REGIONAL:
            binding = 'codigo_exato_aprovado'
        elif label.casefold() == 'rio de janeiro':
            binding = 'rotulo_rj_confirmado'
        else:
            raise ImportErrorSafe('Carga inicial restrita ao vinculo RJ confirmado. Revise novas regionais antes de importar.')
        status = _text(record.get('status'), 40, required=True)
        if status.lower() not in STATUSES:
            raise ImportErrorSafe('Status declarado nao reconhecido. Nenhum estado foi inferido.')
        checked = _check_time(record.get('last_check'), zone)
        rows.append((identifier, name, address, APPROVED_REGIONAL, label, binding,
                     _text(record.get('description'), 2000), status, checked))
        for field in EXCLUDED_FIELDS:
            value = record.get(field)
            excluded[field] += value is not None and value != '' and value != [] and value != {}
    rows.sort(key=lambda row: row[0])
    hashes = hashlib.sha256(raw_source).hexdigest(), hashlib.sha256(raw_regionals).hexdigest()
    canonical = (SOURCE_ID, hashes, source_timezone, rows)
    digest = hashlib.sha256(json.dumps(canonical, default=lambda value: value.isoformat(),
                                      ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    return VMCatalog(digest, *hashes, source_timezone, (APPROVED_REGIONAL,), tuple(rows), tuple(sorted(excluded.items())))


def _inspect(cursor, catalog):
    cursor.execute('SELECT codigo FROM operacional.regionais WHERE codigo=ANY(%s)', (list(catalog.regional_codes),))
    missing = len(set(catalog.regional_codes) - {row[0] for row in cursor.fetchall()})
    counts = {}
    for table in TABLES:
        cursor.execute('SELECT count(*) FROM operacional.' + table)
        counts[table] = cursor.fetchone()[0]
    return {'regionais_das_vms_ausentes_no_banco': missing, 'contagens': counts,
            'tabelas_cadastro_vms_vazias': not any(counts.values())}


def inspect_vm_catalog(connection, catalog):
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='5s'")
        _identity(cursor)
        return _inspect(cursor, catalog)


def write_vm_catalog(connection, catalog, *, progress=None):
    progress = progress or DatabaseProgress()
    with connection.cursor() as cursor:
        progress.phase = 'validacao_destino'
        cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        _identity(cursor)
        cursor.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', BOOTSTRAP_LOCK)
        if cursor.fetchone() != (True,):
            raise ImportErrorSafe('Outra carga de VMs em andamento. Nao repetir agora.')
        cursor.execute('LOCK TABLE operacional.regionais IN ACCESS SHARE MODE')
        for table in TABLES:
            cursor.execute('LOCK TABLE operacional.' + table + ' IN ROW EXCLUSIVE MODE')
        progress.phase = 'conferencia_destino'
        inspection = _inspect(cursor, catalog)
        if not inspection['tabelas_cadastro_vms_vazias']:
            raise ImportErrorSafe('Cadastro de VMs ja carregado. Nao repetir a carga inicial.')
        if inspection['regionais_das_vms_ausentes_no_banco']:
            raise ImportErrorSafe('Regional RJ ausente no banco. Carga bloqueada.')
        progress.phase = 'insercao_cadastro_vms'
        cursor.execute('INSERT INTO operacional.fontes_cadastro_vms '
                       '(id,arquivo_origem_sha256,catalogo_regionais_sha256,fuso_verificacao_legada,digest_carga) '
                       'VALUES (%s,%s,%s,%s,%s)',
                       (SOURCE_ID, catalog.source_sha256, catalog.regionals_sha256, catalog.source_timezone, catalog.digest))
        for row in catalog.rows:
            cursor.execute('INSERT INTO operacional.maquinas_virtuais '
                           '(fonte_id,id_origem,nome,ip,codigo_regional,regional_origem,regra_vinculo,'
                           'descricao,status_declarado,ultima_verificacao) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                           (SOURCE_ID, *row))
        progress.phase = 'conferencia_final'
        cursor.execute('SELECT count(*) FROM operacional.fontes_cadastro_vms')
        if cursor.fetchone() != (1,):
            raise ImportErrorSafe('Contagem de fontes divergente. Transacao cancelada.')
        cursor.execute('SELECT id_origem,nome,host(ip),codigo_regional,regional_origem,regra_vinculo,'
                       'descricao,status_declarado,ultima_verificacao FROM operacional.maquinas_virtuais '
                       'WHERE fonte_id=%s ORDER BY id_origem', (SOURCE_ID,))
        readback = []
        for row in cursor.fetchall():
            try:
                address = str(ipaddress.ip_address(row[2]))
            except (ValueError, TypeError):
                raise ImportErrorSafe('Endereco divergente na conferencia SQL. Transacao cancelada.') from None
            readback.append((*row[:2], address, *row[3:]))
        if tuple(readback) != catalog.rows:
            raise ImportErrorSafe('Conferencia final de VMs divergente. Transacao cancelada.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--regionals', type=Path)
    parser.add_argument('--source-timezone')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-database', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args(argv)
    progress = DatabaseProgress(phase='leitura_origem')
    try:
        if (args.apply or args.check_database) and (args.source is None or args.regionals is None):
            raise ImportErrorSafe('Operacao SQL exige --source e --regionals com copias revisadas.')
        source = args.source or ROOT / 'data/vms.json'
        regionals = args.regionals or ROOT / 'estrutura_regionais.json'
        catalog = build_vm_catalog(source.read_bytes(), regionals.read_bytes(), args.source_timezone)
        result = {'modo': 'simulacao_sem_conexao_ao_banco', **catalog.summary()}
        if args.apply or args.check_database:
            if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
                raise ImportErrorSafe('Execute a operacao SQL somente no Rigel.')
            if args.apply and args.expected_digest != catalog.digest:
                raise ImportErrorSafe('Gravacao exige o digest exato da simulacao revisada.')
            from services.operational_postgres import connect_collector
            progress.phase = 'conexao'
            with connect_collector(read_only=not args.apply) as connection:
                if args.apply:
                    write_vm_catalog(connection, catalog, progress=progress)
                    result['modo'] = 'carga_inicial_cadastro_vms_confirmada'
                else:
                    result['banco'] = inspect_vm_catalog(connection, catalog)
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
