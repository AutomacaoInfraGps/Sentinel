"""Read-only regional metadata coverage; no database, manager imports or raw labels."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _time_kind
from scripts.database.audit_server_sources import _read_source, _text

FIELDS = ('nome', 'descricao', 'estado', 'uf')
UFS = frozenset('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())


def _kind(record, field):
    if field not in record:
        return 'ausente'
    value = record[field]
    if value is None:
        return 'nulo'
    if not isinstance(value, str):
        return 'nao_textual'
    if value == '':
        return 'texto_vazio'
    if not value.strip():
        return 'somente_espacos'
    return 'texto_preenchido'


def audit_catalog(payload):
    entries = payload.get('regionais') if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {'estrutura_valida': False}
    fields = {field: Counter() for field in FIELDS}
    states = {field: Counter() for field in ('estado', 'uf')}
    padded = Counter({field: 0 for field in FIELDS})
    lengths = Counter({'nome_acima_240': 0, 'descricao_acima_500': 0})
    codes, names = Counter(), Counter()
    invalid = bad_codes = conflicts = raw_differences = 0
    for code, record in entries.items():
        code_text = _text(code)
        if not code_text or len(code_text) > 120 or code_text != code or code_text != code_text.upper() or '\x00' in code_text:
            bad_codes += 1
        if code_text:
            codes[code_text.upper()] += 1
        if not isinstance(record, dict):
            invalid += 1
            continue
        for field in FIELDS:
            fields[field][_kind(record, field)] += 1
            value = record.get(field)
            padded[field] += isinstance(value, str) and value != value.strip()
        for field in ('estado', 'uf'):
            value = record.get(field)
            text = _text(value)
            category = ('sigla_reconhecida' if text in UFS else
                        'sigla_reconhecida_apos_normalizacao' if text.upper() in UFS else
                        'texto_fora_das_siglas' if text else 'vazio_ausente_ou_nao_textual')
            states[field][category] += 1
        name = _text(record.get('nome'))
        if name:
            names[name.casefold()] += 1
        lengths['nome_acima_240'] += isinstance(record.get('nome'), str) and len(record['nome']) > 240
        lengths['descricao_acima_500'] += isinstance(record.get('descricao'), str) and len(record['descricao']) > 500
        state, uf = _text(record.get('estado')), _text(record.get('uf'))
        conflicts += bool(state and uf and state.upper() != uf.upper())
        raw_differences += bool(state and uf and record['estado'] != record['uf'])
    configuration = payload.get('configuracao')
    publication = configuration.get('ultima_atualizacao') if isinstance(configuration, dict) else None
    return {'estrutura_valida': True, 'regionais': len(entries), 'registros_invalidos': invalid,
            'codigos_fora_do_padrao_sql_atual': bad_codes,
            'codigos_repetidos_apos_normalizacao': sum(count > 1 for count in codes.values()),
            'nomes_repetidos_sem_fusao': sum(count > 1 for count in names.values()),
            'campos_por_situacao': {key: dict(counts) for key, counts in fields.items()},
            'formato_estado_uf': {key: dict(counts) for key, counts in states.items()},
            'espacos_externos_por_campo': dict(padded), 'limites_da_tela_e_projecao_atual': dict(lengths),
            'estado_uf_preenchidos_divergentes_apos_normalizacao': conflicts,
            'estado_uf_preenchidos_textualmente_diferentes': raw_differences,
            'publicacao_cadastro': _time_kind(publication)}


def audit_sources(source=None):
    payload, info = _read_source(Path(source) if source else ROOT / 'estrutura_regionais.json')
    if info['situacao'] == 'lido':
        info.update(audit_catalog(payload))
    return {'modo': 'auditoria_metadados_regionais_somente_leitura_sem_banco',
            'fontes': {'cadastro_regional': info},
            'projecao_sql_referencia_codigo': ['codigo', 'nome', 'presente_no_cadastro'],
            'conferencia_do_banco_executada': False,
            'estado_uf_inferidos': False, 'conflitos_resolvidos_automaticamente': False,
            'nomes_descricoes_enderecos_e_credenciais_exportados': False,
            'gerenciador_importado': False, 'arquivos_modificados': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='JSON de cadastro explicito; padrao estrutura_regionais.json.')
    args = parser.parse_args(argv)
    print(json.dumps(audit_sources(args.source), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
