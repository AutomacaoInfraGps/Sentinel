"""Read-only certificate metadata audit; no WinRM, collector, vault or SQL calls."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_ap_sources import _unique_object, _time_kind

ALIASES = {'thumbprint': ('thumbprint', 'Thumbprint'), 'subject': ('subject', 'Subject'),
           'issuer': ('issuer', 'Issuer'), 'notAfter': ('notAfter', 'NotAfter')}
SENSITIVE_KEYS = {'privatekey', 'private_key', 'password', 'senha', 'pfx', 'pfxdata',
                  'pem', 'rawdata', 'certificatebytes', 'token', 'credential', 'credentials'}


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _thumbprint(value):
    compact = ''.join(_text(value).split()).upper()
    if re.fullmatch(r'[0-9A-F]{40}|[0-9A-F]{64}', compact):
        return compact
    return None


def _expiration(value, now):
    kind = _time_kind(value)
    if kind != 'com_fuso':
        return kind, 'nao_classificada_sem_data_com_fuso'
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    seconds = (parsed - now).total_seconds()
    return kind, 'expirado' if seconds < 0 else 'a_vencer_menos_30_dias' if seconds < 30 * 86400 else 'valido_30_dias_ou_mais'


def audit_payload(payload, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError('Audit time requires timezone')
    if not isinstance(payload, (dict, list)):
        raise ValueError('Invalid certificate envelope')
    records = [payload] if isinstance(payload, dict) else payload
    fields = Counter({key: 0 for key in ALIASES})
    nontext = Counter({key: 0 for key in ALIASES})
    dates, validity, thumb_formats, collection_times = Counter(), Counter(), Counter(), Counter()
    fingerprints, subjects = Counter(), Counter()
    variants = defaultdict(set)
    invalid = conflicts = sensitive = private_flag = host = store = collected = 0
    for record in records:
        if not isinstance(record, dict):
            invalid += 1
            continue
        values = {}
        for field, (lower, upper) in ALIASES.items():
            # Same alias priority as the page; conflicting aliases remain a diagnostic.
            values[field] = record.get(lower) or record.get(upper)
            if record.get(lower) and record.get(upper) and record[lower] != record[upper]:
                conflicts += 1
            value = values[field]
            fields[field] += bool(_text(value))
            nontext[field] += value is not None and not isinstance(value, str)
        fingerprint = _thumbprint(values['thumbprint'])
        if fingerprint:
            fingerprints[fingerprint] += 1
            thumb_formats['hex_40' if len(fingerprint) == 40 else 'hex_64'] += 1
            variants[fingerprint].add(tuple(_text(values[key]) for key in ('subject', 'issuer', 'notAfter')))
        else:
            thumb_formats['ausente' if not _text(values['thumbprint']) else 'formato_nao_reconhecido'] += 1
        subject = _text(values['subject'])
        if subject:
            subjects[subject.casefold()] += 1
        kind, status = _expiration(values['notAfter'], now)
        dates[kind] += 1
        validity[status] += 1
        keys = {key.casefold() for key in record}
        sensitive += bool(keys & SENSITIVE_KEYS)
        private_flag += bool(keys & {'hasprivatekey', 'has_private_key'})
        host += any(_text(record.get(key)) for key in ('host', 'servidor', 'hostname', 'computerName', 'PSComputerName'))
        store += any(_text(record.get(key)) for key in ('store', 'storePath', 'certificate_store'))
        stamp = record.get('coletado_em') or record.get('collected_at')
        collected += bool(_text(stamp))
        collection_times[_time_kind(stamp)] += 1
    return {'formato': 'objeto_unico' if isinstance(payload, dict) else 'lista',
            'registros': len(records), 'registros_invalidos': invalid,
            'campos_textuais_preenchidos': dict(fields), 'campos_nao_textuais': dict(nontext),
            'conflitos_entre_aliases': conflicts, 'formato_thumbprint': dict(thumb_formats),
            'thumbprints_distintos_reconhecidos': len(fingerprints),
            'thumbprints_repetidos': sum(count > 1 for count in fingerprints.values()),
            'thumbprints_com_metadados_divergentes': sum(len(values) > 1 for values in variants.values()),
            'assuntos_repetidos_sem_fusao': sum(count > 1 for count in subjects.values()),
            'vencimentos_por_formato': dict(dates), 'validade_apenas_datas_com_fuso': dict(validity),
            'registros_com_host_explicito': host, 'registros_com_repositorio_explicito': store,
            'registros_com_data_coleta_textual': collected, 'coleta_explicita_por_registro': dict(collection_times),
            'registros_com_campos_potencialmente_sensiveis': sensitive,
            'registros_com_indicador_de_chave_privada': private_flag}


def audit_sources(root=ROOT, now=None):
    now = now or datetime.now(timezone.utc)
    path = Path(root) / 'certificate_disk_report_acrab.json'
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
        summary = audit_payload(payload, now)
        if path.read_bytes() != raw:
            source = {'situacao': 'alterado_durante_leitura'}
        else:
            source = {'situacao': 'lido', 'sha256_arquivo': hashlib.sha256(raw).hexdigest(),
                      'bom_utf8_presente': raw.startswith(b'\xef\xbb\xbf'), **summary}
    except FileNotFoundError:
        source = {'situacao': 'ausente'}
    except Exception:
        source = {'situacao': 'leitura_ou_estrutura_invalida'}
    return {'modo': 'auditoria_certificados_somente_leitura_sem_banco',
            'auditado_em_utc': now.astimezone(timezone.utc).isoformat(),
            'fontes': {'relatorio_certificados': source},
            'identidades_ou_dados_brutos_exportados': False,
            'datas_sem_fuso_nao_convertidas': True,
            'mtime_nao_usado_como_data_de_coleta': True,
            'vencimento_nao_comprova_confianca_ou_uso_do_certificado': True,
            'vinculos_host_regional_nao_inferidos': True,
            'coletor_executado': False, 'cofre_acessado': False,
            'arquivos_modificados': False}


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(json.dumps(audit_sources(), indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
