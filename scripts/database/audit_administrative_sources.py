"""Read-only coverage; optional unresolved labels never include accounts or contacts."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _read, _time_kind
from services.sla_contact_matching import resolve_sla_contact_regional
from unifi_site_matching import normalize_unifi_site

ROLES = (('diretor', 'NOME_DIRETOR_1', 'EMAIL_DIRETOR'),
         ('gerente', 'NOME_GERENTE', 'EMAIL_GERENTE'),
         ('apoio_1', 'NOME_APOIO_1', 'EMAIL_APOIO_1'),
         ('apoio_2', 'NOME_APOIO_2', 'EMAIL_APOIO_2'))
CONTACT_COLUMNS = ('NOME_REGIONAL', 'NOME_REG_FORTI', *(column for _, name, email in ROLES for column in (name, email)))


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _filled(value):
    text = _text(value)
    return bool(text and not text.upper().startswith('SEM_'))


def _list_stats(value):
    if not isinstance(value, list):
        return None
    valid = [item for item in value if isinstance(item, str) and item.strip()]
    return {'contas': len(valid), 'invalidos': len(value) - len(valid),
            'duplicados_exatos': len(valid) - len(set(valid))}


def audit_admins(cache, baseline, firewalls, regionals, *, unresolved=False):
    devices = cache.get('dispositivos') if isinstance(cache, dict) else None
    if not isinstance(devices, dict) or not isinstance(baseline, dict):
        raise ValueError('Invalid admin source')
    index = defaultdict(set)
    groups = firewalls.get('firewalls_por_regional') if isinstance(firewalls, dict) else None
    if not isinstance(groups, dict):
        raise ValueError('Invalid firewall source')
    for code, items in groups.items():
        if code not in regionals or not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and _text(item.get('nome')):
                index[item['nome'].strip().casefold()].add(code)
    result = {'dispositivos': len(devices), 'por_tipo': Counter(),
              'consulta_valida_declarada': Counter(), 'vinculo_por_nome_exato_firewall': Counter(),
              'horarios_ultima_coleta_valida': Counter(), 'com_serial': 0,
              'com_alerta': 0, 'consulta_indisponivel': 0, 'monitoramento_limitado': 0,
              'contas_no_cache_incluindo_dados_anteriores': 0, 'listas_admins_invalidas': 0,
              'contas_cache_invalidas': 0, 'contas_cache_duplicadas_exatas': 0,
              'baseline_dispositivos': len(baseline), 'baseline_contas': 0,
              'baseline_listas_invalidas': 0, 'baseline_contas_invalidas': 0,
              'baseline_duplicados_exatos': 0,
              'baseline_dispositivos_fora_do_cache': sum(key not in devices for key in baseline),
              'dispositivos_sem_entrada_baseline': sum(key not in baseline for key in devices)}
    details = []
    for device_key, device in devices.items():
        if not isinstance(device, dict):
            raise ValueError('Invalid admin device')
        kind = device.get('tipo')
        result['por_tipo'][kind if kind in ('fortigate', 'fortimanager', 'fortianalyzer') else 'outro'] += 1
        valid = device.get('consulta_valida')
        result['consulta_valida_declarada']['sim' if valid is True else 'nao' if valid is False else 'ausente_ou_invalida'] += 1
        result['horarios_ultima_coleta_valida'][_time_kind(device.get('ultima_coleta_valida'))] += 1
        result['com_serial'] += bool(_text(device.get('serial') or device.get('firewall_serial')))
        result['com_alerta'] += bool(device.get('novos') or device.get('removidos'))
        result['consulta_indisponivel'] += device.get('consulta_indisponivel') is True
        result['monitoramento_limitado'] += device.get('monitoramento_limitado') is True
        matches = index.get(_text(device.get('nome')).casefold(), set())
        binding = ('central_sem_regional' if kind in ('fortimanager', 'fortianalyzer') else
                   'unico' if len(matches) == 1 else 'ambiguo' if matches else 'nao_encontrado')
        result['vinculo_por_nome_exato_firewall'][binding] += 1
        if unresolved and binding in ('ambiguo', 'nao_encontrado'):
            details.append({'chave_dispositivo': _text(device_key),
                            'nome_dispositivo': _text(device.get('nome')),
                            'motivo': binding, 'candidatos_regionais': sorted(matches)})
        stats = _list_stats(device.get('admins'))
        result['listas_admins_invalidas'] += stats is None
        if stats:
            result['contas_no_cache_incluindo_dados_anteriores'] += stats['contas']
            result['contas_cache_invalidas'] += stats['invalidos']
            result['contas_cache_duplicadas_exatas'] += stats['duplicados_exatos']
    for entries in baseline.values():
        stats = _list_stats(entries)
        result['baseline_listas_invalidas'] += stats is None
        if stats:
            result['baseline_contas'] += stats['contas']
            result['baseline_contas_invalidas'] += stats['invalidos']
            result['baseline_duplicados_exatos'] += stats['duplicados_exatos']
    result['publicacao'] = _time_kind(cache.get('atualizado_em'))
    if unresolved:
        result['pendencias_identidade'] = {
            'equipamentos_sem_vinculo_unico': details,
            'chaves_baseline_fora_do_cache': sorted(_text(key) for key in baseline if key not in devices),
        }
    return result


def audit_contacts(records, regionals, *, unresolved=False):
    names, forti_names, links = Counter(), Counter(), Counter()
    rules = Counter()
    details = []
    roles = {role: {'com_nome': 0, 'com_email': 0, 'nome_sem_email': 0, 'email_sem_nome': 0}
             for role, _, _ in ROLES}
    for record in records:
        name, forti = (_text(record.get(key)) for key in ('NOME_REGIONAL', 'NOME_REG_FORTI'))
        if name:
            names[normalize_unifi_site(name)] += 1
        if forti:
            forti_names[forti.casefold()] += 1
        code, reason, matches = resolve_sla_contact_regional(regionals, name, forti)
        rules[reason] += 1
        links['candidato_unico' if code else 'ambiguo' if matches else 'nao_encontrado'] += 1
        if unresolved and code is None:
            details.append({'rotulo_regional_sla': name, 'rotulo_fortianalyzer': forti,
                            'motivo': reason,
                            'candidatos_regionais': sorted(matches)})
        for role, name_col, email_col in ROLES:
            has_name, has_email = _filled(record.get(name_col)), _filled(record.get(email_col))
            roles[role]['com_nome'] += has_name
            roles[role]['com_email'] += has_email
            roles[role]['nome_sem_email'] += has_name and not has_email
            roles[role]['email_sem_nome'] += has_email and not has_name
    result = {'linhas': len(records), 'regionais_sem_rotulo': sum(not _text(row.get('NOME_REGIONAL')) for row in records),
            'rotulos_regionais_duplicados_normalizados': sum(count > 1 for count in names.values()),
            'rotulos_fortianalyzer_duplicados': sum(count > 1 for count in forti_names.values()),
            'candidatos_regionais_por_codigo_ou_nome_sem_aproximacao': dict(links),
            'por_regra_vinculo_regional': dict(rules),
            'por_papel': roles, 'vinculos_aprovados_pela_auditoria': False}
    if unresolved:
        result['rotulos_sem_vinculo_unico'] = details
    return result


def _contacts_from_workbook(path, sheet_name, regionals, *, unresolved=False):
    # Read formulas as formulas: cached formula results must not masquerade as contacts.
    from openpyxl import load_workbook
    with Path(path).open('rb') as stream:
        workbook = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        try:
            if sheet_name and sheet_name not in workbook.sheetnames:
                return {'situacao': 'aba_configurada_ausente'}
            sheet = workbook[sheet_name or workbook.sheetnames[0]]
            iterator = sheet.iter_rows()
            header = next(iterator, ())
            headers = [_text(cell.value) for cell in header]
            counts = Counter(headers)
            if any(counts[column] != 1 for column in CONTACT_COLUMNS):
                return {'situacao': 'colunas_obrigatorias_ausentes_ou_duplicadas'}
            positions = {column: headers.index(column) for column in CONTACT_COLUMNS}
            records, formulas = [], 0
            for cells in iterator:
                record = {}
                for column, index in positions.items():
                    cell = cells[index] if index < len(cells) else None
                    if cell is not None and cell.data_type == 'f':
                        formulas += 1
                    record[column] = '' if cell is None or cell.value is None else str(cell.value).strip()
                if any(record.values()):
                    records.append(record)
            if formulas:
                return {'situacao': 'formulas_exigem_revisao', 'celulas_com_formula': formulas}
            return {'situacao': 'lido', **audit_contacts(records, regionals, unresolved=unresolved)}
        finally:
            workbook.close()


def audit_sources(root=ROOT, *, unresolved=False):
    root = Path(root)
    report = {'modo': 'auditoria_administrativa_somente_leitura_sem_banco', 'fontes': {}}
    try:
        environment = _read(root / 'environment.json')
        catalog = _read(root / 'estrutura_regionais.json')
        regions = catalog['regionais']
        if not isinstance(environment, dict) or not isinstance(regions, dict) or not regions or any(not isinstance(item, dict) for item in regions.values()):
            raise ValueError('Invalid config')
    except Exception:
        report['fontes']['configuracao'] = {'situacao': 'configuracao_ou_catalogo_invalido'}
        return report
    report['regionais_no_catalogo'] = len(regions)
    try:
        section = environment.get('fortianalyzer') or {}
        baseline_name = section.get('admin_baseline_file', 'admin_baseline.json')
        baseline_path = Path(baseline_name)
        if not baseline_path.is_absolute():
            baseline_path = root / baseline_path
        result = audit_admins(_read(root / 'output/dashboard_admins_cache.json'), _read(baseline_path),
                              _read(root / 'output/dashboard_firewalls_cache.json'), regions, unresolved=unresolved)
        report['fontes']['monitor_admins'] = {'situacao': 'lido', **result}
    except Exception:
        report['fontes']['monitor_admins'] = {'situacao': 'fonte_ausente_ou_invalida'}
    try:
        section = environment.get('email_contatos') or {}
        configured = section.get('xlsx_path')
        if not isinstance(configured, str) or not configured.strip():
            report['fontes']['contatos_sla'] = {'situacao': 'planilha_nao_configurada'}
        else:
            path = Path(configured).expanduser()
            if not path.is_absolute() or path.suffix.lower() != '.xlsx':
                report['fontes']['contatos_sla'] = {'situacao': 'caminho_absoluto_xlsx_exigido'}
            else:
                report['fontes']['contatos_sla'] = _contacts_from_workbook(
                    path, section.get('sheet_name') or '', regions, unresolved=unresolved)
    except ImportError:
        report['fontes']['contatos_sla'] = {'situacao': 'dependencia_openpyxl_ausente'}
    except Exception:
        report['fontes']['contatos_sla'] = {'situacao': 'fonte_ausente_ou_leitura_invalida'}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unresolved', action='store_true',
                        help='Exibe somente identificadores pendentes de equipamento e rotulos regionais, sem contas ou dados pessoais.')
    args = parser.parse_args(argv)
    print(json.dumps(audit_sources(unresolved=args.unresolved), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
