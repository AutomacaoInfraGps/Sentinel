"""Freeze firmware metadata only, without jobs, network queries or PostgreSQL access."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.database.audit_server_sources import _ip
from scripts.database.audit_switch_firmware_sources import COLUMNS, MAX_ROWS, compare_with_cache, read_inventory
from scripts.database.import_firewall_cache import ImportErrorSafe, _unique_keys
from scripts.database.import_server_catalog import _text

SOURCE = 'sentinel_switch_firmware_sqlite'
REASONS = {'enderecos_da_fonte_conflitantes', 'ambiguo_nao_aprovado',
           'candidato_sem_identidade_valida', 'ip_e_nome_apontam_identidades_diferentes',
           'ip_e_nome_concordantes_candidato', 'apenas_ip_candidato_nao_aprovado',
           'apenas_nome_candidato_nao_aprovado', 'sem_correspondencia'}
ENVELOPE = {'version', 'fonte', 'capturado_em', 'sha256_cache_status',
            'sha256_inventario_projetado', 'registros', 'digest_carga'}
MAX_BYTES = 16 * 1024 * 1024


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _json(raw):
    if len(raw) > MAX_BYTES:
        raise ImportErrorSafe('Arquivo acima do limite de leitura.')
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError):
        raise ImportErrorSafe('JSON invalido ou com chaves duplicadas.') from None


def _date(value):
    try:
        text = _text(value, 80, required=True)
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if 'T' not in text or parsed.utcoffset() is None:
            raise ValueError()
        return text
    except (ValueError, OverflowError, TypeError):
        raise ImportErrorSafe('Horario ISO completo com fuso obrigatorio; nenhum fuso sera inferido.') from None


def _rows(records, *, classified=False):
    if not isinstance(records, list) or not 0 < len(records) <= MAX_ROWS:
        raise ImportErrorSafe('Inventario vazio, invalido ou acima do limite.')
    rows, hosts = [], set()
    allowed = set(COLUMNS) | ({'diagnostico_vinculo'} if classified else set())
    for record in records:
        if not isinstance(record, dict) or set(record) != allowed:
            raise ImportErrorSafe('Campos fora do escopo de firmware. Captura bloqueada.')
        row = {key: _text(record[key], 80 if key == 'checked_at_utc' else 255, required=True)
               for key in COLUMNS}
        _date(row['checked_at_utc'])
        if not _ip(row['ip_address']):
            raise ImportErrorSafe('Endereco de firmware invalido.')
        if row['host'].casefold() in hosts:
            raise ImportErrorSafe('Host repetido; nenhum registro sera fundido.')
        hosts.add(row['host'].casefold())
        if row['source'] not in ('webui', 'bulk_webui', 'snmp', 'ssh', 'manual'):
            raise ImportErrorSafe('Origem de firmware exige revisao.')
        if classified:
            reason = record['diagnostico_vinculo']
            if not isinstance(reason, str) or reason not in REASONS:
                raise ImportErrorSafe('Diagnostico de identidade invalido.')
            row['diagnostico_vinculo'] = reason
        rows.append(row)
    return sorted(rows, key=lambda row: row['host'])


def capture(database, cache_path, *, now=None):
    raw = cache_path.read_bytes()
    cache = _json(raw)
    if not isinstance(cache, dict) or not cache or any(not isinstance(record, dict) for record in cache.values()):
        raise ImportErrorSafe('Cache de status ausente, vazio ou invalido.')
    records, info = read_inventory(database)
    if records is None:
        raise ImportErrorSafe('Inventario SQLite indisponivel; captura bloqueada.')
    rows = _rows(records)
    inventory_hash = _hash(rows)
    # Retain the comparison diagnosis, never a chosen device ID or automatic binding.
    for row in rows:
        counts = compare_with_cache([row], cache)['candidatos_sem_aprovacao']
        row['diagnostico_vinculo'] = next(iter(counts))
    if cache_path.read_bytes() != raw:
        raise ImportErrorSafe('Cache mudou durante a captura; repita a simulacao.')
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.utcoffset() is None:
        raise ImportErrorSafe('Horario de captura exige fuso.')
    payload = {'version': 1, 'fonte': SOURCE, 'capturado_em': timestamp.astimezone(timezone.utc).isoformat(),
               'sha256_cache_status': hashlib.sha256(raw).hexdigest(),
               'sha256_inventario_projetado': inventory_hash, 'registros': rows}
    payload['digest_carga'] = _hash(payload)
    return validate(payload)


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != ENVELOPE:
        raise ImportErrorSafe('Formato de captura invalido.')
    if type(payload['version']) is not int or payload['version'] != 1 or payload['fonte'] != SOURCE:
        raise ImportErrorSafe('Versao ou fonte de captura divergente.')
    _date(payload['capturado_em'])
    rows = _rows(payload['registros'], classified=True)
    if rows != payload['registros']:
        raise ImportErrorSafe('Captura nao canonica; nenhuma normalizacao silenciosa sera aplicada.')
    for key in ('sha256_cache_status', 'sha256_inventario_projetado', 'digest_carga'):
        value = payload[key]
        if not isinstance(value, str) or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
            raise ImportErrorSafe('Hash da captura invalido.')
    projected = [{key: row[key] for key in COLUMNS} for row in rows]
    if _hash(projected) != payload['sha256_inventario_projetado']:
        raise ImportErrorSafe('Inventario da captura divergente.')
    if _hash({key: value for key, value in payload.items() if key != 'digest_carga'}) != payload['digest_carga']:
        raise ImportErrorSafe('Digest da captura divergente.')
    return payload


def summary(payload):
    return {key: payload[key] for key in ENVELOPE if key != 'registros'} | {
        'registros': len(payload['registros']),
        'por_diagnostico_vinculo': dict(Counter(row['diagnostico_vinculo'] for row in payload['registros'])),
        'vinculos_aprovados_automaticamente': False, 'jobs_exportados': False,
        'credenciais_exportadas': False, 'equipamentos_consultados': False,
        'postgresql_acessado': False, 'sincronizacao_automatica_firmware': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/switch_updates/scheduled_updates.sqlite3')
    parser.add_argument('--cache', type=Path, default=ROOT / 'output/switches_status_cache.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--output', type=Path, help='Cria um novo JSON congelado; nao sobrescreve arquivo existente.')
    mode.add_argument('--source', type=Path, help='Confere somente um JSON congelado, sem reler fontes atuais.')
    args = parser.parse_args(argv)
    try:
        if args.source:
            raw = args.source.read_bytes()
            payload = validate(_json(raw))
            if args.source.read_bytes() != raw:
                raise ImportErrorSafe('Captura mudou durante a leitura.')
        else:
            payload = capture(args.database, args.cache)
        if args.output:
            encoded = json.dumps(payload, ensure_ascii=True, indent=2)
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(encoded + '\n')
        result = {'modo': 'captura_congelada_sem_postgresql' if args.output else
                  'conferencia_captura_sem_postgresql' if args.source else 'simulacao_sem_conexao_ao_banco',
                  **summary(payload)}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except ImportErrorSafe as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print('Falha na leitura ou captura de firmware. Detalhes internos omitidos.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
