"""Operator diagnostic: one read-only SSH query, no SQL or cache writes."""

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def diagnose_output(output):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output)
    fields = {}
    for line in text.splitlines():
        label, separator, value = line.partition(':')
        if separator:
            fields.setdefault(label.strip().casefold(), set()).add(value.strip())
    values = fields.get('current virtual domain', set())
    vdom = None
    if not values:
        status = 'campo_ausente'
    elif len(values) != 1:
        status = 'valores_conflitantes'
    else:
        value = next(iter(values))
        if value.casefold() == 'global':
            status = 'contexto_global'
        elif (not value or len(value) > 240
              or not re.fullmatch(r'[A-Za-z0-9_.-]+', value)
              or value.casefold() in {'unknown', 'n/a'}):
            status = 'valor_vazio_ou_invalido'
        else:
            status, vdom = 'identificado', value
    configuration = fields.get('virtual domain configuration', set())
    configuration = next(iter(configuration)) if len(configuration) == 1 else None
    return {
        'modo': 'diagnostico_contexto_ssh_somente_leitura',
        'serial_presente': bool(fields.get('serial-number')),
        'hostname_presente': bool(fields.get('hostname')),
        'campo_vdom_presente': bool(values),
        'situacao_vdom': status, 'vdom': vdom,
        'configuracao_vdom': configuration if configuration in ('enable', 'disable', 'multiple')
        else 'ausente_ou_nao_reconhecida',
    }


def query_context(ssh, credentials, *, filtered_vdom=False):
    try:
        ssh.connect(hostname=credentials['host'], port=2222,
                    username=credentials['username'], password=credentials['password'],
                    timeout=10, auth_timeout=10, banner_timeout=10,
                    look_for_keys=False, allow_agent=False)
        command = ('get system status | grep "Current virtual domain"'
                   if filtered_vdom else 'get system status')
        _, stdout, _ = ssh.exec_command(command, timeout=10)
        raw = stdout.read(65537)
        if len(raw) > 65536:
            raise ValueError('Resposta excede o limite do diagnostico.')
        output = raw.decode(errors='replace')
        return {**diagnose_output(output), 'consulta_filtrada_vdom': filtered_vdom,
                'bytes_recebidos': len(raw),
                'marcador_paginacao_detectado': bool(re.search(r'--\s*more\s*--', output, re.IGNORECASE))}
    finally:
        ssh.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--filtered-vdom', action='store_true',
                        help='Consulta somente a linha de VDOM via grep no FortiGate.')
    args = parser.parse_args(argv)
    if os.environ.get('COMPUTERNAME', '').upper() != 'RIGEL':
        parser.error('Execute somente no Rigel, na conta Windows do coletor.')
    try:
        import paramiko
        from core.environment_loader import load_environment_file, resolve_credential_references
        from core.secret_store import JsonSecretStore

        config = load_environment_file(ROOT / 'environment.json', resolve_secrets=False)
        target = config.get('fortigate', {})
        if not isinstance(target, dict):
            raise ValueError()
        if 'host' not in target:
            target = next((entry for entry in target.values()
                           if isinstance(entry, dict) and entry.get('host')), {})
        # Resolve only the three needed settings, not the entire environment.
        credentials = resolve_credential_references(
            {key: target.get(key) for key in ('host', 'username', 'password')},
            secret_store=JsonSecretStore())
        if any(not isinstance(value, str) or not value for value in credentials.values()):
            raise ValueError()
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        report = query_context(ssh, credentials, filtered_vdom=args.filtered_vdom)
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 0
    except Exception:
        print('Falha no diagnostico. Confira acesso DPAPI, autenticacao e chave SSH ja verificada. '
              'Nenhum dado foi gravado; detalhes omitidos.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
