"""Audit saved UniFi radio projections without devices, SQL or raw identifiers."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _mac, _time_kind, _unique_object

METRICS = ('cu_total', 'cu_self_tx', 'cu_self_rx', 'tx_retry')


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _percent(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 100 and math.isfinite(value))


def _channel(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    return isinstance(value, str) and value.strip().isascii() and value.strip().isdigit() and int(value.strip()) > 0


def audit_radio(payload):
    if not isinstance(payload, dict):
        raise ValueError('Invalid envelope')
    aps = payload.get('aps')
    groups = payload.get('interferencia_5ghz_por_site')
    if not isinstance(aps, list) or not isinstance(groups, dict):
        raise ValueError('Invalid inventories')
    inventory = Counter()
    valid_identities = Counter()
    inventory_counts = Counter()
    for ap in aps:
        if not isinstance(ap, dict):
            inventory_counts['registros_invalidos'] += 1
            continue
        key = (_text(ap.get('site')), _text(ap.get('nome')))
        if not all(key):
            inventory_counts['sem_site_ou_nome_textual'] += 1
            continue
        inventory[key] += 1
        if _mac(ap.get('mac')) and _text(ap.get('site_id')):
            valid_identities[key] += 1
    counts, candidates, dates, channels, risks = (Counter() for _ in range(5))
    metrics = {field: Counter() for field in METRICS}
    radio_keys = Counter()
    for site, entries in groups.items():
        if not _text(site):
            counts['sites_sem_rotulo_textual'] += 1
        if not isinstance(entries, list):
            counts['listas_canais_invalidas'] += 1
            continue
        for entry in entries:
            counts['grupos_canais'] += 1
            if not isinstance(entry, dict):
                counts['grupos_canais_invalidos'] += 1
                continue
            channels['inteiro_positivo' if _channel(entry.get('canal')) else 'ausente_ou_invalido'] += 1
            rows = entry.get('aps')
            if not isinstance(rows, list):
                counts['listas_aps_invalidas'] += 1
                continue
            declared = entry.get('qtd_aps')
            if type(declared) is not int or declared < 0:
                counts['quantidades_declaradas_invalidas'] += 1
            elif declared != len(rows):
                counts['quantidades_declaradas_divergentes'] += 1
            for row in rows:
                counts['registros_radio'] += 1
                if not isinstance(row, dict):
                    counts['registros_radio_invalidos'] += 1
                    continue
                key = (_text(site), _text(row.get('nome')))
                if not all(key):
                    reason = 'sem_site_ou_nome_textual'
                elif inventory[key] > 1:
                    reason = 'ambiguo_por_site_nome'
                elif inventory[key] == 1 and valid_identities[key] == 1:
                    reason = 'candidato_unico_por_site_nome_sem_aprovacao'
                elif inventory[key] == 1:
                    reason = 'inventario_sem_mac_ou_site_id_validos'
                else:
                    reason = 'sem_correspondencia'
                candidates[reason] += 1
                if all(key):
                    radio_keys[key] += 1
                counts['com_mac_valido_no_registro_radio'] += _mac(row.get('mac')) is not None
                counts['com_site_id_no_registro_radio'] += bool(_text(row.get('site_id')))
                counts['com_id_radio_textual'] += bool(_text(row.get('radio_id')))
                dates[_time_kind(row.get('coletado_em'))] += 1
                for field in METRICS:
                    value = row.get(field)
                    kind = ('ausente_ou_nulo' if value is None else
                            'percentual_valido' if _percent(value) else 'invalido')
                    metrics[field][kind] += 1
                    if _percent(value) and value == 0:
                        metrics[field]['zeros_sem_comprovacao_de_medicao'] += 1
                if all(_percent(row.get(field)) for field in ('cu_total', 'cu_self_tx', 'cu_self_rx')):
                    counts['tx_rx_proprios_maiores_que_total'] += row['cu_self_tx'] + row['cu_self_rx'] > row['cu_total']
                risk = row.get('risco')
                risks[risk if isinstance(risk, str) and risk in ('OK', 'ATENCAO', 'CRITICO') else 'ausente_ou_outro'] += 1
    return {
        'situacao': 'lido', 'publicacao': _time_kind(payload.get('timestamp')),
        'aps_no_inventario': len(aps), 'sites_na_projecao_radio': len(groups),
        'inventario': dict(inventory_counts), 'contagens': dict(counts),
        'formato_canais': dict(channels), 'candidatos_por_site_nome': dict(candidates),
        'site_nome_repetidos_no_inventario': sum(n > 1 for n in inventory.values()),
        'site_nome_em_varios_registros_radio': sum(n > 1 for n in radio_keys.values()),
        'identidades_inventario_sem_linha_radio': sum(n for key, n in inventory.items() if key not in radio_keys),
        'metricas': {field: dict(values) for field, values in metrics.items()},
        'coleta_explicita_por_registro_radio': dict(dates),
        'riscos_declarados_sem_recalculo': dict(risks),
    }


def audit_sources(root=ROOT):
    report = {
        'modo': 'auditoria_radios_aps_somente_leitura_sem_banco', 'fontes': {},
        'vinculos_aprovados_automaticamente': False,
        'zeros_podem_ser_defaults_do_coletor': True,
        'projecao_exclui_canal_auto_ou_ausente': True,
        'ausencia_de_linha_radio_nao_prova_ausencia_de_radio': True,
        'publicacao_nao_comprova_medicao_individual': True,
        'identidades_metricas_brutas_e_credenciais_exportadas': False,
        'coletor_executado': False, 'postgresql_acessado': False,
        'arquivos_modificados': False,
    }
    try:
        raw = (Path(root) / 'data/unifi.json').read_bytes()
        payload = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
        result = audit_radio(payload)
        result['sha256_arquivo'] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, RecursionError):
        result = {'situacao': 'ausente_ou_invalido'}
    report['fontes']['projecao_radio_unifi'] = result
    return report


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(audit_sources(), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
