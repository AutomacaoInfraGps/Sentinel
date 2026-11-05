"""Caminhos internos e configuracao operacional da Revisao de Acessos."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
DATA_ROOT = PROJECT_ROOT / 'instance' / 'access_review'
CODE_ROOT = PACKAGE_ROOT / 'automation'
AREAS = {
    'windows': ('Servidores Windows', 'ServidoresWindows'),
    'linux': ('Linux', 'Linux'),
    'admanager': ('ADManager Plus', 'ADManager'),
    'firewalls': ('Firewalls', 'Firewalls'),
}
MODELS = {
    'windows': 'Auditoria Galaxia Servidores Windows - Exemplo.docx',
    'linux': 'Auditoria Galaxia Linux - Exemplo.docx',
    'admanager': 'Auditoria Galaxia ADManager - Exemplo.docx',
    'firewalls': 'Auditoria Galaxia Firewalls - Exemplo.docx',
}

EVIDENCE_SLOTS = {
    'linux': ('p005_1', 'p023_1', 'p024_1'),
    'admanager': ('p003_1', 'p005_1'),
    'firewalls': ('p005_1', 'p008_1', 'p014_1'),
}


class ConfigurationError(ValueError):
    pass


def _diagnostic(code, message, action, area=None):
    return {'code': code, 'area': area, 'message': message, 'action': action}


def _read_object(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError()
    return value


def _remount_diagnostics(root, area):
    """Confirma apenas os insumos necessarios antes de oferecer a remontagem."""
    label, folder = AREAS[area]
    evidence = root / 'dados' / 'evidencias' / folder
    missing = []
    if area == 'windows':
        inventory_path = root / 'dados' / 'execucoes' / 'Inventario-Evidencias-ServidoresWindows.json'
        try:
            inventory = _read_object(inventory_path)
            slots = {
                item.get('slot') for item in inventory.get('slots', [])
                if isinstance(item, dict) and isinstance(item.get('slot'), str)
                and re.fullmatch(r'[A-Za-z0-9_-]+', item['slot'])
            }
            if not slots:
                raise ValueError()
            missing = [slot for slot in slots if not (evidence / f'{slot}.png').is_file()]
        except (OSError, ValueError):
            missing = ['inventario']
    else:
        missing = [slot for slot in EVIDENCE_SLOTS[area] if not (evidence / f'{slot}.png').is_file()]

    if area == 'firewalls':
        result_path = root / 'dados' / 'execucoes' / folder / 'Resultado-AuditoriaFirewalls.json'
        try:
            result = _read_object(result_path)
            regionals = result.get('regionais', [])
            if not isinstance(regionals, list):
                raise ValueError()
            evidence_root = evidence.resolve()
            for item in regionals:
                name = item.get('evidencia') if isinstance(item, dict) else None
                if not isinstance(name, str) or not name.strip():
                    raise ValueError()
                target = (evidence / name).resolve()
                if not target.is_relative_to(evidence_root) or not target.is_file():
                    missing.append('regional')
        except (OSError, ValueError):
            missing.append('resultado')

    if missing:
        return [_diagnostic(
            'remount_evidence_missing',
            f'{label}: a remontagem ainda não está disponível.',
            'Execute primeiro uma revisão completa. A remontagem só é liberada quando todas as evidências necessárias da coleta anterior estão preservadas.',
            area,
        )]
    return []


def load_settings(root=DATA_ROOT):
    try:
        config = json.loads((Path(root) / 'config' / 'auditorias.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ConfigurationError('Configure config/auditorias.json na Revisao de Acessos.') from exc
    if not isinstance(config, dict):
        raise ConfigurationError('A configuracao de auditorias deve ser um objeto JSON.')
    for key, default, low, high in (
        ('tentativas', 2, 1, 10), ('intervalo_segundos', 10, 0, 300),
        ('timeout_seconds', 21600, 60, 43200), ('retention_days', 180, 1, 3650),
        ('max_events', 1000, 10, 10000),
    ):
        value = config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigurationError(f'Valor invalido em auditorias.json: {key}.')
        config[key] = value
    enabled = config.get('areas', list(AREAS))
    if not isinstance(enabled, list) or not enabled or any(a not in AREAS for a in enabled):
        raise ConfigurationError('Areas habilitadas invalidas em auditorias.json.')
    config['areas'] = enabled
    if not isinstance(config.get('remover_prints_apos_validacao', True), bool):
        raise ConfigurationError('remover_prints_apos_validacao deve ser booleano.')
    return config


def configuration_diagnostics(root=DATA_ROOT, selected=None, mode='completa'):
    root = Path(root)
    diagnostics = []
    try:
        config = load_settings(root)
    except ConfigurationError as exc:
        return [_diagnostic(
            'audit_settings_invalid',
            'A Revisão de Acessos precisa concluir a configuração inicial.',
            str(exc),
        )]
    areas = selected or config['areas']
    for area in areas:
        if area not in AREAS:
            diagnostics.append(_diagnostic(
                'area_invalid', 'Uma área selecionada não é reconhecida.',
                'Atualize a página e selecione novamente as revisões.',
            ))
            continue
        label = AREAS[area][0]
        if area not in config['areas']:
            diagnostics.append(_diagnostic(
                'area_disabled', f'{label} está desabilitada.',
                'Habilite essa área na configuração geral da Revisão de Acessos.', area,
            ))
        if not (root / 'modelos' / MODELS[area]).is_file():
            diagnostics.append(_diagnostic(
                'model_missing', f'{label}: o modelo do relatório não foi encontrado.',
                'Disponibilize o modelo DOCX esperado antes de executar esta revisão.', area,
            ))
        if mode == 'completa' and area != 'windows':
            path = root / 'config' / f'{area}.json'
            try:
                values = _read_object(path)
                keys = {'linux': ('zabbix_url', 'grafana_url'), 'admanager': ('admanager_url',),
                        'firewalls': ('fortianalyzer_url', 'fortimanager_url', 'fortianalyzer_adom', 'fortimanager_adom')}[area]
                if any(not isinstance(values.get(k), str) or not values[k].strip() for k in keys):
                    diagnostics.append(_diagnostic(
                        'required_config_missing', f'{label}: faltam informações obrigatórias.',
                        f'Preencha os endereços e demais campos de config/{area}.json.', area,
                    ))
                    continue
                if any(not isinstance(values.get(k, default), bool) for k, default in (('verify_tls', True), ('allow_http', False))):
                    diagnostics.append(_diagnostic(
                        'security_option_invalid', f'{label}: as opções de segurança são inválidas.',
                        'Use true ou false nos campos verify_tls e allow_http.', area,
                    ))
                    continue
                for key in keys:
                    if key.endswith('_url'):
                        url = urlsplit(values[key])
                        if not url.hostname or url.username or url.password or url.fragment:
                            diagnostics.append(_diagnostic(
                                'url_invalid', f'{label}: um endereço configurado não é válido.',
                                'Informe uma URL sem usuário, senha ou fragmento no endereço.', area,
                            ))
                            break
                        if url.scheme != 'https' and not (url.scheme == 'http' and values.get('allow_http') is True):
                            action = ('O ADManager deste ambiente usa HTTP. Defina allow_http como true em config/admanager.json.'
                                      if area == 'admanager' and url.scheme == 'http' else
                                      'Use HTTPS ou solicite a aprovação da exceção allow_http para esse serviço interno.')
                            diagnostics.append(_diagnostic(
                                'http_not_allowed', f'{label}: o endereço HTTP ainda não foi autorizado.',
                                action, area,
                            ))
                            break
            except (OSError, ValueError):
                diagnostics.append(_diagnostic(
                    'area_config_invalid', f'{label}: a configuração não pôde ser validada.',
                    f'Revise o arquivo config/{area}.json e confirme se o JSON está completo.', area,
                ))
        elif mode == 'somente_montagem':
            diagnostics.extend(_remount_diagnostics(root, area))
    if mode == 'completa' and any(a != 'windows' for a in areas):
        if not (root / 'credentials' / 'credentials.json').is_file():
            diagnostics.append(_diagnostic(
                'credential_manifest_missing',
                'As referências de acesso dos sistemas ainda não foram preparadas.',
                'Execute a preparação do módulo e depois cadastre os acessos no cofre conforme as instruções da Revisão de Acessos.',
            ))
    return diagnostics


def configuration_issues(root=DATA_ROOT, selected=None, mode='completa'):
    return [f"{item['message']} {item['action']}" for item in configuration_diagnostics(root, selected, mode)]
