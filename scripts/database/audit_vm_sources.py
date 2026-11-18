"""Read-only VM source coverage, without SQL, device calls, secrets or record exports."""

import argparse
from collections import Counter, defaultdict
import ipaddress
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _read, _time_kind
from unifi_site_matching import normalize_unifi_site

FIELDS = ('id', 'name', 'ip', 'ipAddresses', 'regional', 'description', 'status',
          'last_check', 'host_id', 'host_name', 'operatingSystem', 'processors', 'memory',
          'uptime', 'details', 'coletado_em')
STATUSES = {'running', 'stopped', 'unknown', 'unreachable', 'online', 'offline',
            'paused', 'saved', 'starting', 'stopping', 'error'}


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _ip(value):
    text = _text(value)
    if not text:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _present(value):
    return value is not None and value != '' and value != [] and value != {}


def _regional_candidates(label, regions):
    if not label:
        return 'ausente', ()
    if label in regions:
        return 'codigo_exato', (label,)
    exact = tuple(sorted(code for code, region in regions.items()
                         if _text(region.get('nome')).casefold() == label.casefold()))
    if exact:
        return ('nome_exato_candidato_unico' if len(exact) == 1 else 'ambiguo'), exact
    normalized = normalize_unifi_site(label)
    matches = tuple(sorted(code for code, region in regions.items()
                           if normalized and normalized in {normalize_unifi_site(code),
                                                            normalize_unifi_site(_text(region.get('nome')))}))
    if matches:
        return ('normalizacao_candidata_unica' if len(matches) == 1 else 'ambiguo'), matches
    if label.upper().startswith('RG_'):
        target = 'REG_' + label[3:].upper()
        if target in regions:
            return 'prefixo_rg_candidato_nao_aprovado', (target,)
    return 'nao_encontrado', ()


def audit_records(records, regions, *, unresolved=False):
    if not isinstance(records, list):
        raise ValueError('Invalid VM envelope')
    fields = Counter({field: 0 for field in FIELDS})
    statuses, times, collected, bindings = Counter(), Counter(), Counter(), Counter()
    ids, names, address_counts, host_identities = Counter(), Counter(), Counter(), Counter()
    servers_by_ip = defaultdict(set)
    server_lists_invalid = 0
    for code, regional in regions.items():
        servers = regional.get('servidores', [])
        if not isinstance(servers, list):
            server_lists_invalid += 1
            continue
        for index, server in enumerate(servers):
            address = _ip(server.get('ip')) if isinstance(server, dict) else None
            if address:
                servers_by_ip[address].add((code, index))
    invalid = missing_id = nontext_id = padded_id = invalid_ip = invalid_lists = invalid_list_items = 0
    with_address = conflicting_addresses = with_details = invalid_details = 0
    possible_credentials = 0
    server_matches = Counter()
    pending = Counter()
    candidates_by_label = {}
    for vm in records:
        if not isinstance(vm, dict):
            invalid += 1
            continue
        for field in FIELDS:
            fields[field] += _present(vm.get(field))
        identifier = _text(vm.get('id'))
        if not identifier:
            missing_id += 1
        nontext_id += vm.get('id') is not None and not isinstance(vm.get('id'), str)
        padded_id += isinstance(vm.get('id'), str) and vm['id'] != identifier
        if identifier:
            ids[identifier] += 1
        name = _text(vm.get('name'))
        if name:
            names[name.casefold()] += 1
        host = _text(vm.get('host_id'))
        if host and identifier:
            host_identities[(host, identifier)] += 1
        status = _text(vm.get('status')).lower()
        statuses[status if status in STATUSES else 'outro_ou_ausente'] += 1
        times[_time_kind(vm.get('last_check'))] += 1
        collected[_time_kind(vm.get('coletado_em'))] += 1
        label = _text(vm.get('regional'))
        reason, candidates = _regional_candidates(label, regions)
        bindings[reason] += 1
        if unresolved and reason not in ('codigo_exato', 'nome_exato_candidato_unico'):
            pending[(label, reason)] += 1
            candidates_by_label[(label, reason)] = candidates
        primary = _ip(vm.get('ip'))
        invalid_ip += _present(vm.get('ip')) and primary is None
        listed = vm.get('ipAddresses')
        if listed is not None and not isinstance(listed, list):
            invalid_lists += 1
            listed = []
        raw_items = listed or []
        listed_addresses = {_ip(item) for item in raw_items if _ip(item)}
        invalid_list_items += sum(_ip(item) is None for item in raw_items)
        addresses = listed_addresses | ({primary} if primary else set())
        with_address += bool(addresses)
        conflicting_addresses += bool(primary and listed_addresses and primary not in listed_addresses)
        address_counts.update(addresses)
        matches = set().union(*(servers_by_ip[address] for address in addresses)) if addresses else set()
        server_matches['candidato_unico_por_ip' if len(matches) == 1 else
                       'varios_candidatos_por_ip' if matches else 'sem_correspondencia_por_ip'] += 1
        detail = vm.get('details')
        with_details += isinstance(detail, dict) and bool(detail)
        invalid_details += detail is not None and not isinstance(detail, dict)
        possible_credentials += any(_present(vm.get(key)) for key in
                                    ('username', 'password', 'senha', 'token', 'credential_ref', 'password_ref'))
    result = {'registros': len(records), 'registros_invalidos': invalid,
              'campos_presentes': dict(fields), 'por_status_declarado': dict(statuses),
              'horarios_ultima_verificacao': dict(times), 'horarios_coleta_explicita': dict(collected),
              'sem_id_textual': missing_id, 'ids_nao_textuais': nontext_id, 'ids_com_espacos_externos': padded_id,
              'ids_repetidos': sum(count > 1 for count in ids.values()),
              'nomes_repetidos_ignorando_maiusculas': sum(count > 1 for count in names.values()),
              'identidades_host_id_vm_id_repetidas': sum(count > 1 for count in host_identities.values()),
              'com_endereco_ip_valido': with_address, 'enderecos_principais_invalidos': invalid_ip,
              'listas_ip_invalidas': invalid_lists, 'itens_ip_invalidos': invalid_list_items,
              'ip_principal_fora_da_lista': conflicting_addresses,
              'ips_presentes_em_varios_registros': sum(count > 1 for count in address_counts.values()),
              'vinculo_regional_candidato': dict(bindings), 'vinculos_aprovados_pela_auditoria': False,
              'comparacao_com_cadastro_servidores': dict(server_matches),
              'listas_servidores_invalidas': server_lists_invalid,
              'registros_com_details': with_details, 'details_invalidos': invalid_details,
              'registros_com_campos_de_acesso_preenchidos': possible_credentials,
              'credenciais_exportadas': False, 'registros_fundidos_com_servidores': False,
              'detalhes_armazenados_nao_comprovam_medicao_real': True,
              'status_running_nao_comprova_estado_do_hipervisor': True}
    if unresolved:
        result['rotulos_regionais_pendentes'] = [
            {'rotulo_regional': label, 'motivo': reason, 'vms': count,
             'candidatos_regionais': list(candidates_by_label[(label, reason)])}
            for (label, reason), count in sorted(pending.items())]
    return result


def audit_sources(root=ROOT, *, unresolved=False):
    root = Path(root)
    report = {'modo': 'auditoria_vms_somente_leitura_sem_banco', 'fontes': {}}
    try:
        catalog = _read(root / 'estrutura_regionais.json')
        regions = catalog.get('regionais') if isinstance(catalog, dict) else None
        if not isinstance(regions, dict) or not regions or any(not isinstance(item, dict) for item in regions.values()):
            raise ValueError('Invalid regionals')
        report['fontes']['catalogo_regional'] = {'situacao': 'lido', 'regionais': len(regions)}
    except Exception:
        report['fontes']['catalogo_regional'] = {'situacao': 'ausente_ou_invalido'}
        return report
    path = root / 'data/vms.json'
    if not path.is_file():
        report['fontes']['cadastro_vms'] = {'situacao': 'ausente_arquivo_nao_criado'}
        return report
    try:
        payload = _read(path)
        report['fontes']['cadastro_vms'] = {'situacao': 'lido', **audit_records(payload, regions, unresolved=unresolved)}
    except Exception:
        report['fontes']['cadastro_vms'] = {'situacao': 'leitura_ou_estrutura_invalida'}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unresolved', action='store_true',
                        help='Exibe somente rotulos regionais pendentes; nunca nomes, IPs ou contas das VMs.')
    args = parser.parse_args(argv)
    print(json.dumps(audit_sources(unresolved=args.unresolved), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
