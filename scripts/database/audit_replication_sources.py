"""Read-only AD replication source coverage; no repadmin, AD, SQL or record exports."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _unique_object, _time_kind

FIELDS = ('nome', 'tipo', 'status', 'delta', 'latencia', 'parceiros', 'falhas',
          'erros', 'replicacoes', 'sucesso_total', 'ultima_replicacao', 'detalhes', 'coletado_em')
TOTAL_FIELDS = ('total_servidores', 'servidores_saudaveis', 'servidores_problemas',
                'controladores', 'replicacao_ok', 'replicacao_erro')


def public_source_path():
    # Same path rules as config._resolve_public_base, without importing its side effects.
    configured = str(os.environ.get('AUTOMACAO_PUBLIC_BASE') or '').strip()
    if configured:
        return Path(configured).expanduser() / 'data/replicacao.json', 'AUTOMACAO_PUBLIC_BASE'
    return Path(os.environ.get('PUBLIC', 'C:/Users/Public')) / 'Automacao/data/replicacao.json', 'PUBLIC_ou_padrao_windows'


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _present(value):
    return value is not None and value != ''


def _integer(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value.strip()):
        return int(value.strip())
    return None


def _publication(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace('Z', '+00:00')).isoformat()
    except ValueError:
        return None


def _ui_total(payload):
    """Reproduce normal valid counts, refusing booleans/negative/unsafe coercions."""
    if not payload:
        return 0
    if not isinstance(payload, dict):
        return None
    for key in ('total_servidores', 'controladores'):
        if payload.get(key) is not None:
            return _integer(payload[key])
    details = payload.get('detalhes') or {}
    controllers = details.get('controladores') if isinstance(details, dict) else None
    if controllers is None:
        return 0
    return len(controllers) if isinstance(controllers, list) else None


def audit_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Invalid replication envelope')
    details = payload.get('detalhes')
    if 'servidores' in payload:
        records, schema = payload['servidores'], 'servidores'
        errors = payload.get('erros_operacionais')
    elif isinstance(details, dict) and 'controladores' in details:
        records, schema = details['controladores'], 'detalhes_controladores'
        errors = details.get('erros_operacionais')
    else:
        records, schema, errors = None, 'sem_lista_reconhecida', None
    totals = {key: _integer(payload[key]) for key in TOTAL_FIELDS if key in payload}
    base = {'formato': schema, 'publicacao': _time_kind(payload.get('timestamp')),
            'publicacao_declarada_iso': _publication(payload.get('timestamp')),
            'totais_declarados_validos': {key: value for key, value in totals.items() if value is not None},
            'totais_declarados_invalidos': sum(value is None for value in totals.values()),
            'total_usado_pela_selecao_da_tela': _ui_total(payload),
            'lista_registros_valida': isinstance(records, list),
            'lista_erros_operacionais_presente': errors is not None,
            'lista_erros_operacionais_valida': isinstance(errors, list),
            'erros_operacionais': len(errors) if isinstance(errors, list) else None,
            'erros_operacionais_nao_textuais': sum(not isinstance(item, str) for item in errors) if isinstance(errors, list) else None}
    if not isinstance(records, list):
        return base
    fields = Counter({key: 0 for key in FIELDS})
    types, statuses, dates, collected, delta_types = Counter(), Counter(), Counter(), Counter(), Counter()
    names, identities = Counter(), Counter()
    short_names = {}
    invalid = missing_names = missing_identity = numeric_invalid = inconsistent = over_total = malformed_ratio = 0
    rows_with_details = 0
    for record in records:
        if not isinstance(record, dict):
            invalid += 1
            continue
        for key in FIELDS:
            fields[key] += _present(record.get(key))
        name = _text(record.get('nome')).casefold()
        direction = _text(record.get('tipo')).casefold()
        type_category = {'origem': 'origem', 'destino': 'destino', 'problema': 'problema'}.get(direction, 'ausente_ou_outro')
        types[type_category] += 1
        if name:
            names[name] += 1
            short_names.setdefault(name.split('.')[0], set()).add(name)
        else:
            missing_names += 1
        if name and direction in ('origem', 'destino', 'problema'):
            identities[(name, direction)] += 1
        else:
            missing_identity += 1
        status = _text(record.get('status')).lower()
        statuses[status if status in ('ok', 'warning', 'error', 'unknown', 'healthy', 'unhealthy') else 'ausente_ou_outro'] += 1
        dates[_time_kind(record.get('ultima_replicacao'))] += 1
        collected[_time_kind(record.get('coletado_em'))] += 1
        delta = record.get('delta') if 'delta' in record else record.get('latencia')
        delta_types['ausente' if not _present(delta) else 'texto' if isinstance(delta, str) else 'nao_textual'] += 1
        numbers = {key: _integer(record[key]) for key in ('parceiros', 'falhas', 'erros', 'replicacoes')
                   if _present(record.get(key))}
        numeric_invalid += sum(value is None for value in numbers.values())
        if numbers.get('falhas') is not None and numbers.get('erros') is not None:
            inconsistent += numbers['falhas'] != numbers['erros']
        if numbers.get('falhas') is not None and numbers.get('parceiros') is not None:
            over_total += numbers['falhas'] > numbers['parceiros']
        if _present(record.get('sucesso_total')):
            ratio = record['sucesso_total']
            malformed_ratio += not isinstance(ratio, str) or re.fullmatch(r'\s*\d+\s*/\s*\d+\s*', ratio) is None
        rows_with_details += _present(record.get('detalhes'))
    return {**base, 'registros': len(records), 'registros_invalidos': invalid,
            'controladores_distintos_por_nome_completo': len(names), 'sem_nome_textual': missing_names,
            'nomes_em_varias_linhas': sum(count > 1 for count in names.values()),
            'identidades_nome_secao_repetidas': sum(count > 1 for count in identities.values()),
            'sem_identidade_nome_secao_explicita': missing_identity,
            'nomes_curtos_com_varias_identidades_completas': sum(len(values) > 1 for values in short_names.values()),
            'por_secao_declarada': dict(types), 'por_status_declarado': dict(statuses),
            'campos_presentes': dict(fields), 'horarios_ultima_replicacao_declarada': dict(dates),
            'horarios_coleta_explicita': dict(collected), 'formato_delta_ou_latencia': dict(delta_types),
            'contadores_invalidos': numeric_invalid, 'linhas_falhas_erros_divergentes': inconsistent,
            'linhas_falhas_maiores_total': over_total, 'sucesso_total_invalido': malformed_ratio,
            'registros_com_detalhes': rows_with_details,
            'total_declarado_difere_de_linhas': base['total_usado_pela_selecao_da_tela'] != len(records)
                if base['total_usado_pela_selecao_da_tela'] is not None else None}


def _read_source(path):
    path = Path(path)
    if not path.is_file():
        return None, {'situacao': 'ausente'}
    try:
        raw = path.read_bytes()
        payload = None
        encoding_used = None
        for encoding in ('utf-8', 'utf-8-sig', 'latin1'):
            try:
                payload = json.loads(raw.decode(encoding), object_pairs_hook=_unique_object)
                encoding_used = encoding
                break
            except (ValueError, UnicodeError):
                continue
        if encoding_used is None:
            raise ValueError('Invalid source')
        info = audit_payload(payload)
        if path.read_bytes() != raw:
            return None, {'situacao': 'alterado_durante_leitura'}
        return payload, {'situacao': 'lido', 'codificacao': encoding_used,
                         'sha256_arquivo': hashlib.sha256(raw).hexdigest(), **info}
    except Exception:
        return None, {'situacao': 'leitura_ou_estrutura_invalida'}


def predict_selection(local, public):
    if not local and not public:
        return 'nenhuma'
    if not local:
        return 'publica'
    if not public:
        return 'local'
    left, right = _ui_total(local), _ui_total(public)
    if left is None or right is None:
        return 'nao_reproduzivel_com_seguranca'
    return 'publica' if right > left else 'local'


def compare_names(local, public):
    def names(payload):
        if not isinstance(payload, dict):
            return None
        if 'servidores' in payload:
            records = payload['servidores']
        else:
            details = payload.get('detalhes')
            records = details.get('controladores') if isinstance(details, dict) else None
        if not isinstance(records, list) or any(
                not isinstance(row, dict) or not _text(row.get('nome')) for row in records):
            return None
        return {_text(row['nome']).casefold() for row in records}

    left, right = names(local), names(public)
    if left is None or right is None:
        return {'comparavel': False}
    return {'comparavel': True, 'nomes_completos_em_comum': len(left & right),
            'nomes_completos_somente_local': len(left - right),
            'nomes_completos_somente_publica': len(right - left),
            'mesmo_conjunto_de_nomes_completos': left == right}


def audit_sources(root=ROOT, public_source=None):
    public_path, origin = public_source_path() if public_source is None else (Path(public_source), 'argumento_explicito')
    local, local_info = _read_source(Path(root) / 'data/replicacao.json')
    public, public_info = _read_source(public_path)
    return {'modo': 'auditoria_replicacao_ad_somente_leitura_sem_banco',
            'fontes': {'local': local_info, 'publica': public_info},
            'comparacao_identidades': compare_names(local, public),
            'resolucao_caminho_publico': origin,
            'selecao_prevista_pela_regra_da_tela': predict_selection(local, public),
            'criterio_da_tela': 'maior_total_declarado_com_preferencia_local_no_empate',
            'selecao_nao_prioriza_data': True,
            'ressalva_fonte_com_falha': any(info['situacao'] not in ('lido', 'ausente') for info in (local_info, public_info)),
            'ultima_replicacao_pode_ser_horario_da_coleta': True,
            'publicacao_e_hash_nao_comprovam_nova_coleta_ad': True,
            'secao_deve_ser_preservada_sem_inferencia': True,
            'sem_inferencia_de_regional': True,
            'nomes_e_erros_brutos_exportados': False,
            'repadmin_executado': False, 'arquivos_modificados': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-source', type=Path,
                        help='Arquivo publico exato, caso o servico use ambiente diferente do terminal.')
    args = parser.parse_args(argv)
    print(json.dumps(audit_sources(public_source=args.public_source), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
