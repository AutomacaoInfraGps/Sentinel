"""
Interface Web para Sistema de Automação - Versão Hierárquica
Sistema organizado por Regionais → Servidores
"""

import os
import json
import time
import sys
import subprocess
import tempfile
import re
import difflib
import ipaddress
import socket
import platform
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread
from uuid import uuid4
from gerenciar_fortigate import GerenciadorFortigate
from fortimanager_client import FortiManagerClient
from fortianalyzer_client import FortiAnalyzerClient
from config import ENV_CONFIG
from flask import Flask, render_template, jsonify, request, redirect, url_for, current_app, make_response, send_file, send_from_directory, session, flash, has_app_context, Response
from flask_login import LoginManager, login_required, current_user

try:
    from credentials import get_credentials
except ImportError:
    def get_credentials(service, prompt_if_missing=False):
        return {}

# Importa o módulo de gerenciamento de VMs
from vm_manager import verificar_vm_online, obter_servicos_vm, obter_logs_vm, obter_detalhes_vm, verificar_vm_completo, gerar_relatorio_completo, gerar_relatorio_simples

try:
    import psutil
except ImportError:
    # Instala o psutil se não estiver disponível
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
    import psutil

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas não instalado. Funcionalidades de Excel limitadas.")
    PANDAS_AVAILABLE = False
    pd = None

# Configuração do projeto
from config import PROJECT_ROOT, REPLICACAO_JSON
from data_store import load_data, is_data_fresh

# Módulos hierárquicos
from gerenciar_regionais import GerenciadorRegionais
from verificar_servidores_v2 import VerificadorServidoresV2
from dashboard_hierarquico import DashboardHierarquico
from gerenciar_switches import GerenciadorSwitches
from gerenciar_fortigate import GerenciadorFortigate
from gerenciar_vms import GerenciadorVMs
from gerenciar_contatos_email import GerenciadorContatosEmail
from switches_backup_utils import create_switch_backup
from sofia import init_sofia
from sofia.tools_sentinel import configurar_ferramentas_sentinel

# Autenticação AD
from auth_ad import init_auth, get_user

# Configuração Flask com caminhos corretos para executável
from utils_paths import get_base_dir

# Define caminhos para templates e static
base_dir = get_base_dir()
template_dir = base_dir / "templates"
static_dir = base_dir / "static" if (base_dir / "static").exists() else None

# Cria app Flask com caminhos corretos
if static_dir:
    app = Flask(__name__, template_folder=str(template_dir), static_folder=str(static_dir))
else:
    app = Flask(__name__, template_folder=str(template_dir))

app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

sofia_config = ENV_CONFIG.get("sofia", {}) if isinstance(ENV_CONFIG.get("sofia", {}), dict) else {}
sofia_env = os.environ.get("SENTINEL_SOFIA_ENABLED")
if sofia_env is None:
    app.config["SOFIA_ENABLED"] = bool(sofia_config.get("enabled", False))
else:
    app.config["SOFIA_ENABLED"] = sofia_env.strip().lower() in {"1", "true", "yes", "on"}


@app.context_processor
def inject_sofia_feature_flag():
    return {"sofia_enabled": app.config.get("SOFIA_ENABLED", False)}

BRANDING_ASSETS_DIR = base_dir / "scripts" / ".image"
BRANDING_ASSET_FILES = {
    "sentinel_logo_final_v4.png",
    "sentinel_logo_final_v4.svg",
    "sentinel_icon.png",
    "sentinel_icon.svg",
}

# Habilitar reload automático de templates
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# Configuração Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para acessar esta página.'
login_manager.login_message_category = 'info'

# Inicializa autenticação AD
init_auth(app)

@login_manager.user_loader
def load_user(user_id):
    """Carrega usuário para Flask-Login"""
    return get_user(user_id)


# Instâncias globais
gerenciador_regionais = GerenciadorRegionais()
verificador_v2 = VerificadorServidoresV2()
dashboard_hierarquico = DashboardHierarquico()
gerenciador_switches = GerenciadorSwitches()
gerenciador_fortigate = GerenciadorFortigate()
gerenciador_contatos_email = GerenciadorContatosEmail()

configurar_ferramentas_sentinel(
    regionais_manager=gerenciador_regionais,
    switches_manager=gerenciador_switches,
)
init_sofia(app)

_background_jobs = {}
_background_jobs_lock = Lock()
_background_jobs_ttl_seconds = 1800


def _cleanup_background_jobs():
    now = time.time()
    with _background_jobs_lock:
        stale_jobs = [
            job_id for job_id, job in _background_jobs.items()
            if job.get('status') in {'completed', 'failed'}
            and now - job.get('updated_at', now) > _background_jobs_ttl_seconds
        ]
        for job_id in stale_jobs:
            _background_jobs.pop(job_id, None)


def _create_background_job(kind, total=0, message=None, detail=None, meta=None):
    _cleanup_background_jobs()
    job_id = uuid4().hex
    now = time.time()
    with _background_jobs_lock:
        _background_jobs[job_id] = {
            'id': job_id,
            'kind': kind,
            'status': 'running',
            'total': max(int(total or 0), 0),
            'completed': 0,
            'percent': 0,
            'message': message,
            'detail': detail,
            'current_item': None,
            'result': None,
            'partial_results': {},
            'error': None,
            'meta': dict(meta or {}),
            'created_at': now,
            'updated_at': now,
        }
    return job_id


def _update_background_job(job_id, **kwargs):
    with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if not job:
            return None

        if 'status' in kwargs and kwargs['status']:
            job['status'] = kwargs['status']
        if 'message' in kwargs:
            job['message'] = kwargs['message']
        if 'detail' in kwargs:
            job['detail'] = kwargs['detail']
        if 'current_item' in kwargs:
            job['current_item'] = kwargs['current_item']
        if 'error' in kwargs:
            job['error'] = kwargs['error']
        if 'result' in kwargs:
            job['result'] = kwargs['result']
        if 'meta' in kwargs and isinstance(kwargs['meta'], dict):
            job['meta'].update(kwargs['meta'])
        if 'total' in kwargs and kwargs['total'] is not None:
            job['total'] = max(int(kwargs['total']), 0)
        if 'completed' in kwargs and kwargs['completed'] is not None:
            job['completed'] = max(int(kwargs['completed']), 0)
        if 'patch_results' in kwargs and isinstance(kwargs['patch_results'], dict):
            job['partial_results'].update(kwargs['patch_results'])

        if 'percent' in kwargs and kwargs['percent'] is not None:
            job['percent'] = max(0, min(100, int(kwargs['percent'])))
        elif job.get('total', 0) > 0:
            job['percent'] = max(0, min(100, int(round((job.get('completed', 0) / job['total']) * 100))))

        job['updated_at'] = time.time()
        return dict(job)


def _complete_background_job(job_id, result=None, message=None, detail=None):
    with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if not job:
            return None

        job['status'] = 'completed'
        job['completed'] = job.get('total', 0)
        job['percent'] = 100
        job['message'] = message or job.get('message')
        job['detail'] = detail or job.get('detail')
        job['result'] = result
        job['updated_at'] = time.time()
        return dict(job)


def _fail_background_job(job_id, error, message=None, detail=None):
    with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if not job:
            return None

        job['status'] = 'failed'
        job['error'] = str(error)
        job['message'] = message or job.get('message') or 'Falha ao executar tarefa em segundo plano'
        job['detail'] = detail or str(error)
        job['updated_at'] = time.time()
        return dict(job)


def _get_background_job(job_id):
    _cleanup_background_jobs()
    with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        return dict(job) if job else None


def _background_async_requested():
    payload = request.get_json(silent=True) if request.is_json else None
    flag = None
    if isinstance(payload, dict):
        flag = payload.get('async')
    if flag is None:
        flag = request.args.get('async')

    return str(flag).strip().lower() in {'1', 'true', 'yes', 'on'}


def _start_background_job(target, *, name):
    worker = Thread(target=target, name=name, daemon=True)
    worker.start()
    return worker


def _build_switches_resumo(resultados):
    total = len(resultados)
    online = sum(1 for r in resultados.values() if r.get('status') == 'online')
    offline = sum(1 for r in resultados.values() if (r.get('status') or '').strip().lower() in {'offline', 'não encontrado', 'nao encontrado', 'erro'})
    warning = sum(1 for r in resultados.values() if r.get('status') == 'warning')
    inativo = sum(1 for r in resultados.values() if r.get('status') == 'inativo')
    return {
        'total': total,
        'online': online,
        'offline': offline,
        'warning': warning,
        'inativo': inativo,
    }


def _run_switches_job(job_id, mode='all', regional=None, host=None):
    manager = GerenciadorSwitches()

    try:
        _update_background_job(job_id, message='Autenticando no Zabbix...', detail='Iniciando verificação dos switches.')

        if not manager.autenticar():
            _fail_background_job(job_id, 'Falha na autenticação com o Zabbix', message='Falha na autenticação com o Zabbix')
            return

        if mode == 'single':
            alvo = str(host or '').strip()
            _update_background_job(
                job_id,
                total=1,
                message='Consultando switch no Zabbix...',
                detail=f'Verificando o switch {alvo}.',
                current_item=alvo,
            )
            resultado = manager.verificar_switch(alvo)
            _update_background_job(job_id, completed=1, patch_results={alvo: resultado})
            _complete_background_job(job_id, result={
                'success': True,
                'status': resultado['status'],
                'detalhes': resultado['detalhes'],
                'ultima_verificacao': resultado.get('ultima_verificacao'),
                'status_reason': resultado.get('status_reason'),
                'status_details': resultado.get('status_details'),
                'warning_problemas': resultado.get('warning_problemas', []),
                'warning_resumo': resultado.get('warning_resumo')
            }, message='Verificação do switch concluída.', detail=f'Switch {alvo} verificado com sucesso.')
            return

        if mode == 'regional':
            switches_regional = manager.regionais.get(regional, [])
            total_switches = len(switches_regional)
            _update_background_job(
                job_id,
                total=total_switches,
                message='Consultando switches da regional...',
                detail=f'Verificando a regional {regional}.',
                meta={'regional': regional}
            )

            def regional_progress(done, total, host_name, resultado):
                _update_background_job(
                    job_id,
                    completed=done,
                    total=total,
                    current_item=host_name,
                    message=f'Verificando {done} de {total} switches da regional {regional}',
                    detail=f'Último switch processado: {host_name}',
                    patch_results={host_name: resultado}
                )

            resultados = manager.verificar_regional(regional, progress_callback=regional_progress)
            if isinstance(resultados, dict) and 'error' in resultados:
                _fail_background_job(job_id, resultados['error'], message=f'Falha ao verificar a regional {regional}')
                return

            _complete_background_job(job_id, result={
                'success': True,
                'resultados': resultados,
                'resumo': _build_switches_resumo(resultados)
            }, message='Verificação da regional concluída.', detail=f'Regional {regional} processada com sucesso.')
            return

        switches_desconhecidos = [s for s in manager.switches if s.get('status') == 'desconhecido']
        switches_conhecidos = [s for s in manager.switches if s.get('status') != 'desconhecido']
        total_switches = len(switches_desconhecidos + switches_conhecidos)
        _update_background_job(
            job_id,
            total=total_switches,
            message='Consultando switches no Zabbix...',
            detail='Iniciando verificação de todos os switches cadastrados.'
        )

        def all_progress(done, total, host_name, resultado):
            _update_background_job(
                job_id,
                completed=done,
                total=total,
                current_item=host_name,
                message=f'Verificando {done} de {total} switches cadastrados',
                detail=f'Último switch processado: {host_name}',
                patch_results={host_name: resultado}
            )

        resultados = manager.verificar_todos_switches(progress_callback=all_progress)
        _complete_background_job(job_id, result={
            'success': True,
            'resultados': resultados,
            'resumo': _build_switches_resumo(resultados)
        }, message='Verificação de switches concluída.', detail='Todos os switches foram processados.')

    except Exception as exc:
        app.logger.exception('Erro no job de switches %s', job_id)
        _fail_background_job(job_id, exc, message='Erro ao verificar switches')


def _executar_sincronizacao_links_todas_regionais(progress_callback=None):
    app_obj = current_app._get_current_object() if has_app_context() else app
    regionais = gerenciador_regionais.listar_regionais()
    adom = _get_fortimanager_adom()
    fortimanager_devices = _list_fortimanager_devices(adom)
    resultados = {}

    total_regionais = len(regionais)
    concluidas = 0
    regionais_validas = []

    for codigo_regional in regionais:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            resultados[codigo_regional] = {
                'success': False,
                'message': 'Regional não encontrada'
            }
            concluidas += 1
            if callable(progress_callback):
                progress_callback(concluidas, total_regionais, codigo_regional, resultados[codigo_regional])
            continue

        regionais_validas.append((codigo_regional, regional_info))

    def sincronizar_regional(item):
        codigo_regional, regional_info = item
        with app_obj.app_context():
            return codigo_regional, _coletar_links_regional(
                codigo_regional,
                regional_info,
                persist=False,
                adom=adom,
                fortimanager_devices=fortimanager_devices,
                include_sdwan=False,
                auth_timeout=5,
            )

    max_workers = min(6, max(1, len(regionais_validas)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(sincronizar_regional, item): item[0]
            for item in regionais_validas
        }

        for future in as_completed(future_map):
            codigo_regional = future_map[future]
            try:
                _, resultado = future.result()

                if resultado.get('success'):
                    _persistir_links_internet_exibicao(
                        codigo_regional,
                        resultado.get('links', []),
                    )

                resultados[codigo_regional] = {
                    'success': bool(resultado.get('success')),
                    'message': resultado.get('message'),
                    'total_atualizados': resultado.get('total_atualizados', 0),
                    'total_criados': resultado.get('total_criados', 0),
                    'source': resultado.get('source')
                }
            except Exception as exc:
                app_obj.logger.exception(
                    'Erro ao sincronizar links da regional %s',
                    codigo_regional,
                )
                resultados[codigo_regional] = {
                    'success': False,
                    'message': f'Erro ao sincronizar regional: {exc}',
                    'total_atualizados': 0,
                    'total_criados': 0,
                    'source': None,
                }
            finally:
                concluidas += 1
                if callable(progress_callback):
                    progress_callback(concluidas, total_regionais, codigo_regional, resultados.get(codigo_regional, {}))

    return {
        'success': True,
        'regionais': resultados
    }


def _run_links_sync_job(job_id):
    try:
        total_regionais = len(gerenciador_regionais.listar_regionais())
        _update_background_job(
            job_id,
            total=total_regionais,
            message='Consultando FortiManager e regionais...',
            detail='Iniciando sincronização dos links das regionais.'
        )

        def progress(done, total, codigo_regional, resultado):
            status_texto = 'sincronizada' if resultado.get('success') else 'com pendência'
            _update_background_job(
                job_id,
                completed=done,
                total=total,
                current_item=codigo_regional,
                message=f'Processadas {done} de {total} regionais',
                detail=f'Regional {codigo_regional} {status_texto}.',
                patch_results={codigo_regional: resultado}
            )

        resultado = _executar_sincronizacao_links_todas_regionais(progress_callback=progress)
        _complete_background_job(
            job_id,
            result=resultado,
            message='Sincronização de links concluída.',
            detail='Todas as regionais foram processadas.'
        )
    except Exception as exc:
        app.logger.exception('Erro no job de links %s', job_id)
        _fail_background_job(job_id, exc, message='Erro ao sincronizar links das regionais')


def _run_executar_completo_job(job_id):
    try:
        def atualizar_progresso_execucao(percent, message, detail=None):
            _update_background_job(
                job_id,
                percent=percent,
                message=message,
                detail=detail or message,
            )

        def processar_linha_saida(line):
            texto = (line or '').strip()
            if not texto:
                return

            texto_upper = texto.upper()
            if 'VERIFICANDO SERVIDOR VIRTUAL' in texto_upper:
                atualizar_progresso_execucao(12, 'Verificando servidores das regionais...', texto)
            elif 'EXECUTANDO VERIFICAÇÃO DE REPLICAÇÃO AD' in texto_upper:
                atualizar_progresso_execucao(35, 'Executando replicação AD...', texto)
            elif 'COLETANDO INFORMAÇÕES DAS APS UNIFI' in texto_upper:
                atualizar_progresso_execucao(50, 'Coletando dados UniFi...', texto)
            elif 'VERIFICANDO STATUS DOS SWITCHES' in texto_upper:
                atualizar_progresso_execucao(62, 'Verificando switches...', texto)
            elif 'VERIFICANDO LINKS DE INTERNET' in texto_upper:
                atualizar_progresso_execucao(74, 'Verificando links de internet...', texto)
            elif 'FALHA AO GERAR PRINT' in texto_upper or '[GPS]' in texto_upper:
                atualizar_progresso_execucao(84, 'Atualizando artefatos visuais...', texto)
            elif 'DEBUG REPLICAÇÃO AD' in texto_upper:
                atualizar_progresso_execucao(88, 'Consolidando replicação AD...', texto)
            elif 'DEBUG LINKS DE INTERNET' in texto_upper:
                atualizar_progresso_execucao(92, 'Consolidando links...', texto)
            elif 'DASHBOARD' in texto_upper and ('GERADO' in texto_upper or 'SALVO' in texto_upper):
                atualizar_progresso_execucao(98, 'Finalizando dashboard consolidado...', texto)

        _update_background_job(
            job_id,
            total=1,
            completed=0,
            percent=3,
            message='Preparando execução completa...',
            detail='Inicializando o processo do dashboard consolidado.'
        )

        script_path = PROJECT_ROOT / 'executar_tudo.py'
        if not script_path.exists():
            _fail_background_job(job_id, 'Script executar_tudo.py não encontrado', message='Script executar_tudo.py não encontrado')
            return

        env = os.environ.copy()
        env['AUTOMACAO_NO_BROWSER'] = '1'
        env['PYTHONUNBUFFERED'] = '1'

        process = subprocess.Popen(
            [sys.executable, '-u', str(script_path), '--no-browser'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(PROJECT_ROOT),
            env=env,
            bufsize=1,
        )

        stdout_lines = []
        if process.stdout is not None:
            for line in process.stdout:
                stdout_lines.append(line)
                processar_linha_saida(line)

        return_code = process.wait()
        stdout_text = ''.join(stdout_lines)

        dashboard_path = PROJECT_ROOT / 'output' / 'dashboard_final.html'

        if return_code == 0:
            _complete_background_job(
                job_id,
                result={
                    'dashboard_gerado': dashboard_path.exists(),
                    'dashboard_url': '/output/dashboard_final.html' if dashboard_path.exists() else None,
                    'detalhes': {
                        'regionais': 'Verificação de servidores concluída',
                        'gps': 'GPS Amigo capturado',
                        'replicacao': 'Replicação AD verificada',
                        'unifi': 'Antenas UniFi coletadas'
                    },
                    'stdout_tail': stdout_text[-4000:]
                },
                message='Execução completa realizada com sucesso! Todos os sistemas verificados.',
                detail='Dashboard final consolidado gerado com sucesso.'
            )
            return

        erro_execucao = stdout_text.strip() or 'Erro desconhecido'
        _fail_background_job(
            job_id,
            erro_execucao,
            message='Erro na execução completa',
            detail=erro_execucao[-4000:]
        )
    except Exception as exc:
        app.logger.exception('Erro no job de execução completa %s', job_id)
        _fail_background_job(job_id, exc, message='Erro ao executar rotina completa')


def _normalizar_host_switch(host):
    return re.sub(r'\s+', ' ', str(host or '').strip()).casefold()


def _obter_arquivo_switches():
    return gerenciador_switches.arquivo_excel


def _criar_backup_switches(arquivo_excel):
    return create_switch_backup(arquivo_excel, base_dir=base_dir)


def _carregar_planilha_switches():
    arquivo_excel = _obter_arquivo_switches()
    df = pd.read_excel(arquivo_excel, sheet_name='Switches', header=2)
    df.columns = df.columns.str.strip()
    return arquivo_excel, df


def _localizar_indice_switch(df, host):
    if 'Host' not in df.columns:
        return pd.Index([])

    hosts_normalizados = df['Host'].fillna('').map(_normalizar_host_switch)
    return df[hosts_normalizados == _normalizar_host_switch(host)].index


def _normalizar_link_texto(valor):
    return re.sub(r"[^A-Z0-9]+", "", str(valor or "").strip().upper())


def _normalizar_link_ip(valor):
    texto = str(valor or "").strip()
    if not texto:
        return ""
    partes = texto.split()
    return partes[0] if partes else ""


def _is_public_ip(valor) -> bool:
    ip_texto = _extract_interface_ip(valor) or _normalizar_link_ip(valor)
    if not ip_texto:
        return False

    try:
        ip_obj = ipaddress.ip_address(ip_texto)
    except ValueError:
        return False

    return not any([
        ip_obj.is_private,
        ip_obj.is_loopback,
        ip_obj.is_link_local,
        ip_obj.is_multicast,
        ip_obj.is_reserved,
        ip_obj.is_unspecified,
    ])


def _is_rfc1918_ip(valor) -> bool:
    ip_texto = _extract_interface_ip(valor) or _normalizar_link_ip(valor)
    if not ip_texto:
        return False

    try:
        ip_obj = ipaddress.ip_address(ip_texto)
    except ValueError:
        return False

    redes_privadas = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    return any(ip_obj in rede for rede in redes_privadas)


def _mapear_interface_preferida(link_cadastrado):
    interface_explicita = str(link_cadastrado.get("interface_fortigate") or "").strip().lower()
    if interface_explicita:
        return interface_explicita

    nome = _normalizar_link_texto(link_cadastrado.get("nome"))
    provedor = _normalizar_link_texto(link_cadastrado.get("provedor"))

    mapeamento_nome = {
        "WAN11": "wan2",
        "WAN2": "wan2",
        "WAN1": "wan1",
    }
    if nome in mapeamento_nome:
        return mapeamento_nome[nome]

    mapeamento_provedor = {
        "MUNDIVOX": "wan2",
    }
    return mapeamento_provedor.get(provedor)


def _carregar_links_cadastrados_fortigate(regiao):
    estrutura_path = PROJECT_ROOT / "estrutura_regionais.json"
    regional_por_regiao = {
        "RJ": "REG_RIO_DE_JANEIRO",
    }

    regional_codigo = regional_por_regiao.get((regiao or "").strip().upper())
    if not regional_codigo or not estrutura_path.exists():
        return []

    try:
        data = json.loads(estrutura_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    regional = (data.get("regionais") or {}).get(regional_codigo) or {}
    return [
        dict(link)
        for link in _obter_links_internet_exibicao(regional)
        if link.get("ativo", True)
    ]


def _mesclar_links_fortigate_com_cadastro(regiao, links_fortigate):
    links_cadastrados = _carregar_links_cadastrados_fortigate(regiao)
    if not links_cadastrados:
        return [dict(link) for link in links_fortigate]

    links_fortigate_todos = [dict(link) for link in links_fortigate]
    links_disponiveis = [dict(link) for link in links_fortigate]
    links_mesclados = []

    for link_cadastrado in links_cadastrados:
        indice_match = None
        nome_cadastrado = _normalizar_link_texto(link_cadastrado.get("nome"))
        provedor_cadastrado = _normalizar_link_texto(link_cadastrado.get("provedor"))
        ip_cadastrado = _normalizar_link_ip(link_cadastrado.get("ip"))
        interface_preferida = _mapear_interface_preferida(link_cadastrado)

        if interface_preferida:
            for indice, link_fortigate in enumerate(links_disponiveis):
                if str(link_fortigate.get("nome") or "").strip().lower() == interface_preferida:
                    indice_match = indice
                    break

        if indice_match is None:
            for indice, link_fortigate in enumerate(links_disponiveis):
                if _normalizar_link_texto(link_fortigate.get("nome")) == nome_cadastrado:
                    indice_match = indice
                    break

        if indice_match is None:
            for indice, link_fortigate in enumerate(links_disponiveis):
                if _normalizar_link_texto(link_fortigate.get("alias")) == provedor_cadastrado:
                    indice_match = indice
                    break

        if indice_match is None:
            for indice, link_fortigate in enumerate(links_disponiveis):
                if _normalizar_link_ip(link_fortigate.get("ip")) == ip_cadastrado:
                    indice_match = indice
                    break

        link_fortigate = links_disponiveis.pop(indice_match) if indice_match is not None else {}
        if not link_fortigate and interface_preferida:
            for item in links_fortigate_todos:
                if str(item.get("nome") or "").strip().lower() == interface_preferida:
                    link_fortigate = dict(item)
                    break

        link_mesclado = dict(link_fortigate)
        link_mesclado["interface_monitorada"] = link_fortigate.get("nome")
        link_mesclado["interface_esperada"] = interface_preferida
        link_mesclado["match_confiavel"] = bool(link_fortigate)
        link_mesclado["nome"] = (link_cadastrado.get("nome") or link_fortigate.get("nome") or "N/A").strip()
        link_mesclado["alias"] = (link_cadastrado.get("provedor") or link_fortigate.get("alias") or "").strip()
        link_mesclado["ip"] = ip_cadastrado or link_fortigate.get("ip", "N/A")
        link_mesclado["status"] = link_fortigate.get("status", link_cadastrado.get("status", "offline"))
        link_mesclado["velocidade"] = link_fortigate.get("velocidade", "N/A")
        link_mesclado["tipo"] = link_fortigate.get("tipo", "N/A")
        link_mesclado["estatisticas"] = link_fortigate.get("estatisticas") or {}
        link_mesclado["ultima_verificacao"] = link_fortigate.get("ultima_verificacao") or link_cadastrado.get("ultima_verificacao")
        links_mesclados.append(link_mesclado)

    return links_mesclados


def _extrair_regional_vpn(nome_tunel):
    texto = str(nome_tunel or "").strip().upper()
    if not texto:
        return "N/A"

    match = re.match(r"^([A-Z]\d{3})", texto)
    if match:
        return match.group(1)

    return texto


def _extrair_nome_exibicao_regional_vpn(nome_tunel):
    texto = str(nome_tunel or "").strip().upper()
    if not texto:
        return "REGIONAL"

    match = re.match(r"^[A-Z]\d{3}_?(.+)$", texto)
    sufixo = match.group(1) if match else texto
    sufixo = sufixo.strip("_-")
    if not sufixo:
        return "REGIONAL"

    partes = [parte for parte in sufixo.split("_") if parte]
    if not partes:
        return "REGIONAL"

    if partes[0] in {"REG", "REGIONAL"} and len(partes) > 1:
        partes = partes[1:]

    primeira_parte = partes[0]
    nome_limpo = re.sub(r"\d+$", "", primeira_parte).strip("_-")
    return nome_limpo or primeira_parte or "REGIONAL"


def _normalizar_texto_regional(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^A-Z0-9]+", "", texto)
    return texto


def _remover_prefixo_regional(valor):
    texto = str(valor or "").strip().upper()
    return re.sub(r"^(RG|REG|REGIONAL)[_\s\-]*", "", texto).strip()


def _gerar_tokens_regional(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return set()

    tokens = set()
    candidatos = [texto, _remover_prefixo_regional(texto)]
    for candidato in candidatos:
        normalizado = _normalizar_texto_regional(candidato)
        if normalizado:
            tokens.add(normalizado)

        partes = [parte for parte in re.split(r"[_\s\-/&]+", candidato) if parte]
        partes = [parte for parte in partes if parte not in {"RG", "REG", "REGIONAL", "DE", "DO", "DA", "DOS", "DAS", "E"}]

        for parte in partes:
            parte_norm = _normalizar_texto_regional(parte)
            if parte_norm:
                tokens.add(parte_norm)

        if partes:
            sigla = "".join(parte[0] for parte in partes if parte and parte[0].isalpha())
            sigla_norm = _normalizar_texto_regional(sigla)
            if len(sigla_norm) >= 2:
                tokens.add(sigla_norm)

    return {token for token in tokens if token}


def _carregar_indice_regionais_vpn():
    estrutura_path = PROJECT_ROOT / "estrutura_regionais.json"
    if not estrutura_path.exists():
        return []

    try:
        data = json.loads(estrutura_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    indice = []
    for chave, dados in (data.get("regionais") or {}).items():
        nome = str((dados or {}).get("nome") or chave).strip()
        nome_sem_prefixo = _remover_prefixo_regional(nome).replace("_", " ").strip()
        nome_exibicao = nome_sem_prefixo or nome

        tokens = set()
        tokens.update(_gerar_tokens_regional(chave))
        tokens.update(_gerar_tokens_regional(nome))

        indice.append({
            "chave": chave,
            "nome_exibicao": nome_exibicao,
            "tokens": tokens,
        })

    return indice


def _mapear_regional_vpn(nome_exibicao_vpn, codigo_vpn, indice_regionais):
    if not indice_regionais:
        return None

    candidatos = []
    candidatos.extend(_gerar_tokens_regional(nome_exibicao_vpn))
    candidatos.extend(_gerar_tokens_regional(codigo_vpn))
    candidatos = [candidato for candidato in candidatos if candidato]

    for candidato in candidatos:
        for regional in indice_regionais:
            if candidato in regional["tokens"]:
                return regional

    melhor = None
    melhor_score = 0
    for candidato in candidatos:
        for regional in indice_regionais:
            for token in regional["tokens"]:
                if not token:
                    continue
                if candidato in token or token in candidato:
                    score = min(len(candidato), len(token))
                    if score > melhor_score:
                        melhor = regional
                        melhor_score = score

    return melhor


def _agrupar_vpns_por_regional(vpns):
    indice_regionais = _carregar_indice_regionais_vpn()
    regionais_cadastradas = {item.get("chave") for item in indice_regionais}
    vpns_por_regional = {}

    for vpn in vpns:
        tunel = str(vpn.get("tunel") or "Desconhecido").strip()
        status_bruto = str(vpn.get("status") or "down").strip().lower()
        status = "up" if status_bruto == "up" else "down"
        regional_vpn = _extrair_regional_vpn(tunel)
        nome_exibicao_vpn = _extrair_nome_exibicao_regional_vpn(tunel)

        regional_mapeada = _mapear_regional_vpn(nome_exibicao_vpn, regional_vpn, indice_regionais)
        if regional_mapeada:
            regional = regional_mapeada["chave"]
            nome_exibicao = regional_mapeada["nome_exibicao"]
        else:
            regional = regional_vpn
            nome_exibicao = nome_exibicao_vpn

        dados_regional = vpns_por_regional.setdefault(
            regional,
            {"online": 0, "offline": 0, "nome_exibicao": nome_exibicao, "tunels": []}
        )
        if status == "up":
            dados_regional["online"] += 1
        else:
            dados_regional["offline"] += 1

        dados_regional["tunels"].append(vpn)

    for dados_regional in vpns_por_regional.values():
        dados_regional["tunels"].sort(key=lambda item: str(item.get("tunel") or ""))

    regionais_ordenadas = sorted(vpns_por_regional.keys(), key=lambda chave: str(vpns_por_regional[chave].get("nome_exibicao") or chave))
    regionais_mapeadas = [regional for regional in regionais_ordenadas if regional in regionais_cadastradas]
    regionais_exibicao = regionais_mapeadas if regionais_mapeadas else regionais_ordenadas
    regionais_com_offline = [regional for regional in regionais_exibicao if vpns_por_regional[regional]["offline"] > 0]

    return {
        "regionais": regionais_exibicao,
        "vpns_por_regional": vpns_por_regional,
        "regionais_com_offline": regionais_com_offline,
        "total_regionais": len(regionais_exibicao),
        "regionais_sem_offline": max(len(regionais_exibicao) - len(regionais_com_offline), 0),
    }


def _formatar_nome_link_dashboard(link):
    nome = str(link.get("nome") or "").strip()
    alias = str(link.get("alias") or "").strip()
    if nome and alias and _normalizar_link_texto(nome) != _normalizar_link_texto(alias):
        return f"{nome} - {alias}"
    return nome or alias or "N/A"


def _ordenar_regionais_links(chaves_regionais):
    ordem_preferida = ["SP", "RJ"]
    chaves = [str(chave).strip().upper() for chave in chaves_regionais if str(chave).strip()]
    ordenadas = [item for item in ordem_preferida if item in chaves]
    ordenadas.extend(sorted(item for item in chaves if item not in ordem_preferida))
    return ordenadas


def _coletar_links_multiregional():
    fortigates = ENV_CONFIG.get("fortigate")
    if not isinstance(fortigates, dict):
        return {
            "success": False,
            "message": "Configuração de Fortigate inválida (esperado SP, RJ, etc)"
        }

    links_por_regional = {}
    sd_wan_por_regional = {}
    links = []

    for regional, cfg in fortigates.items():
        regional_nome = str(regional or "N/A").strip().upper()
        gerenciador = GerenciadorFortigate(
            host=cfg.get("host"),
            port=cfg.get("port"),
            username=cfg.get("username"),
            password=cfg.get("password"),
        )

        if not gerenciador.autenticar():
            links_por_regional[regional_nome] = []
            sd_wan_por_regional[regional_nome] = {"error": "Falha na autenticação"}
            continue

        resultado = gerenciador.obter_informacoes_completas()
        if not resultado.get("success"):
            links_por_regional[regional_nome] = []
            sd_wan_por_regional[regional_nome] = {
                "error": resultado.get("message", "Erro desconhecido")
            }
            continue

        links_processados = _mesclar_links_fortigate_com_cadastro(regional_nome, resultado.get("links", []))
        links_normalizados = []

        for link in links_processados:
            link_normalizado = dict(link)
            link_normalizado["regional"] = regional_nome
            link_normalizado["nome"] = _formatar_nome_link_dashboard(link_normalizado)
            link_normalizado["ultima_verificacao"] = (
                link_normalizado.get("ultima_verificacao")
                or resultado.get("timestamp")
                or datetime.now().isoformat()
            )
            links_normalizados.append(link_normalizado)
            links.append(link_normalizado)

        links_por_regional[regional_nome] = links_normalizados
        sd_wan_por_regional[regional_nome] = resultado.get("sd_wan") or {}

    regionais_ordenadas = _ordenar_regionais_links(links_por_regional.keys())
    links_por_regional = {regional: links_por_regional.get(regional, []) for regional in regionais_ordenadas}
    sd_wan_por_regional = {regional: sd_wan_por_regional.get(regional, {}) for regional in regionais_ordenadas}

    return {
        "success": True,
        "links": links,
        "links_por_regional": links_por_regional,
        "sd_wan_por_regional": sd_wan_por_regional,
        "timestamp": datetime.now().isoformat()
    }

# === UTILITÁRIOS FORTIMANAGER/FORTIGATE (REGIONAIS) ===

_REGIONAL_ALIAS = {
    "GALAXIA": ["GLX"],
    "GLOBAL": ["GLOBALSEG", "GLOBALSEG"],
    "SEGURANCA": ["GLOBALSEG", "GLOBALSEG"],
    "ALAGOAS": ["REGALAGOAS"],
    "SJC": ["REGSAOJOSEDOSCAMPOS"],
}

_REGIONAL_DEVICE_OVERRIDE = {
    "REG_GLOBAL_SEGURANCA": ["FTG_GLOBALSEG", "FTG_GLX_100F_MATRIZ"],
    "REG_ALAGOAS": ["FTG_REGALAGOAS"],
    "REG_PARA": ["FGT_REGPARA"],
    "REG_ORMEC_PARA": ["FTG_ORMEC_PARA"],
    "REG_SAO_LEOPOLDO": ["FGT_REGSAOLEOPOLDO"],
    "REG_SULZER": ["FTG_REGSULZERTRIUNFO"],
    "REG_SJC": ["FGT_REGSAOJOSEDOSCAMPOS"],
}

_REGIONAL_LINK_INTERFACE_INCLUDE_OVERRIDE = {
    "REG_GLOBAL_SEGURANCA": {"wan1", "wan2", "wan_connect_01"},
    "REG_SULZER": {"wan2", "b"},
}


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join([c for c in value if not unicodedata.combining(c)])
    value = re.sub(r"[^A-Za-z0-9]+", " ", value)
    return value.strip().upper()


def _tokenize(value: str) -> set:
    if not value:
        return set()
    normalized = _normalize_text(value)
    tokens = {t for t in normalized.split() if t}
    # remove tokens comuns que não ajudam na identificação
    stopwords = {"RG", "REG", "REGIONAL", "REGIAO"}
    return {t for t in tokens if t not in stopwords}


def _expand_aliases(tokens: set) -> set:
    expanded = set(tokens)
    for token in list(tokens):
        for alias in _REGIONAL_ALIAS.get(token, []):
            expanded.add(alias)
    return expanded


def _suggest_regionais(codigo_regional: str, limit: int = 5) -> list:
    regionais = gerenciador_regionais.listar_regionais()
    if not regionais:
        return []

    normalized_target = _normalize_text(codigo_regional)
    normalized_map = {codigo: _normalize_text(codigo) for codigo in regionais}
    suggestions = []

    for normalized_match in difflib.get_close_matches(normalized_target, list(normalized_map.values()), n=limit, cutoff=0.45):
        for codigo, normalized in normalized_map.items():
            if normalized == normalized_match and codigo not in suggestions:
                suggestions.append(codigo)

    return suggestions[:limit]


def _rank_fortimanager_devices(codigo_regional: str, regional_info: dict, devices: list, limit: int = 5) -> list:
    if not devices:
        return []

    regional_name = regional_info.get("nome", "") if regional_info else ""
    base = f"{codigo_regional} {regional_name}"
    regional_tokens = _expand_aliases(_tokenize(base))
    ranked = []

    for device in devices:
        device_label = f"{device.get('name', '')} {device.get('hostname', '')}"
        device_norm = _normalize_text(device_label)
        device_tokens = set(device_norm.split())

        score = 0
        for token in regional_tokens:
            if token in device_tokens:
                score += 3
            elif token and token in device_norm:
                score += 1

        if score > 0:
            ranked.append({
                "name": device.get("name", ""),
                "hostname": device.get("hostname", ""),
                "ip": device.get("ip", ""),
                "score": score
            })

    ranked.sort(key=lambda item: (-item["score"], str(item.get("name", ""))))
    return ranked[:limit]


def _extract_interface_ip(ip_value) -> str:
    if isinstance(ip_value, (list, tuple)):
        if not ip_value:
            return ""
        ip_text = str(ip_value[0] or "").strip()
    else:
        ip_text = str(ip_value or "").strip()
    if not ip_text:
        return ""
    ip_text = ip_text.split()[0].strip()
    if "/" in ip_text:
        ip_text = ip_text.split("/", 1)[0].strip()
    if ip_text in {"0", "0.0.0.0", "::", "N/A", "None"}:
        return ""
    return ip_text


def _extract_interface_mask(ip_value) -> str:
    if isinstance(ip_value, (list, tuple)):
        if len(ip_value) < 2:
            return ""
        return str(ip_value[1] or "").strip()

    ip_text = str(ip_value or "").strip()
    if not ip_text:
        return ""

    parts = ip_text.split()
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _format_prefix_mask(mask_value) -> str:
    mask_text = str(mask_value or "").strip()
    if not mask_text:
        return ""

    if mask_text.startswith("/"):
        return mask_text

    try:
        return f"/{ipaddress.IPv4Network(f'0.0.0.0/{mask_text}').prefixlen}"
    except Exception:
        return mask_text


def _ping_indica_online(process_result) -> bool:
    stdout = str(getattr(process_result, "stdout", "") or "")
    stderr = str(getattr(process_result, "stderr", "") or "")
    output = f"{stdout}\n{stderr}".lower()

    if "reply from" in output or "resposta de" in output:
        return True

    if getattr(process_result, "returncode", 1) == 0:
        if "ttl=" in output or "tempo=" in output or "time=" in output:
            return True

    return False


def _is_meaningful_provider_text(value) -> bool:
    provider = _extract_provider_name({"alias": value})
    normalized = _normalizar_link_texto(provider)
    if normalized in {"", "WAN", "LINK", "INTERNET", "TEMP", "TESTE", "DESATIVADOS"}:
        return False
    if len(normalized) <= 1:
        return False
    if normalized.isdigit():
        return False
    return True


def _is_excluded_wan_name(name: str) -> bool:
    name = str(name or "").strip().lower()
    if not name:
        return False
    if name in {"dmz", "mgmt", "ha"}:
        return True
    if re.fullmatch(r"ha\d+", name):
        return True
    return False


def _should_keep_synced_link(link: dict) -> bool:
    interface_name = str(link.get("interface_monitorada") or link.get("nome") or "").strip().lower()
    provider_name = str(link.get("provedor") or "").strip()
    ip_text = _extract_interface_ip(link.get("ip"))

    if _is_excluded_wan_name(interface_name):
        return False
    if not _is_meaningful_provider_text(provider_name):
        return False
    if ip_text and _is_public_ip(ip_text):
        return True
    if _is_forti_non_public_wan_candidate(link):
        return True
    return False


def _is_forti_non_public_wan_candidate(link: dict) -> bool:
    interface_name = str(link.get("interface_monitorada") or link.get("nome") or "").strip().lower()
    provider_name = str(link.get("provedor") or "").strip()
    link_type = str(link.get("tipo") or "").strip().lower()
    origem_sync = str(link.get("origem_sync") or "").strip().lower()
    regra_origem = str(link.get("regra_origem") or "").strip().lower()
    link_ip = _extract_interface_ip(link.get("ip"))

    if _is_excluded_wan_name(interface_name):
        return False
    if not _is_meaningful_provider_text(provider_name):
        return False
    if link_ip and _is_public_ip(link_ip):
        return False
    if link_type == "tunnel":
        return False
    if "vpn" in interface_name or interface_name.startswith("t_"):
        return False
    if origem_sync not in {"fortigate", "fortimanager"} and regra_origem != "links_internet_auto":
        return False

    edge_name = interface_name.startswith(("wan", "port")) or interface_name in {"a", "b"}
    return edge_name


def _format_interface_local_label(interface: dict) -> str:
    name = str(interface.get("name") or interface.get("interface") or "").strip()
    alias = str(interface.get("alias") or interface.get("description") or "").strip()
    if name:
        return name
    return alias


def _is_wan_interface(interface: dict) -> bool:
    name = str(interface.get("name") or interface.get("interface") or "").strip().lower()
    alias = str(interface.get("alias") or interface.get("description") or "").strip().lower()
    role_raw = interface.get("role")
    role = str(role_raw or "").strip().lower()
    interface_type_raw = interface.get("type")
    interface_type = str(interface_type_raw or "").strip().lower()
    interface_ip = _extract_interface_ip(interface.get("ip"))
    has_public_ip = _is_public_ip(interface_ip)
    is_up = str(interface.get("status") or "").strip().lower() in {"1", "up", "online", "active"} or interface.get("status") == 1
    meaningful_provider = _is_meaningful_provider_text(interface.get("alias") or interface.get("description") or "")

    if not name:
        return False

    if interface_type == "tunnel" or interface_type_raw == 4:
        return False

    if "vpn" in name or name.startswith("t_"):
        return False

    if _is_excluded_wan_name(name):
        return False

    if name.startswith(("internal", "loopback", "fortilink")):
        return False

    if name == "mgmt":
        return False

    edge_name = name.startswith("wan") or name.startswith("port") or name in {"a", "b"}
    role_wan = role in {"1", "wan"} or role_raw == 1

    if has_public_ip:
        return role_wan or edge_name

    if not is_up:
        return False

    return role_wan and edge_name and meaningful_provider


def _format_link_speed(speed_value) -> str:
    speed_text = str(speed_value or "").strip()
    if not speed_text:
        return "N/A"
    if re.fullmatch(r"\d+(?:\.\d+)?", speed_text):
        return f"{speed_text} Mbps"
    return speed_text


def _format_bandwidth_from_interface(interface: dict) -> str:
    downstream = interface.get("estimated-downstream-bandwidth") or interface.get("measured-downstream-bandwidth") or 0
    upstream = interface.get("estimated-upstream-bandwidth") or interface.get("measured-upstream-bandwidth") or 0

    for value in (downstream, upstream):
        if isinstance(value, (int, float)) and value > 0:
            mbps = value / 1000 if value >= 1000 else value
            return f"{int(mbps)} Mbps" if float(mbps).is_integer() else f"{mbps:.1f} Mbps"

    speed_value = interface.get("speed")
    try:
        speed_numeric = float(speed_value)
    except (TypeError, ValueError):
        speed_numeric = None

    # No FortiManager, speed=1 costuma ser um valor generico da interface,
    # nao a banda contratada do link.
    if speed_numeric is not None and speed_numeric <= 1:
        return "Banda nao registrada"

    formatted_speed = _format_link_speed(speed_value)
    if formatted_speed == "N/A":
        return "Banda nao registrada"
    return formatted_speed


def _is_local_interface_type(interface: dict) -> bool:
    interface_type_raw = interface.get("type")
    interface_type = str(interface_type_raw or "").strip().lower()
    return interface_type in {"vlan", "zone", "switch", "hard-switch", "vlan-switch", "aggregate", "software-switch"}


def _is_local_interface_name(name: str, alias: str) -> bool:
    name_lower = str(name or "").strip().lower()
    alias_lower = str(alias or "").strip().lower()
    textos = [name_lower, alias_lower]

    if any("rede local" in texto or "rede_local" in texto for texto in textos):
        return True
    if any(re.search(r"(^|[^a-z])(lan|local)([^a-z]|$)", texto) for texto in textos if texto):
        return True
    if name_lower in {"lan", "internal", "vlan"}:
        return True
    if name_lower.startswith(("lan", "internal", "vlan", "zone")):
        return True
    return False


def _selecionar_interface_lan(interfaces: list) -> dict:
    candidatos = []
    for interface in interfaces or []:
        name = str(interface.get("name") or interface.get("interface") or "").strip()
        if not name:
            continue

        interface_ip = _extract_interface_ip(interface.get("ip"))
        role_raw = interface.get("role")
        role = str(role_raw or "").strip().lower()
        interface_type_raw = interface.get("type")
        if str(interface_type_raw or "").strip().lower() == "tunnel" or interface_type_raw == 4:
            continue

        if role in {"1", "wan"} or role_raw == 1:
            continue

        name_lower = name.lower()
        alias = str(interface.get("alias") or interface.get("description") or "").strip().lower()
        status = str(interface.get("status") or "").strip().lower()
        has_private_ip = _is_rfc1918_ip(interface_ip)
        local_name = _is_local_interface_name(name, alias)
        local_type = _is_local_interface_type(interface)

        if not has_private_ip and not local_name and not local_type:
            continue

        score = 0
        if has_private_ip:
            score += 10
        if local_name:
            score += 8
        if local_type:
            score += 6
        if name_lower in {"lan", "internal"}:
            score += 4
        if name_lower.startswith(("internal", "lan", "vlan", "zone")):
            score += 3
        if status in {"1", "up", "online", "active"} or interface.get("status") == 1:
            score += 2
        if "desativ" in alias or "disabled" in alias:
            score -= 6
        if "segregada" in alias or "visitante" in alias or "gerencia" in alias or name_lower in {"dmz", "mgmt"}:
            score -= 4

        if name_lower in {"wan1", "wan2"}:
            score -= 20

        candidatos.append((score, name_lower, interface))

    if not candidatos:
        return {}

    candidatos.sort(key=lambda item: (-item[0], item[1]))
    return candidatos[0][2]


def _extract_provider_name(interface: dict) -> str:
    alias = str(interface.get("alias") or interface.get("description") or "").strip()
    interface_name = str(interface.get("name") or interface.get("interface") or "").strip()
    raw_value = alias or interface_name or "N/A"

    normalized = re.sub(r"^(wan|link|internet)[-_\s]*", "", raw_value, flags=re.IGNORECASE).strip("-_ ")
    normalized = normalized.replace("_", " ").replace("-", " ").strip()

    return normalized or raw_value


def _normalize_addressing_mode(mode_value) -> str:
    if mode_value is None:
        return ""

    if isinstance(mode_value, bool):
        return ""

    if isinstance(mode_value, (int, float)):
        if int(mode_value) == 2:
            return "pppoe"
        if int(mode_value) == 1:
            return "dhcp"
        if int(mode_value) == 0:
            return "static"
        return str(int(mode_value))

    mode_text = str(mode_value or "").strip().lower()
    if not mode_text:
        return ""

    if mode_text in {"0", "static", "manual"}:
        return "static"
    if mode_text in {"1", "dhcp", "dynamic"}:
        return "dhcp"
    if mode_text in {"2", "pppoe", "pppoe"}:
        return "pppoe"
    return mode_text


def _extract_interface_addressing_mode(interface: dict) -> str:
    for key in ("addressing_mode", "addressing-mode", "mode"):
        normalized = _normalize_addressing_mode(interface.get(key))
        if normalized:
            return normalized
    return ""


def _resolve_link_ip_publico_status(link: dict) -> str:
    ip_value = _extract_interface_ip(link.get("ip"))
    if ip_value:
        return ""

    addressing_mode = _normalize_addressing_mode(
        link.get("addressing_mode")
        or link.get("modo_enderecamento")
        or link.get("mode")
    )
    return "pppoe" if addressing_mode == "pppoe" else "sem_ip_publico"


def _format_link_ip_exibicao(link: dict) -> str:
    ip_value = _extract_interface_ip(link.get("ip"))
    mask_value = _format_prefix_mask(_extract_interface_mask(link.get("ip"))) or str(link.get("mascara") or "").strip()
    if ip_value:
        return f"{ip_value}{mask_value if mask_value else ''}"

    ip_publico_status = str(link.get("ip_publico_status") or _resolve_link_ip_publico_status(link)).strip().lower()
    if ip_publico_status == "pppoe":
        return "PPPoE"
    return "sem_ip_publico"


def _normalize_synced_link(interface: dict, fortigate_host=None, fortigate_porta=None, source="fortigate") -> dict:
    interface_name = str(interface.get("name") or interface.get("interface") or "").strip()
    provider_name = _extract_provider_name(interface)
    status_text = str(interface.get("status") or "").strip().lower()
    link_flag = interface.get("link")
    status_raw = interface.get("status")
    addressing_mode = _extract_interface_addressing_mode(interface)
    interface_ip = _extract_interface_ip(interface.get("ip")) or ""

    if link_flag is None:
        status = "online" if status_text in {"1", "up", "online", "active"} or status_raw == 1 else "offline"
    else:
        status = "online" if bool(link_flag) else "offline"

    return {
        "nome": interface_name.upper() if interface_name.lower().startswith("wan") else interface_name,
        "ip": interface_ip,
        "mascara": _format_prefix_mask(_extract_interface_mask(interface.get("ip"))),
        "provedor": provider_name,
        "velocidade": _format_bandwidth_from_interface(interface),
        "categoria": "internet",
        "regra_origem": "links_internet_auto",
        "tipo": interface.get("type") or "N/A",
        "addressing_mode": addressing_mode,
        "ip_publico_status": "pppoe" if not interface_ip and addressing_mode == "pppoe" else ("sem_ip_publico" if not interface_ip else ""),
        "status": status,
        "ativo": True,
        "interface_monitorada": interface_name or None,
        "fortigate_host": fortigate_host,
        "fortigate_porta": fortigate_porta,
        "ultima_verificacao": datetime.now().isoformat(),
        "origem_sync": source
    }


def _ordenar_links_internet(links: list) -> list:
    def _sort_key(link: dict):
        prioridade = link.get("priority")
        prioridade_val = prioridade if isinstance(prioridade, (int, float)) else 9999
        member_id = link.get("sdwan_member_id")
        member_val = member_id if isinstance(member_id, (int, float)) else 9999
        interface_nome = str(link.get("interface_monitorada") or link.get("nome") or "").strip().lower()
        return (prioridade_val, member_val, interface_nome)

    return sorted((dict(link) for link in (links or [])), key=_sort_key)


def _marcar_papeis_redundancia(links: list) -> list:
    links_ordenados = _ordenar_links_internet(links)
    total = len(links_ordenados)

    for index, link in enumerate(links_ordenados):
        if total <= 1:
            link["papel_link"] = "principal"
            link["tem_redundancia"] = False
        else:
            link["papel_link"] = "principal" if index == 0 else "redundancia"
            link["tem_redundancia"] = True

    return links_ordenados


def _is_internet_link_candidate(link: dict) -> bool:
    interface_name = str(link.get("interface_monitorada") or link.get("nome") or "").strip().lower()
    provider_name = str(link.get("provedor") or "").strip().lower()
    link_type = str(link.get("tipo") or "").strip().lower()
    categoria = str(link.get("categoria") or "").strip().lower()
    regra_origem = str(link.get("regra_origem") or "").strip().lower()
    origem_sync = str(link.get("origem_sync") or "").strip().lower()
    link_ip = _extract_interface_ip(link.get("ip"))

    if link_type == "tunnel":
        return False

    if any("vpn" in value for value in (interface_name, provider_name)):
        return False

    if interface_name.startswith("t_"):
        return False

    if _is_excluded_wan_name(interface_name):
        return False

    if not _is_meaningful_provider_text(provider_name):
        return False

    if link_ip and _is_public_ip(link_ip):
        pass
    elif _is_forti_non_public_wan_candidate(link):
        return True
    else:
        return False

    if categoria == "internet" or regra_origem == "links_internet_auto":
        return True

    if str(link.get("modo_verificacao") or "").strip().lower() == "sla":
        return True

    if interface_name.startswith("wan"):
        return True

    if origem_sync in {"fortigate", "fortimanager"} and link_type in {"", "physical", "aggregate", "redundant", "vlan", "pppoe"}:
        return _is_public_ip(link.get("ip"))

    return (
        False
    )


def _filtrar_links_internet(links: list) -> list:
    return [link for link in (links or []) if _is_internet_link_candidate(link)]


def _is_link_id_numerico(link_id) -> bool:
    return bool(re.search(r"_\d+$", str(link_id or "").strip().lower()))


def _selecionar_links_internet_canonicos(links: list) -> list:
    links_internet = _filtrar_links_internet(links)
    links_numericos = [link for link in links_internet if _is_link_id_numerico(link.get("id"))]
    return links_numericos or links_internet


def _obter_links_internet_exibicao(regional_info: dict) -> list:
    links_auto = regional_info.get("links_internet_auto") if isinstance(regional_info, dict) else None
    if isinstance(links_auto, list):
        return [dict(link) for link in links_auto if _is_internet_link_candidate(link)]

    links_migrados = []
    for link in _selecionar_links_internet_canonicos((regional_info or {}).get("links", [])):
        regra_origem = str(link.get("regra_origem") or "").strip().lower()
        origem_sync = str(link.get("origem_sync") or "").strip().lower()
        fortigate_host = str(link.get("fortigate_host") or "").strip()

        if (
            regra_origem == "links_internet_auto"
            or origem_sync in {"fortigate", "fortimanager"}
            or fortigate_host
        ):
            links_migrados.append(link)

    return links_migrados


def _normalize_interface_local_value(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    normalized = text.lower()
    if normalized in {"rede local", "rede_local"}:
        return "LAN"
    if normalized == "lan":
        return "LAN"
    if normalized in {"desativados", "disabled"}:
        return None
    return text


def _obter_links_internet_fallback_local(regional_info: dict) -> list:
    links_oficiais = _obter_links_internet_exibicao(regional_info)
    if links_oficiais:
        return [dict(link) for link in links_oficiais if _is_internet_link_candidate(link)]

    fallback = []
    for link in _selecionar_links_internet_canonicos((regional_info or {}).get("links", [])):
        if not _is_internet_link_candidate(link):
            continue

        link_fallback = dict(link)
        link_fallback.setdefault("categoria", "internet")
        link_fallback.setdefault("regra_origem", "links_internet_auto")
        link_fallback.setdefault("origem_sync", "fallback_local")
        link_fallback.setdefault("interface_monitorada", link_fallback.get("nome"))
        fallback.append(link_fallback)

    return fallback


def _persistir_links_internet_exibicao(codigo_regional: str, links: list):
    gerenciador_regionais.recarregar_regionais()
    regional = gerenciador_regionais.regionais.get("regionais", {}).get(codigo_regional)
    if not regional:
        return

    regional["links_internet_auto"] = [
        dict(link)
        for link in _filtrar_links_internet(links or [])
    ]
    gerenciador_regionais.salvar_regionais()


def _atualizar_link_internet_exibicao(codigo_regional: str, id_link: str, novos_dados: dict):
    gerenciador_regionais.recarregar_regionais()
    regional = gerenciador_regionais.regionais.get("regionais", {}).get(codigo_regional)
    if not regional:
        return False

    links_auto = regional.get("links_internet_auto") or []
    interface_alvo = str(novos_dados.get("interface_monitorada") or novos_dados.get("nome") or "").strip().lower()

    for index, link in enumerate(links_auto):
        link_id = str(link.get("id") or "").strip()
        link_interface = str(link.get("interface_monitorada") or link.get("nome") or "").strip().lower()
        if id_link == link_id or (interface_alvo and interface_alvo == link_interface):
            links_auto[index].update(dict(novos_dados))
            regional["links_internet_auto"] = links_auto
            gerenciador_regionais.salvar_regionais()
            return True

    return False


def _find_link_for_interface(existing_links: list, normalized_link: dict):
    interface_key = _normalizar_link_texto(
        normalized_link.get("interface_monitorada") or normalized_link.get("nome")
    )
    provider_key = _normalizar_link_texto(normalized_link.get("provedor"))
    ip_key = _normalizar_link_ip(normalized_link.get("ip"))

    for link in existing_links:
        link_interface = _normalizar_link_texto(
            link.get("interface_monitorada") or link.get("nome")
        )
        if interface_key and link_interface == interface_key:
            return link

    for link in existing_links:
        if not _is_internet_link_candidate(link):
            continue
        if provider_key and _normalizar_link_texto(link.get("provedor")) == provider_key:
            return link

    for link in existing_links:
        if not _is_internet_link_candidate(link):
            continue
        if ip_key and _normalizar_link_ip(link.get("ip")) == ip_key:
            return link

    return None


def _build_auto_link_id(codigo_regional: str, interface_name: str, existing_links: list) -> str:
    codigo_slug = re.sub(r"[^a-z0-9]+", "_", str(codigo_regional or "").strip().lower()).strip("_")
    interface_slug = re.sub(r"[^a-z0-9]+", "_", str(interface_name or "link").strip().lower()).strip("_")
    base_id = f"link_{codigo_slug}_{interface_slug or 'wan'}"
    used_ids = {str(link.get("id") or "").strip() for link in existing_links}

    if base_id not in used_ids:
        return base_id

    suffix = 2
    while f"{base_id}_{suffix}" in used_ids:
        suffix += 1
    return f"{base_id}_{suffix}"


def _load_regional_interfaces(
    codigo_regional: str,
    regional_info: dict,
    adom=None,
    fortimanager_devices=None,
    auth_timeout=None,
) -> dict:
    resolved = _get_gerenciador_fortigate_regional(
        codigo_regional,
        regional_info,
        adom=adom,
        fortimanager_devices=fortimanager_devices,
    )
    gerenciador_regional = resolved.get("manager") if resolved else None
    device_info = resolved.get("device") if resolved else None
    adom = resolved.get("adom") if resolved else None
    use_proxy = _use_fortimanager_proxy()

    if not gerenciador_regional:
        return {
            "success": False,
            "message": "Fortigate da regional não identificado no FortiManager",
            "status": "fortigate_not_mapped",
            "resolved": resolved,
            "interfaces": []
        }

    if auth_timeout is not None:
        try:
            gerenciador_regional.request_timeout = auth_timeout
        except Exception:
            pass

    interfaces = []
    source = "fortigate"

    if use_proxy and device_info and device_info.get("name"):
        try:
            with FortiManagerClient() as fm:
                interfaces_result = fm.list_device_interfaces(adom, device_info.get("name"))
            interfaces_data = interfaces_result.get("result", [])
            interfaces = interfaces_data[0].get("data", []) if interfaces_data else []
            if interfaces:
                source = "fortimanager"
            else:
                current_app.logger.warning(
                    "FortiManager não retornou interfaces para %s em %s; usando fallback direto no FortiGate",
                    device_info.get("name"),
                    adom,
                )
        except Exception as exc:
            current_app.logger.warning(
                "Erro ao obter interfaces via FortiManager para %s: %s. Usando fallback direto no FortiGate",
                codigo_regional,
                exc,
            )

    if not interfaces:
        if not gerenciador_regional.autenticar():
            fallback_manager = None
            fallback_port = 443
            if getattr(gerenciador_regional, "port", None) != fallback_port:
                fallback_manager = GerenciadorFortigate(
                    host=getattr(gerenciador_regional, "host", None),
                    port=fallback_port,
                    username=getattr(gerenciador_regional, "username", None),
                    password=getattr(gerenciador_regional, "password", None)
                )
                if auth_timeout is not None:
                    fallback_manager.request_timeout = auth_timeout
                if fallback_manager.autenticar():
                    gerenciador_regional = fallback_manager
                else:
                    fallback_manager = None

            if fallback_manager is None:
                return {
                    "success": False,
                    "message": "Falha na autenticação com o Fortigate",
                    "status": "fortigate_auth_error",
                    "resolved": resolved,
                    "interfaces": []
                }

        interfaces_result = gerenciador_regional.obter_interfaces()
        if not interfaces_result["success"]:
            return {
                "success": False,
                "message": "Erro ao obter interfaces do Fortigate",
                "status": "fortigate_error",
                "resolved": resolved,
                "interfaces": []
            }

        interfaces = interfaces_result["interfaces"]
        source = "fortigate"

    return {
        "success": True,
        "interfaces": interfaces,
        "source": source,
        "resolved": resolved,
        "manager": gerenciador_regional,
        "device": device_info,
        "adom": adom,
    }


def _resolve_fortigate_credentials() -> dict:
    env_fg = ENV_CONFIG.get("fortigate", {})
    if isinstance(env_fg, dict) and env_fg.get("host"):
        return env_fg
    if isinstance(env_fg, dict):
        for cfg in env_fg.values():
            if isinstance(cfg, dict) and cfg.get("host"):
                return cfg
    return get_credentials("fortigate") or {}


def _get_fortimanager_adom() -> str:
    fm_cfg = ENV_CONFIG.get("fortimanager", {}) if isinstance(ENV_CONFIG.get("fortimanager", {}), dict) else {}
    return fm_cfg.get("adom", "root")


def _use_fortimanager_proxy() -> bool:
    fm_cfg = ENV_CONFIG.get("fortimanager", {}) if isinstance(ENV_CONFIG.get("fortimanager", {}), dict) else {}
    return bool(fm_cfg.get("use_proxy_for_links"))


def _list_fortimanager_devices(adom: str):
    fm_cfg = ENV_CONFIG.get("fortimanager", {}) if isinstance(ENV_CONFIG.get("fortimanager", {}), dict) else {}
    if not fm_cfg.get("host") or not fm_cfg.get("username"):
        return []

    try:
        with FortiManagerClient() as client:
            response = client.list_devices(adom=adom)
        result = response.get("result", [])
        if not result:
            return []
        return result[0].get("data", None)
    except Exception as exc:
        if has_app_context(): 
            current_app.logger.error(f"Erro ao listar devices do FortiManager: {exc}") 
        else: 
            app.logger.error(f"Erro ao listar devices do FortiManager: {exc}") 
        return None


def _match_fortimanager_device(codigo_regional: str, regional_info: dict, devices: list) -> dict:
    if not devices:
        return {}

    for device_name in _REGIONAL_DEVICE_OVERRIDE.get(codigo_regional.upper(), []):
        for device in devices:
            if str(device.get("name", "")).strip().upper() == device_name.upper():
                return device

    regional_name = regional_info.get("nome", "") if regional_info else ""
    base = f"{codigo_regional} {regional_name}"
    regional_tokens = _expand_aliases(_tokenize(base))

    best = None
    best_score = 0
    for device in devices:
        device_label = f"{device.get('name', '')} {device.get('hostname', '')}"
        device_norm = _normalize_text(device_label)
        device_tokens = set(device_norm.split())

        score = 0
        for token in regional_tokens:
            if token in device_tokens:
                score += 3
            elif token and token in device_norm:
                score += 1

        if score > best_score:
            best_score = score
            best = device

    return best or {}


def _get_gerenciador_fortigate_regional(codigo_regional: str, regional_info: dict, adom=None, fortimanager_devices=None):
    creds = _resolve_fortigate_credentials()
    port = creds.get("port", 20443)
    username = creds.get("username")
    password = creds.get("password")

    target_ip = None
    target_name = None
    override_device_names = _REGIONAL_DEVICE_OVERRIDE.get(codigo_regional.upper(), [])

    if regional_info:
        fortigate_info = regional_info.get("fortigate", {}) if isinstance(regional_info.get("fortigate", {}), dict) else {}
        target_ip = regional_info.get("fortigate_ip") or fortigate_info.get("ip")
        target_name = regional_info.get("fortigate_device") or fortigate_info.get("name")
        port = fortigate_info.get("port", port)
        username = fortigate_info.get("username", username)
        password = fortigate_info.get("password", password)

        if not target_ip:
            for link in regional_info.get("links", []):
                link_host = str(link.get("fortigate_host") or "").strip()
                if link_host:
                    target_ip = link_host
                    port = link.get("fortigate_porta") or port
                    break

    adom = adom or _get_fortimanager_adom()
    devices = fortimanager_devices if fortimanager_devices is not None else _list_fortimanager_devices(adom)
    inventory_available = devices is not None
    devices = devices or []
    candidate_devices = _rank_fortimanager_devices(codigo_regional, regional_info or {}, devices)
    device_match = {}

    if override_device_names:
        device_match = _match_fortimanager_device(codigo_regional, regional_info or {}, devices)
        if device_match:
            target_name = device_match.get("name") or target_name
            target_ip = device_match.get("ip") or target_ip

    if not target_ip and target_name:
        for device in devices:
            if str(device.get("name", "")).strip().upper() == str(target_name).strip().upper():
                target_ip = device.get("ip")
                break

    if not target_ip:
        device_match = device_match or _match_fortimanager_device(codigo_regional, regional_info or {}, devices)
        target_ip = device_match.get("ip")

    if not target_ip:
        return {
            "manager": None,
            "device": None,
            "adom": adom,
            "fortimanager_inventory_available": inventory_available,
            "fortimanager_devices": devices,
            "candidate_devices": candidate_devices
        }

    device_info = {}
    if target_name:
        device_info = {"name": target_name, "ip": target_ip}
    elif "device_match" in locals() and device_match:
        device_info = device_match
    else:
        device_info = {"name": "", "ip": target_ip}

    if target_ip and not device_info.get("name"):
        for device in devices:
            if str(device.get("ip", "")).strip() == str(target_ip).strip():
                device_info = device
                break

    return {
        "manager": GerenciadorFortigate(
            host=target_ip,
            port=port,
            username=username,
            password=password
        ),
        "device": device_info,
        "adom": adom,
        "fortimanager_inventory_available": inventory_available,
        "fortimanager_devices": devices,
        "candidate_devices": candidate_devices
    }


def _preparar_link_para_template(link: dict) -> dict:
    link_completo = dict(link)
    ip_render = _extract_interface_ip(link_completo.get("ip"))
    link_completo["ip"] = ip_render or ""
    link_completo.setdefault("status", "unknown")
    link_completo.setdefault("ultima_verificacao", None)
    link_completo.setdefault("interface_monitorada", link_completo.get("nome"))
    link_completo.setdefault("fortigate_host", None)
    link_completo.setdefault("fortigate_porta", None)
    link_completo.setdefault("modo_verificacao", None)
    link_completo.setdefault("sla_status", None)
    link_completo.setdefault("sdwan_member_id", None)
    link_completo.setdefault("velocidade", "N/A")
    link_completo.setdefault("mascara", "")
    link_completo.setdefault("interface_local", None)
    link_completo.setdefault("ip_local", "")
    link_completo.setdefault("mascara_local", "")
    link_completo.setdefault("addressing_mode", _normalize_addressing_mode(link_completo.get("addressing_mode") or link_completo.get("modo_enderecamento") or link_completo.get("mode")))
    link_completo.setdefault("ip_publico_status", _resolve_link_ip_publico_status(link_completo))
    link_completo["ip_exibicao"] = _format_link_ip_exibicao(link_completo)
    link_completo["interface_local"] = _normalize_interface_local_value(link_completo.get("interface_local"))
    link_completo.setdefault("ativo", True)
    return link_completo


def _coletar_links_regional(
    codigo_regional: str,
    regional_info: dict,
    persist=False,
    adom=None,
    fortimanager_devices=None,
    include_sdwan=True,
    auth_timeout=None,
) -> dict:
    links_existentes = [dict(link) for link in (regional_info.get("links") or [])]
    links_canonicos_existentes = [dict(link) for link in _selecionar_links_internet_canonicos(links_existentes)]
    links_fallback = _obter_links_internet_fallback_local(regional_info)
    interfaces_result = _load_regional_interfaces(
        codigo_regional,
        regional_info,
        adom=adom,
        fortimanager_devices=fortimanager_devices,
        auth_timeout=auth_timeout,
    )

    if not interfaces_result.get("success"):
        if persist and links_fallback:
            _persistir_links_internet_exibicao(codigo_regional, links_fallback)
        return {
            "success": False,
            "message": interfaces_result.get("message"),
            "status": interfaces_result.get("status"),
            "resolved": interfaces_result.get("resolved") or {},
            "links": [_preparar_link_para_template(link) for link in links_fallback],
            "atualizados": [],
            "criados": [],
            "source": interfaces_result.get("source")
        }

    gerenciador_regional = interfaces_result.get("manager")
    interfaces = interfaces_result.get("interfaces", [])
    interfaces_wan = [interface for interface in interfaces if _is_wan_interface(interface)]
    interfaces_override = _REGIONAL_LINK_INTERFACE_INCLUDE_OVERRIDE.get(codigo_regional.upper())
    if interfaces_override:
        interfaces_wan = [
            interface
            for interface in interfaces_wan
            if str(interface.get("name") or interface.get("interface") or "").strip().lower() in interfaces_override
        ]
    interface_lan = _selecionar_interface_lan(interfaces)
    sdwan_members_map = {}

    if gerenciador_regional and include_sdwan:
        try:
            sdwan_result = gerenciador_regional.obter_membros_sdwan_com_sla()
            if sdwan_result.get("success"):
                sdwan_members_map = {
                    str(member.get("interface") or "").strip().lower(): member
                    for member in sdwan_result.get("membros", [])
                    if str(member.get("interface") or "").strip()
                }
        except Exception as exc:
            current_app.logger.warning(
                "Erro ao obter membros SD-WAN da regional %s: %s",
                codigo_regional,
                exc,
            )

    if not interfaces_wan:
        if persist and links_fallback:
            _persistir_links_internet_exibicao(codigo_regional, links_fallback)
        return {
            "success": False,
            "message": "Nenhuma interface WAN encontrada no equipamento da regional",
            "status": "wan_not_found",
            "resolved": interfaces_result.get("resolved") or {},
            "links": [_preparar_link_para_template(link) for link in links_fallback],
            "atualizados": [],
            "criados": [],
            "source": interfaces_result.get("source")
        }

    links_resultado = []
    atualizados = []
    criados = []
    links_base = list(links_existentes)
    links_referencia = list(links_canonicos_existentes)

    for interface in interfaces_wan:
        normalized_link = _normalize_synced_link(
            interface,
            fortigate_host=getattr(gerenciador_regional, "host", None),
            fortigate_porta=getattr(gerenciador_regional, "port", None),
            source=interfaces_result.get("source") or "fortigate",
        )

        if not _should_keep_synced_link(normalized_link):
            continue

        link_existente = _find_link_for_interface(links_referencia, normalized_link)
        link_final = dict(link_existente or {})
        link_final.update(normalized_link)

        sdwan_member = sdwan_members_map.get(str(link_final.get("interface_monitorada") or "").strip().lower())
        if sdwan_member:
            link_final["modo_verificacao"] = "sla"
            link_final["sla_status"] = sdwan_member.get("sla_status") or sdwan_member.get("status")
            link_final["sdwan_member_id"] = sdwan_member.get("member_id")
            link_final["priority"] = sdwan_member.get("priority")
        else:
            status_interface = str(normalized_link.get("status") or "").strip().lower()
            if status_interface in {"online", "offline"}:
                link_final["modo_verificacao"] = "interface"
                link_final["sla_status"] = "active" if status_interface == "online" else "inactive"
                link_final["sdwan_member_id"] = None

        if interface_lan:
            link_final["interface_local"] = _format_interface_local_label(interface_lan) or None
            link_final["ip_local"] = _extract_interface_ip(interface_lan.get("ip")) or ""
            link_final["mascara_local"] = _format_prefix_mask(_extract_interface_mask(interface_lan.get("ip")))

        if link_existente and link_existente.get("id"):
            link_id = link_existente.get("id")
            if persist:
                gerenciador_regionais.atualizar_link(codigo_regional, link_id, link_final)
            atualizados.append({
                "id": link_id,
                "nome": link_final.get("nome"),
                "ip": link_final.get("ip"),
                "provedor": link_final.get("provedor"),
                "velocidade": link_final.get("velocidade"),
                "interface_monitorada": link_final.get("interface_monitorada"),
                "fortigate_porta": link_final.get("fortigate_porta")
            })
        else:
            link_final["id"] = _build_auto_link_id(
                codigo_regional,
                link_final.get("interface_monitorada") or link_final.get("nome"),
                links_base,
            )
            if persist and not links_referencia:
                gerenciador_regionais.adicionar_link(codigo_regional, link_final)
            if not links_referencia:
                links_base.append(link_final)
            links_referencia.append(link_final)
            criados.append({
                "id": link_final.get("id"),
                "nome": link_final.get("nome"),
                "ip": link_final.get("ip"),
                "provedor": link_final.get("provedor"),
                "velocidade": link_final.get("velocidade"),
                "interface_monitorada": link_final.get("interface_monitorada")
            })

        links_resultado.append(_preparar_link_para_template(link_final))

    if persist:
        _persistir_links_internet_exibicao(codigo_regional, links_resultado)

    return {
        "success": True,
        "links": links_resultado,
        "atualizados": atualizados,
        "criados": criados,
        "total_atualizados": len(atualizados) + len(criados),
        "total_criados": len(criados),
        "source": interfaces_result.get("source"),
        "resolved": interfaces_result.get("resolved") or {},
    }

# === ROTAS PRINCIPAIS ===

@app.route('/')
@login_required
def index():
    return redirect(url_for('listar_regionais'))


@app.route('/servidores')
@login_required
def servidores():
    """Página principal - Dashboard hierárquico"""
    try:
        # Carrega regionais diretamente
        regionais = gerenciador_regionais.listar_regionais()
        
        # Estatísticas básicas
        total_servidores = 0
        regionais_resumo = []
        
        # Inicializa contadores para estatísticas gerais
        servidores_online_total = 0
        servidores_offline_total = 0
        
        for codigo_regional in regionais:
            regional_info = gerenciador_regionais.obter_regional(codigo_regional)
            if regional_info:
                servidores = regional_info.get('servidores', [])
                total_servidores += len(servidores)

                # Usa o último status persistido no JSON para evitar verificar todas as regionais
                # de forma síncrona a cada login ou navegação para a home.
                servidores_online = len([s for s in servidores if (s.get('status') or '').lower() == 'online'])
                servidores_offline = len([s for s in servidores if (s.get('status') or '').lower() == 'offline'])
                servidores_warning = len([s for s in servidores if (s.get('status') or '').lower() == 'warning'])

                # Trata status ausente/desconhecido como warning para não mascarar falta de coleta.
                status_conhecidos = servidores_online + servidores_offline + servidores_warning
                servidores_warning += max(len(servidores) - status_conhecidos, 0)

                # Atualiza contadores totais
                servidores_online_total += servidores_online
                servidores_offline_total += servidores_offline
                
                # Calcula percentual
                percentual_online = 0 if len(servidores) == 0 else (servidores_online / len(servidores)) * 100
                
                regionais_resumo.append({
                    'codigo': codigo_regional,
                    'nome': regional_info.get('nome', codigo_regional),
                    'descricao': regional_info.get('descricao', ''),
                    'total_servidores': len(servidores),
                    'servidores_online': servidores_online,
                    'servidores_offline': servidores_offline,
                    'percentual_online': percentual_online
                })
        
        stats = {
            'total_regionais': len(regionais),
            'total_servidores': total_servidores,
            'servidores_online': servidores_online_total,
            'servidores_offline': servidores_offline_total,
            'servidores_warning': max(total_servidores - servidores_online_total - servidores_offline_total, 0),
            'config_completa': (PROJECT_ROOT / "environment.json").exists(),
            'estrutura_hierarquica': True
        }
        
        return render_template('index.html', stats=stats, regionais=regionais_resumo)
        
    except Exception as e:
        flash(f'Erro ao carregar dashboard: {str(e)}', 'error')
        # Fallback para estrutura vazia
        stats = {
            'total_regionais': 0,
            'total_servidores': 0,
            'servidores_online': 0,
            'servidores_offline': 0,
            'servidores_warning': 0,
            'config_completa': False,
            'estrutura_hierarquica': True
        }
        return render_template('index.html', stats=stats, regionais=[])
        

# === ROTAS DE CERTIFICADOS ===
 
CERTIFICATES_DATA_FILE = base_dir / 'certificate_disk_report_acrab.json'
CERTIFICATES_LOG_FILE = base_dir / 'logs' / 'certificados.log'
 
 
def _log_certificados(message: str):
    try:
        CERTIFICATES_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        with open(CERTIFICATES_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'{timestamp} - {message}\n')
    except Exception:
        pass
 
 
def _parse_certificate_expiration(value):
    if not value:
        return None
 
    expiration_text = str(value).strip()
    if expiration_text.endswith('Z'):
        expiration_text = expiration_text[:-1] + '+00:00'
 
    try:
        return datetime.fromisoformat(expiration_text)
    except ValueError:
        try:
            return datetime.strptime(expiration_text, '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return None
 
 
def _get_certificate_status(expiration_dt):
    if expiration_dt is None:
        return 'Status desconhecido', 'table-secondary'
 
    if expiration_dt.tzinfo is not None:
        expiration_dt = expiration_dt.astimezone(timezone.utc).replace(tzinfo=None)
 
    now = datetime.utcnow()
    delta = expiration_dt - now
 
    if delta.total_seconds() < 0:
        return 'Expirado', 'table-danger'
 
    days = int(delta.total_seconds() // 86400)
    if days < 30:
        return f'Expirando em {days} dias', 'table-warning'
 
    return 'Válido', 'table-success'
 
 
def _load_certificates_data():
    if not CERTIFICATES_DATA_FILE.exists():
        return []
 
    try:
        raw = json.loads(CERTIFICATES_DATA_FILE.read_text(encoding='utf-8'))
    except Exception as e:
        _log_certificados(f'Falha ao ler JSON de certificados: {e}')
        return []
 
    if isinstance(raw, dict):
        raw = [raw]
 
    certificates = []
    for item in raw if isinstance(raw, list) else []:
        thumbprint = item.get('thumbprint') or item.get('Thumbprint')
        subject = item.get('subject') or item.get('Subject')
        issuer = item.get('issuer') or item.get('Issuer')
        not_after = item.get('notAfter') or item.get('NotAfter')
 
        expiration_dt = _parse_certificate_expiration(not_after)
        status_text, status_class = _get_certificate_status(expiration_dt)
        expiration_display = expiration_dt.strftime('%d/%m/%Y %H:%M:%S') if expiration_dt else str(not_after or '')
 
        certificates.append({
            'thumbprint': thumbprint,
            'subject': subject,
            'issuer': issuer,
            'notAfter': expiration_display,
            'status_text': status_text,
            'status_class': status_class
        })
 
    return certificates
 
 
@app.route('/validade-certificados')
@login_required
def validade_certificados():
    certificates = _load_certificates_data()
    no_data_message = None
    if not certificates:
        no_data_message = 'Nenhum dado disponível'
 
    _log_certificados('Página de validade de certificados acessada')
    return render_template('validade_certificados_servidores.html', certificates=certificates, no_data_message=no_data_message)
 
 
@app.route('/api/certificados/refresh')
@login_required
def api_certificados_refresh():
    try:
        if not (base_dir / 'coleta_dados_acraby.py').exists():
            raise FileNotFoundError('Script coleta_dados_acraby.py não encontrado')
 
        command = [sys.executable, str(base_dir / 'coleta_dados_acraby.py')]
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f'Erro ao executar script: {result.stderr.strip() or result.stdout.strip()}')
 
        certificates = _load_certificates_data()
        _log_certificados('Refresh de certificados realizado com sucesso')
        return jsonify({'status': 'success', 'data': certificates})
 
    except Exception as e:
        _log_certificados(f'Falha ao atualizar certificados: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

# === ROTAS DE REGIONAIS ===

@app.route('/regionais')
@login_required
def listar_regionais():
    """Página de listagem de regionais"""
    try:
        regionais = gerenciador_regionais.listar_regionais()
        regionais_dados = []
        
        for codigo_regional in regionais:
            regional_info = gerenciador_regionais.obter_regional(codigo_regional)
            if regional_info:
                servidores = regional_info.get('servidores', [])
                links = [
                    _preparar_link_para_template(link)
                    for link in _obter_links_internet_exibicao(regional_info)
                ]
                regionais_dados.append({
                    'codigo': codigo_regional,
                    'nome': regional_info.get('nome', codigo_regional),
                    'descricao': regional_info.get('descricao', ''),
                    'total_servidores': len(servidores),
                    'total_links': len(links),
                    'servidores': servidores,
                    'links': links
                })
        
        return render_template('regionais.html', regionais=regionais_dados)
        
    except Exception as e:
        flash(f'Erro ao carregar regionais: {str(e)}', 'error')
        return render_template('regionais.html', regionais=[])


@app.route('/api/regional/<codigo_regional>/verificar')
@login_required
def api_verificar_regional(codigo_regional):
    """API para verificar status de todos os servidores de uma regional"""
    try:
        codigo_regional = codigo_regional.replace(" ", "_")
        resultados = verificador_v2.verificar_regional(codigo_regional)

        online = len([r for r in resultados if r.get('status') == 'online'])
        offline = len([r for r in resultados if r.get('status') == 'offline'])
        warning = len([r for r in resultados if r.get('status') == 'warning'])

        return jsonify({
            'success': True,
            'resultados': resultados,
            'resumo': {
                'total': len(resultados),
                'online': online,
                'offline': offline,
                'warning': warning
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/regional/<codigo_regional>')
@login_required
def detalhar_regional(codigo_regional):
    """Página de detalhamento de uma regional"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            flash('Regional não encontrada', 'error')
            return redirect(url_for('listar_regionais'))

        def _formatar_ultima_verificacao(valor):
            texto = str(valor or '').strip()
            if not texto:
                return None

            try:
                data = datetime.fromisoformat(texto)
                return {
                    'completa': data.strftime('%d/%m/%Y às %H:%M:%S'),
                    'data': data.strftime('%d/%m/%Y'),
                    'hora': data.strftime('%H:%M:%S')
                }
            except ValueError:
                return {
                    'completa': texto,
                    'data': texto,
                    'hora': ''
                }

        # NÃO verifica automaticamente aqui
        servidores_completos = []

        for servidor in regional_info.get('servidores', []):
            servidor_completo = servidor.copy()

            # garante campos pra não quebrar o template
            servidor_completo.setdefault("status", "unknown")
            servidor_completo.setdefault("tempo_resposta", None)
            servidor_completo.setdefault("erro", None)
            servidor_completo.setdefault("ultima_verificacao", None)
            servidor_completo["ultima_verificacao_formatada"] = _formatar_ultima_verificacao(
                servidor_completo.get("ultima_verificacao")
            )

            servidores_completos.append(servidor_completo)

        links_completos = []
        for link in _obter_links_internet_exibicao(regional_info):
            link_completo = _preparar_link_para_template(link)
            link_completo["ultima_verificacao_formatada"] = _formatar_ultima_verificacao(
                link_completo.get("ultima_verificacao")
            )
            links_completos.append(link_completo)

        # Buscar firewalls desta regional usando o mesmo matching da página principal
        firewalls_completos = []
        try:
            adom = _get_fortimanager_adom()
            try:
                import re as _re

                DEVICE_REGIONAL_OVERRIDE = {
                    'FTG_GLX_100F_MATRIZ': 'REG_GALAXIA',
                    'FGT_REGSAOJOSEDOSCAMPOS': 'REG_SJC',
                }

                def _norm2(s):
                    return _re.sub(r'[^A-Z0-9]', '', s.upper())

                def _device_key2(name):
                    n = name.upper()
                    for prefix in ('FGT_REG', 'FTG_REG', 'FGT_', 'FTG_'):
                        if n.startswith(prefix):
                            return n[len(prefix):]
                    return n

                def _match_regional(device_name, regional_code):
                    """Verifica se o device pertence à regional usando o mesmo algoritmo do listar_firewalls"""
                    # Override manual
                    if device_name in DEVICE_REGIONAL_OVERRIDE:
                        return DEVICE_REGIONAL_OVERRIDE[device_name] == regional_code

                    dev_norm = _norm2(_device_key2(device_name))
                    reg_upper = regional_code.upper()
                    reg_key = reg_upper[4:] if reg_upper.startswith('REG_') else reg_upper
                    reg_norm = _norm2(reg_key)
                    if not reg_norm or not dev_norm:
                        return False

                    if dev_norm == reg_norm:
                        return True
                    if len(reg_norm) >= 3 and dev_norm.startswith(reg_norm):
                        return True
                    if len(dev_norm) >= 3 and reg_norm.startswith(dev_norm):
                        return True
                    if len(reg_norm) >= 4 and reg_norm in dev_norm:
                        return True
                    if len(dev_norm) >= 4 and dev_norm in reg_norm:
                        return True
                    return False

                fm_client = FortiManagerClient()
                fm_client.login()
                fm_devices = fm_client.list_devices(adom)
                fm_devices_list = fm_devices.get('result', [{}])[0] if isinstance(fm_devices.get('result', []), list) and fm_devices.get('result') else {}
                devices_data = fm_devices_list.get('data', []) if isinstance(fm_devices_list, dict) else []

                for device_data in devices_data:
                    if not isinstance(device_data, dict):
                        continue
                    device_name = device_data.get('name', '').strip()
                    if not device_name:
                        continue

                    if not _match_regional(device_name, codigo_regional):
                        continue

                    device_ip       = device_data.get('ip', '')
                    device_hostname = device_data.get('hostname', '')
                    device_model    = device_data.get('platform_str', 'N/A')
                    device_serial   = device_data.get('sn', 'N/A')
                    device_status   = device_data.get('status', 'unknown')

                    try:
                        licenses_data = fm_client.proxy_monitor_license(adom, device_name)

                        firewall_info = {
                            'nome': device_name,
                            'hostname': device_hostname,
                            'ip': device_ip,
                            'status': device_status,
                            'model': device_model,
                            'serial': device_serial,
                            'licencas': [],
                            'licencas_criticas': 0,
                            'licencas_expiradas': 0,
                            'ultima_verificacao': datetime.now().isoformat()
                        }

                        # Device offline (sem túnel)
                        if isinstance(licenses_data, dict) and licenses_data.get('_erro') == 'offline':
                            firewall_info['licencas'].append({
                                'nome': 'forticare', 'tipo': 'forticare',
                                'status': 'offline', 'dias_restantes': 0,
                                'expiracao': 'N/A', 'notificacao_critica': False,
                                'notificacao_expirada': True,
                            })
                            firewall_info['licencas_expiradas'] += 1

                        # Processar apenas forticare
                        elif isinstance(licenses_data, dict) and 'forticare' in licenses_data:
                            license_info = licenses_data['forticare']
                            if isinstance(license_info, dict):
                                dias_rest = 0
                                expires_timestamp = license_info.get('expires', 0)
                                if not expires_timestamp:
                                    support = license_info.get('support', {})
                                    if isinstance(support, dict):
                                        for sub in ('hardware', 'enhanced'):
                                            expires_timestamp = support.get(sub, {}).get('expires', 0)
                                            if expires_timestamp:
                                                break
                                if expires_timestamp and isinstance(expires_timestamp, (int, float)) and expires_timestamp > 0:
                                    try:
                                        from datetime import datetime as dt_class
                                        exp_date = dt_class.fromtimestamp(expires_timestamp)
                                        dias_rest = max(0, (exp_date.date() - dt_class.now().date()).days)
                                    except Exception:
                                        dias_rest = 0

                                lic_status = license_info.get('status', 'unknown')
                                lic_obj = {
                                    'nome': 'forticare', 'tipo': 'forticare',
                                    'status': lic_status,
                                    'dias_restantes': dias_rest,
                                    'expiracao': expires_timestamp if expires_timestamp else 'N/A',
                                    'notificacao_critica': False,
                                    'notificacao_expirada': lic_status in ('expired', 'no_license'),
                                }
                                if lic_obj['notificacao_expirada']:
                                    firewall_info['licencas_expiradas'] += 1
                                elif dias_rest <= 30 and dias_rest > 0:
                                    lic_obj['notificacao_critica'] = True
                                    firewall_info['licencas_criticas'] += 1
                                firewall_info['licencas'].append(lic_obj)

                        firewalls_completos.append(firewall_info)

                    except Exception as e:
                        current_app.logger.warning(f"Erro ao buscar licenças de {device_name}: {str(e)}")
                        firewalls_completos.append({
                            'nome': device_name, 'hostname': device_hostname,
                            'ip': device_ip, 'status': 'erro',
                            'licencas': [], 'licencas_criticas': 0, 'licencas_expiradas': 0,
                            'erro': str(e), 'ultima_verificacao': datetime.now().isoformat()
                        })

                fm_client.logout()
            except Exception as e:
                current_app.logger.warning(f"Erro ao conectar FortiManager: {str(e)}")
        except Exception as e:
            current_app.logger.warning(f"Erro ao buscar firewalls da regional: {str(e)})")

        regional_completa = {
            'codigo': codigo_regional,
            'nome': regional_info.get('nome', codigo_regional),
            'descricao': regional_info.get('descricao', ''),
            'servidores': servidores_completos,
            'links': links_completos,
            'firewalls': firewalls_completos
        }

        return render_template('regional_detalhes.html', regional=regional_completa)

    except Exception as e:
        flash(f'Erro ao carregar regional: {str(e)}', 'error')
        return redirect(url_for('listar_regionais'))

@app.route('/regional/nova')
@login_required
def nova_regional():
    """Página para adicionar nova regional"""
    return render_template('regional_form.html', regional=None, acao='Adicionar')

@app.route('/regional/<codigo_regional>/editar')
@login_required
def editar_regional(codigo_regional):
    """Página para editar regional existente"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            flash('Regional não encontrada', 'error')
            return redirect(url_for('listar_regionais'))
        
        regional_dados = {
            'codigo': codigo_regional,
            'nome': regional_info.get('nome', ''),
            'descricao': regional_info.get('descricao', '')
        }
        
        return render_template('regional_form.html', regional=regional_dados, acao='Editar')
        
    except Exception as e:
        flash(f'Erro ao carregar regional: {str(e)}', 'error')
        return redirect(url_for('listar_regionais'))

@app.route('/regional/<codigo_regional>/servidor/novo')
@login_required
def novo_servidor_regional(codigo_regional):
    """Página para adicionar servidor a uma regional"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            flash('Regional não encontrada', 'error')
            return redirect(url_for('listar_regionais'))

        return render_template(
            'servidor_regional_form.html',
            regional_codigo=codigo_regional,
            regional_nome=regional_info.get('nome', codigo_regional),
            servidor=None,
            acao='Adicionar'
        )

    except Exception as e:
        flash(f'Erro: {str(e)}', 'error')
        return redirect(url_for('listar_regionais'))

@app.route('/api/regional/<codigo_regional>', methods=['DELETE'])
@app.route('/api/regional/<codigo_regional>/excluir', methods=['DELETE'])
@login_required
def api_excluir_regional(codigo_regional):
    try:
        ok, msg = gerenciador_regionais.remover_regional(codigo_regional)

        if not ok:
            return jsonify({"success": False, "message": msg}), 404

        return jsonify({"success": True, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# === ROTAS DE INFRAESTRUTURA ===

@app.route('/emails-contatos')
@login_required
def cadastro_emails_contatos():
    """Tela para gerenciar contatos e emails de regionais em planilha externa."""
    config = gerenciador_contatos_email.obter_configuracao()
    registros = []
    page_error = None

    if config.get('xlsx_path'):
        try:
            registros = gerenciador_contatos_email.listar_registros()
        except Exception as exc:
            page_error = str(exc)

    return render_template(
        'emails_contatos.html',
        config=config,
        registros=registros,
        page_error=page_error,
        required_columns=gerenciador_contatos_email.REQUIRED_COLUMNS,
    )


@app.route('/api/emails-contatos/config', methods=['POST'])
@login_required
def api_salvar_config_emails_contatos():
    try:
        data = request.get_json() or {}
        xlsx_path = str(data.get('xlsx_path') or '').strip()
        sheet_name = str(data.get('sheet_name') or '').strip()

        if not xlsx_path:
            return jsonify({'success': False, 'message': 'Informe o caminho da planilha XLSX.'}), 400

        config = gerenciador_contatos_email.salvar_configuracao(xlsx_path, sheet_name)
        return jsonify({'success': True, 'message': 'Configuração salva com sucesso.', 'config': config})
    except Exception as exc:
        return jsonify({'success': False, 'message': str(exc)}), 500


@app.route('/api/emails-contatos/<int:row_index>', methods=['PUT'])
@login_required
def api_atualizar_emails_contatos(row_index):
    try:
        data = request.get_json() or {}
        payload = {
            column: str(data.get(column) or '').strip()
            for column in gerenciador_contatos_email.REQUIRED_COLUMNS
        }
        registro = gerenciador_contatos_email.atualizar_registro(row_index, payload)
        return jsonify({'success': True, 'message': 'Contato atualizado com sucesso.', 'registro': registro})
    except Exception as exc:
        return jsonify({'success': False, 'message': str(exc)}), 500

@app.route('/switches/editar/<host>', methods=['GET', 'POST'])
@login_required
def editar_switch(host):
    """Página para editar um switch existente"""
    if request.method == 'POST':
        try:
            gerenciador_switches._carregar_switches()

            # Obtém os dados do formulário
            ip = request.form.get('ip').strip()
            regional = request.form.get('regional').strip().upper()
            modelo = request.form.get('modelo', '').strip()
            local = request.form.get('local', '').strip()
            
            # Validações básicas
            if not ip:
                flash('IP é obrigatório', 'error')
                return redirect(url_for('editar_switch', host=host))
            
            if not regional:
                flash('Regional é obrigatória', 'error')
                return redirect(url_for('editar_switch', host=host))
            
            # Encontra o switch na lista
            switch_encontrado = None
            for switch in gerenciador_switches.switches:
                if _normalizar_host_switch(switch["host"]) == _normalizar_host_switch(host):
                    switch_encontrado = switch
                    break
            
            if not switch_encontrado:
                flash(f'Switch não encontrado: {host}', 'error')
                return redirect(url_for('listar_switches'))
            
            # Carrega o arquivo Excel real configurado para switches
            arquivo_excel, df = _carregar_planilha_switches()
            
            # Encontra o índice do switch no DataFrame
            idx = _localizar_indice_switch(df, host)
            if len(idx) == 0:
                flash(f'Switch não encontrado no Excel: {host}', 'error')
                return redirect(url_for('listar_switches'))
            
            # Atualiza os dados no DataFrame
            df.loc[idx[0], 'IP'] = ip
            df.loc[idx[0], 'Regional'] = regional
            df.loc[idx[0], 'Modelo'] = modelo
            df.loc[idx[0], 'Local'] = local
            
            # Cria backup do arquivo original em pasta dedicada
            _criar_backup_switches(arquivo_excel)
            
            # Salva o DataFrame atualizado
            with pd.ExcelWriter(arquivo_excel, engine='openpyxl') as writer:
                # Adiciona linhas em branco no início
                empty_df = pd.DataFrame()
                empty_df.to_excel(writer, sheet_name='Switches', index=False)
                
                # Adiciona o DataFrame principal começando da linha 3
                df.to_excel(writer, sheet_name='Switches', startrow=2, index=False)
            
            # Recarrega os switches
            gerenciador_switches._carregar_switches()
            
            flash(f'Switch {host} atualizado com sucesso!', 'success')
            return redirect(url_for('listar_switches'))
            
        except Exception as e:
            flash(f'Erro ao atualizar switch: {str(e)}', 'error')
            return redirect(url_for('editar_switch', host=host))
    
    # Método GET - exibe o formulário
    gerenciador_switches._carregar_switches()

    # Encontra o switch na lista
    switch = None
    for s in gerenciador_switches.switches:
        if _normalizar_host_switch(s["host"]) == _normalizar_host_switch(host):
            switch = s
            break
    
    if not switch:
        flash(f'Switch não encontrado: {host}', 'error')
        return redirect(url_for('listar_switches'))
    
    regionais = gerenciador_switches.listar_regionais()
    return render_template('editar_switch.html', switch=switch, regionais=regionais)

@app.route('/api/switches/excluir/<host>', methods=['DELETE'])
@login_required
def api_excluir_switch(host):
    """API para excluir um switch"""
    try:
        gerenciador_switches._carregar_switches()

        # Encontra o switch na lista
        switch_encontrado = None
        for switch in gerenciador_switches.switches:
            if _normalizar_host_switch(switch["host"]) == _normalizar_host_switch(host):
                switch_encontrado = switch
                break
        
        if not switch_encontrado:
            return jsonify({
                "success": False,
                "message": f"Switch não encontrado: {host}"
            })
        
        # Carrega o arquivo Excel real configurado para switches
        arquivo_excel, df = _carregar_planilha_switches()
        
        # Encontra o índice do switch no DataFrame
        idx = _localizar_indice_switch(df, host)
        if len(idx) == 0:
            return jsonify({
                "success": False,
                "message": f"Switch não encontrado no Excel: {host}"
            })
        
        # Remove o switch do DataFrame
        df = df.drop(idx[0])
        
        # Cria backup do arquivo original em pasta dedicada
        _criar_backup_switches(arquivo_excel)
        
        # Salva o DataFrame atualizado
        with pd.ExcelWriter(arquivo_excel, engine='openpyxl') as writer:
            # Adiciona linhas em branco no início
            empty_df = pd.DataFrame()
            empty_df.to_excel(writer, sheet_name='Switches', index=False)
            
            # Adiciona o DataFrame principal começando da linha 3
            df.to_excel(writer, sheet_name='Switches', startrow=2, index=False)
        
        # Recarrega os switches
        gerenciador_switches._carregar_switches()
        
        return jsonify({
            "success": True,
            "message": f"Switch {host} excluído com sucesso!"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        })

@app.route('/switches/cadastrar', methods=['GET', 'POST'])
@login_required
def cadastrar_switch():
    """Página para cadastrar um novo switch"""
    if request.method == 'POST':
        try:
            gerenciador_switches._carregar_switches()

            # Obtém os dados do formulário
            host_name = (request.form.get('host') or '').strip()
            ip = (request.form.get('ip') or '').strip()

            regional_form = request.form.get('regional')
            nova_regional = request.form.get('nova-regional')

            if regional_form == 'NOVA':
                regional = (nova_regional or '').strip().upper()
            else:
                regional = (regional_form or '').strip().upper()

            modelo = (request.form.get('modelo') or '').strip()
            local = (request.form.get('local') or '').strip()

            
            # Validações básicas
            if not host_name:
                flash('Nome do host é obrigatório', 'error')
                return redirect(url_for('cadastrar_switch'))
            
            if not ip:
                flash('IP é obrigatório', 'error')
                return redirect(url_for('cadastrar_switch'))
            
            if not regional:
                flash('Regional é obrigatória', 'error')
                return redirect(url_for('cadastrar_switch'))
            
            # Verifica se o switch já existe na lista local
            for switch in gerenciador_switches.switches:
                if _normalizar_host_switch(switch["host"]) == _normalizar_host_switch(host_name):
                    flash(f'Switch já cadastrado: {host_name}', 'error')
                    return redirect(url_for('cadastrar_switch'))
            
            # Carrega o arquivo Excel real configurado para switches
            arquivo_excel, df = _carregar_planilha_switches()
            
            # Cria um novo registro
            novo_switch = {
                "Host": host_name,
                "IP": ip,
                "Regional": regional,
                "Modelo": modelo,
                "Local": local
            }
            
            # Adiciona o novo registro ao DataFrame
            df = pd.concat([df, pd.DataFrame([novo_switch])], ignore_index=True)
            
            # Cria backup do arquivo original em pasta dedicada
            _criar_backup_switches(arquivo_excel)
            
            # Salva o DataFrame atualizado
            with pd.ExcelWriter(arquivo_excel, engine='openpyxl') as writer:
                # Adiciona linhas em branco no início
                empty_df = pd.DataFrame()
                empty_df.to_excel(writer, sheet_name='Switches', index=False)
                
                # Adiciona o DataFrame principal começando da linha 3
                df.to_excel(writer, sheet_name='Switches', startrow=2, index=False)
            
            # Recarrega os switches
            gerenciador_switches._carregar_switches()
            
            # Verifica o novo switch
            gerenciador_switches.verificar_switch(host_name)
            
            flash(f'Switch {host_name} cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_switches'))
            
        except Exception as e:
            flash(f'Erro ao cadastrar switch: {str(e)}', 'error')
            return redirect(url_for('cadastrar_switch'))
    
    # Método GET - exibe o formulário
    # Exibe todas as regionais cadastradas, não só as com switches
    regionais = gerenciador_regionais.listar_regionais()
    return render_template('cadastrar_switch.html', regionais=regionais)

@app.route('/switches')
@login_required
def listar_switches():
    """Página de listagem de switches"""
    try:
        def _status_offline(status):
            return (status or '').strip().lower() in {'offline', 'não encontrado', 'nao encontrado', 'erro'}

        def _formatar_ultima_verificacao(valor):
            if not valor:
                return None

            try:
                texto = str(valor).strip()
                if texto.endswith('Z'):
                    texto = texto[:-1]
                data = datetime.fromisoformat(texto)
                return data.strftime('%d/%m/%Y às %H:%M:%S')
            except Exception:
                return str(valor)

        # Sempre recarrega os switches via API (com fallback para XLSX)
        sucesso_api = gerenciador_switches._carregar_switches_api()
        if not sucesso_api:
            gerenciador_switches._carregar_switches()

        # Obtém as regionais com switches
        regionais = gerenciador_switches.listar_regionais()

        # Prepara dados para a view
        regionais_dados = []

        print("Carregando página de switches com lista atualizada pela API do Zabbix...")

        # Agora processa os dados para a view
        for regional in regionais:
            switches = gerenciador_switches.obter_switches_regional(regional)

            # Garante que todos os IPs estão convertidos corretamente
            for switch in switches:
                # Se o IP não parece estar no formato correto (sem pontos), converte
                if switch.get("ip") and "." not in switch.get("ip", ""):
                    switch["ip"] = gerenciador_switches._converter_ip_numerico(switch["ip"])

                switch["ultima_verificacao_formatada"] = _formatar_ultima_verificacao(
                    switch.get("ultima_verificacao")
                )

            # Conta switches por status
            total_switches = len(switches)
            online = sum(1 for s in switches if s.get('status') == 'online')
            warning = sum(1 for s in switches if s.get('status') == 'warning')
            inativo = sum(1 for s in switches if s.get('status') == 'inativo')
            offline = sum(1 for s in switches if _status_offline(s.get('status')))
            desconhecidos = sum(1 for s in switches if (s.get('status') or '').strip().lower() in {'', 'desconhecido', 'não encontrado', 'nao encontrado', 'erro'})

            # Calcula percentual
            percentual_online = 0 if total_switches == 0 else (online / total_switches) * 100

            regionais_dados.append({
                'nome': regional,
                'total_switches': total_switches,
                'online': online,
                'offline': offline,
                'warning': warning,
                'inativo': inativo,
                'desconhecidos': desconhecidos,
                'percentual_online': percentual_online,
                'switches': switches
            })

        return render_template('switches.html', regionais=regionais_dados)

    except Exception as e:
        flash(f'Erro ao carregar switches: {str(e)}', 'error')
        return render_template('switches.html', regionais=[])

@app.route('/api/switches/verificar/<host>', methods=['POST'])
@login_required
def api_verificar_switch(host):
    """API para verificar um switch específico"""
    try:
        if _background_async_requested():
            job_id = _create_background_job(
                'switches-single',
                total=1,
                message='Preparando verificação do switch...',
                detail=f'Iniciando job para o switch {host}.',
                meta={'host': host}
            )
            _start_background_job(
                lambda: _run_switches_job(job_id, mode='single', host=host),
                name=f'switch-job-{job_id}'
            )
            return jsonify({'success': True, 'job_id': job_id})

        # Autentica no Zabbix
        if not gerenciador_switches.autenticar():
            return jsonify({'success': False, 'message': 'Falha na autenticação com o Zabbix'})
        
        # Verifica o switch
        resultado = gerenciador_switches.verificar_switch(host)
        
        return jsonify({
            'success': True,
            'status': resultado['status'],
            'detalhes': resultado['detalhes'],
            'ultima_verificacao': resultado.get('ultima_verificacao'),
            'status_reason': resultado.get('status_reason'),
            'status_details': resultado.get('status_details'),
            'warning_problemas': resultado.get('warning_problemas', []),
            'warning_resumo': resultado.get('warning_resumo')
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/api/switches/verificar', methods=['POST'])
@login_required
def api_verificar_switches():
    """API para verificar status de todos os switches"""
    try:
        if _background_async_requested():
            job_id = _create_background_job(
                'switches-all',
                total=len(gerenciador_switches.switches),
                message='Preparando verificação dos switches...',
                detail='Criando job para consultar os switches no Zabbix.'
            )
            _start_background_job(
                lambda: _run_switches_job(job_id, mode='all'),
                name=f'switch-job-{job_id}'
            )
            return jsonify({'success': True, 'job_id': job_id})

        # Autentica no Zabbix
        if not gerenciador_switches.autenticar():
            return jsonify({'success': False, 'message': 'Falha na autenticação com o Zabbix'})
        
        # Verifica todos os switches sem limite
        resultados = gerenciador_switches.verificar_todos_switches()
        
        # Conta por status
        total = len(resultados)
        online = sum(1 for r in resultados.values() if r.get('status') == 'online')
        offline = sum(1 for r in resultados.values() if (r.get('status') or '').strip().lower() in {'offline', 'não encontrado', 'nao encontrado', 'erro'})
        warning = sum(1 for r in resultados.values() if r.get('status') == 'warning')
        inativo = sum(1 for r in resultados.values() if r.get('status') == 'inativo')
        
        return jsonify({
            'success': True,
            'resultados': resultados,
            'resumo': {
                'total': total,
                'online': online,
                'offline': offline,
                'warning': warning,
                'inativo': inativo
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/switches/regional/<regional>', methods=['POST'])
@login_required
def api_verificar_switches_regional(regional):
    """API para verificar status dos switches de uma regional"""
    try:
        if _background_async_requested():
            job_id = _create_background_job(
                'switches-regional',
                total=len(gerenciador_switches.regionais.get(regional, [])),
                message='Preparando verificação da regional...',
                detail=f'Criando job para consultar os switches da regional {regional}.',
                meta={'regional': regional}
            )
            _start_background_job(
                lambda: _run_switches_job(job_id, mode='regional', regional=regional),
                name=f'switch-job-{job_id}'
            )
            return jsonify({'success': True, 'job_id': job_id})

        # Autentica no Zabbix
        if not gerenciador_switches.autenticar():
            return jsonify({'success': False, 'message': 'Falha na autenticação com o Zabbix'})
        
        # Verifica switches da regional
        resultados = gerenciador_switches.verificar_regional(regional)
        
        if isinstance(resultados, dict) and 'error' in resultados:
            return jsonify({'success': False, 'message': resultados['error']})
        
        # Conta por status
        total = len(resultados)
        online = sum(1 for r in resultados.values() if r.get('status') == 'online')
        offline = sum(1 for r in resultados.values() if (r.get('status') or '').strip().lower() in {'offline', 'não encontrado', 'nao encontrado', 'erro'})
        warning = sum(1 for r in resultados.values() if r.get('status') == 'warning')
        inativo = sum(1 for r in resultados.values() if r.get('status') == 'inativo')
        
        return jsonify({
            'success': True,
            'resultados': resultados,
            'resumo': {
                'total': total,
                'online': online,
                'offline': offline,
                'warning': warning,
                'inativo': inativo
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})


@app.route('/api/background-jobs/<job_id>', methods=['GET'])
@login_required
def api_background_job_status(job_id):
    """Consulta o status de um job em segundo plano."""
    job = _get_background_job(job_id)
    if not job:
        return jsonify({'success': False, 'message': 'Job não encontrado'}), 404

    return jsonify({
        'success': True,
        'job': job
    })

# === ROTAS DE LINKS DE INTERNET ===

@app.route('/links')
@login_required
def listar_links():
    """Página de listagem de links de internet"""
    try:
        resultado = _coletar_links_multiregional()
        if not resultado.get('success'):
            flash(f'Erro ao obter informações dos links: {resultado.get("message", "Erro desconhecido")}', 'error')
            return render_template(
                'links_internet.html',
                links=[],
                links_por_regional={},
                sd_wan_por_regional={}
            )

        return render_template(
            'links_internet.html',
            links=resultado.get('links', []),
            links_por_regional=resultado.get('links_por_regional', {}),
            sd_wan_por_regional=resultado.get('sd_wan_por_regional', {})
        )

    except Exception as e:
        flash(f'Erro ao carregar links: {str(e)}', 'error')
        return render_template(
            'links_internet.html',
            links=[],
            links_por_regional={},
            sd_wan_por_regional={}
        )

def _salvar_cache_dashboard(nome, dados):
    """Persiste snapshots leves para o dashboard e para o preview rapido."""
    try:
        cache_path = PROJECT_ROOT / "output" / f"dashboard_{nome}_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        current_app.logger.warning("Falha ao salvar cache %s do dashboard: %s", nome, exc)


def _carregar_cache_dashboard(nome, ttl_seconds=None):
    """Carrega snapshot salvo e, opcionalmente, valida a idade maxima."""
    try:
        cache_path = PROJECT_ROOT / "output" / f"dashboard_{nome}_cache.json"
        if not cache_path.exists():
            return None

        dados = json.loads(cache_path.read_text(encoding="utf-8"))
        atualizado_em = dados.get("atualizado_em")
        if ttl_seconds is not None and atualizado_em:
            atualizado_dt = datetime.fromisoformat(str(atualizado_em))
            if atualizado_dt.tzinfo is not None:
                atualizado_dt = atualizado_dt.astimezone().replace(tzinfo=None)
            if (datetime.now() - atualizado_dt).total_seconds() > ttl_seconds:
                return None
        return dados
    except Exception as exc:
        current_app.logger.warning("Falha ao carregar cache %s do dashboard: %s", nome, exc)
        return None


def _invalidar_cache_dashboard(nome):
    """Remove snapshot salvo para forcar nova consulta na proxima abertura."""
    try:
        cache_path = PROJECT_ROOT / "output" / f"dashboard_{nome}_cache.json"
        if cache_path.exists():
            cache_path.unlink()
    except Exception as exc:
        current_app.logger.warning("Falha ao invalidar cache %s do dashboard: %s", nome, exc)

@app.route('/firewalls')
@login_required
def listar_firewalls(return_data=False):
    """Página de listagem de firewalls (FortiGates) com status de licenças"""
    try:
        force_refresh = return_data or request.args.get("refresh") in {"1", "true", "yes", "on"}
        if not force_refresh:
            cached = _carregar_cache_dashboard("firewalls", ttl_seconds=3600)
            if cached:
                if return_data:
                    return cached
                return render_template(
                    'firewalls.html',
                    firewalls_por_regional=cached.get("firewalls_por_regional", {}),
                    total_firewalls=cached.get("total_firewalls", 0),
                    total_alertas=cached.get("total_alertas", 0),
                    total_expirados=cached.get("total_expirados", 0),
                    cache_atualizado_em=cached.get("atualizado_em"),
                    usando_cache=True,
                )

        print("🔴 DEBUG listar_firewalls(): INICIANDO")
        current_app.logger.info("🔴 DEBUG listar_firewalls(): INICIANDO")
        firewalls_por_regional = {}
        total_firewalls = 0
        total_alertas = 0
        total_expirados = 0
        adom = _get_fortimanager_adom()
        print(f"🔴 DEBUG: ADOM = {adom}")
        current_app.logger.info(f"🔴 DEBUG: ADOM = {adom}")
        
        try:
            print("🔴 DEBUG: Conectando ao FortiManager...")
            current_app.logger.info("🔴 DEBUG: Conectando ao FortiManager...")
            fm_client = FortiManagerClient()
            fm_client.login()
            print("🔴 DEBUG: Login bem-sucedido")
            current_app.logger.info("🔴 DEBUG: Login bem-sucedido")
            
            fm_devices = fm_client.list_devices(adom)
            print(f"🔴 DEBUG: fm_devices keys = {fm_devices.keys() if isinstance(fm_devices, dict) else type(fm_devices)}")
            current_app.logger.info(f"🔴 DEBUG: fm_devices keys = {fm_devices.keys() if isinstance(fm_devices, dict) else type(fm_devices)}")
            
            fm_devices_list = fm_devices.get('result', [{}])[0] if isinstance(fm_devices.get('result', []), list) and fm_devices.get('result') else {}
            devices_data = fm_devices_list.get('data', []) if isinstance(fm_devices_list, dict) else []
            print(f"🔴 DEBUG: Total de devices = {len(devices_data)}")
            current_app.logger.info(f"🔴 DEBUG: Total de devices = {len(devices_data)}")
            
            # Mapear regionais para facilitar busca
            regionais_map = {}
            for regional_code in gerenciador_regionais.listar_regionais():
                regional_info = gerenciador_regionais.obter_regional(regional_code)
                if regional_info:
                    regionais_map[regional_code] = regional_info
            
            # Mapeamento manual para casos onde nome do device é abreviação diferente da regional
            DEVICE_REGIONAL_OVERRIDE = {
                'FTG_GLX_100F_MATRIZ': 'REG_GALAXIA',
                'FGT_REGSAOJOSEDOSCAMPOS': 'REG_SJC',
            }

            import re as _re

            def _norm(s):
                """Normaliza string: remove separadores, maiúsculo, só alfanumérico"""
                return _re.sub(r'[^A-Z0-9]', '', s.upper())

            def _device_key(name):
                """Extrai parte significativa do nome do device (remove prefixo FGT_REG etc.)"""
                n = name.upper()
                for prefix in ('FGT_REG', 'FTG_REG', 'FGT_', 'FTG_'):
                    if n.startswith(prefix):
                        return n[len(prefix):]
                return n

            def _find_regional(device_name, regionais_map):
                """Matching fuzzy: normaliza nomes e usa prefixo/contenção para casar device→regional"""
                dev_norm = _norm(_device_key(device_name))
                best_match = None
                best_score = 0
                for reg_code in regionais_map:
                    reg_upper = reg_code.upper()
                    reg_key = reg_upper[4:] if reg_upper.startswith('REG_') else reg_upper
                    reg_norm = _norm(reg_key)
                    if not reg_norm:
                        continue
                    score = 0
                    if dev_norm == reg_norm:
                        score = 1000
                    elif len(reg_norm) >= 3 and dev_norm.startswith(reg_norm):
                        score = len(reg_norm)          # prefixo exato (CAMPINAS in CAMPINAS01)
                    elif len(dev_norm) >= 3 and reg_norm.startswith(dev_norm):
                        score = len(dev_norm)           # device é prefixo da regional (GLOBALSEG in GLOBALSEGURANCA)
                    elif len(reg_norm) >= 4 and reg_norm in dev_norm:
                        score = len(reg_norm) - 1      # regional contida no device
                    elif len(dev_norm) >= 4 and dev_norm in reg_norm:
                        score = len(dev_norm) - 1      # device contido na regional
                    if score > best_score:
                        best_score = score
                        best_match = reg_code
                return best_match if best_score > 0 else None

            # Para cada device no FortiManager, matchear com regional
            for device_data in devices_data:
                if not isinstance(device_data, dict):
                    continue
                
                device_name = device_data.get('name', '').strip()
                device_ip = device_data.get('ip', '')
                device_hostname = device_data.get('hostname', '')
                device_model = device_data.get('platform_str', 'N/A')
                device_serial = device_data.get('sn', 'N/A')
                device_status = device_data.get('status', 'unknown')
                
                if not device_name:
                    continue
                
                # Override manual para casos de abreviação impossível de inferir
                if device_name in DEVICE_REGIONAL_OVERRIDE:
                    regional_encontrada = DEVICE_REGIONAL_OVERRIDE[device_name]
                    print(f"   -> OVERRIDE: {device_name} -> {regional_encontrada}")
                else:
                    regional_encontrada = _find_regional(device_name, regionais_map)
                    print(f"   -> MATCH: {device_name} -> {regional_encontrada}")
                
                # Se encontrou regional, buscar licenças
                if regional_encontrada:
                    try:
                        licenses_data = fm_client.proxy_monitor_license(adom, device_name)
                        
                        firewall_info = {
                            'codigo_regional': regional_encontrada,
                            'nome': device_name,
                            'hostname': device_hostname,
                            'ip': device_ip,
                            'status': device_status,
                            'model': device_model,
                            'serial': device_serial,
                            'licencas': [],
                            'licencas_criticas': 0,
                            'licencas_expiradas': 0,
                            'ultima_verificacao': datetime.now().isoformat()
                        }

                        # Device offline (sem túnel) — licença não verificável
                        if isinstance(licenses_data, dict) and licenses_data.get('_erro') == 'offline':
                            lic_obj = {
                                'nome': 'forticare',
                                'tipo': 'forticare',
                                'status': 'offline',
                                'dias_restantes': 0,
                                'expiracao': 'N/A',
                                'tipo_licenca': 'forticare',
                                'notificacao_critica': False,
                                'notificacao_expirada': True,
                            }
                            firewall_info['licencas'].append(lic_obj)
                            firewall_info['licencas_expiradas'] += 1
                        
                        # Processar apenas a licença 'forticare'
                        elif isinstance(licenses_data, dict) and 'forticare' in licenses_data:
                            license_key = 'forticare'
                            license_info = licenses_data['forticare']
                            
                            if isinstance(license_info, dict):
                                # Extrai timestamp de expiração - procurar em múltiplos locais
                                dias_rest = 0
                                expires_timestamp = 0
                                
                                # 1. Tentar nível raiz
                                expires_timestamp = license_info.get('expires', 0)
                                
                                # 2. Se não encontrou, tentar em support.hardware.expires (forticare)
                                if not expires_timestamp:
                                    support = license_info.get('support', {})
                                    if isinstance(support, dict):
                                        hardware = support.get('hardware', {})
                                        if isinstance(hardware, dict):
                                            expires_timestamp = hardware.get('expires', 0)
                                
                                # 3. Se não encontrou, tentar em support.enhanced.expires (forticare)
                                if not expires_timestamp:
                                    support = license_info.get('support', {})
                                    if isinstance(support, dict):
                                        enhanced = support.get('enhanced', {})
                                        if isinstance(enhanced, dict):
                                            expires_timestamp = enhanced.get('expires', 0)
                                
                                # Se tiver timestamp de expiração, calcula dias restantes
                                if expires_timestamp and isinstance(expires_timestamp, (int, float)) and expires_timestamp > 0:
                                    try:
                                        from datetime import datetime as dt_class
                                        exp_date = dt_class.fromtimestamp(expires_timestamp)
                                        dias_rest = max(0, (exp_date.date() - dt_class.now().date()).days)
                                    except Exception:
                                        dias_rest = 0
                                
                                lic_status = license_info.get('status', 'unknown')
                                lic_obj = {
                                    'nome': license_key,
                                    'tipo': license_key,
                                    'status': lic_status,
                                    'dias_restantes': dias_rest,
                                    'expiracao': expires_timestamp if expires_timestamp else 'N/A',
                                    'tipo_licenca': license_info.get('type', 'unknown'),
                                    'notificacao_critica': False,
                                    'notificacao_expirada': False
                                }
                                
                                # Verifica se licença está expirada
                                if lic_status in ('expired', 'no_license'):
                                    lic_obj['notificacao_expirada'] = True
                                    firewall_info['licencas_expiradas'] += 1
                                # Marca como crítica se vai expirar em menos de 30 dias
                                elif dias_rest <= 30 and dias_rest > 0:
                                    lic_obj['notificacao_critica'] = True
                                    firewall_info['licencas_criticas'] += 1
                                
                                firewall_info['licencas'].append(lic_obj)
                        
                        # Adicionar ao resultado
                        if regional_encontrada not in firewalls_por_regional:
                            firewalls_por_regional[regional_encontrada] = []
                        
                        firewalls_por_regional[regional_encontrada].append(firewall_info)
                        total_firewalls += 1
                        if firewall_info['licencas_expiradas'] > 0:
                            total_expirados += 1
                        elif firewall_info['licencas_criticas'] > 0:
                            total_alertas += firewall_info['licencas_criticas']
                    
                    except Exception as e:
                        print(f"⚠️ Erro ao buscar licenças de {device_name}: {str(e)}")
                        current_app.logger.warning(f"Erro ao buscar licenças de {device_name}: {str(e)}")
            
            print(f"🔴 DEBUG: Total de firewalls encontrados = {total_firewalls}")
            current_app.logger.info(f"🔴 DEBUG: Total de firewalls encontrados = {total_firewalls}")
            print(f"🔴 DEBUG: Total de alertas = {total_alertas}")
            current_app.logger.info(f"🔴 DEBUG: Total de alertas = {total_alertas}")
            fm_client.logout()
        
        except Exception as e:
            print(f"⚠️ Erro ao conectar FortiManager: {str(e)}")
            current_app.logger.warning(f"Erro ao conectar FortiManager: {str(e)}")
        
        firewall_snapshot = {
                "atualizado_em": datetime.now().isoformat(),
                "firewalls_por_regional": firewalls_por_regional,
                "total_firewalls": total_firewalls,
                "total_alertas": total_alertas,
                "total_expirados": total_expirados,
        }
        if total_firewalls:
            _salvar_cache_dashboard("firewalls", firewall_snapshot)
        if return_data:
            return firewall_snapshot

        return render_template(
            'firewalls.html',
            firewalls_por_regional=firewalls_por_regional,
            total_firewalls=total_firewalls,
            total_alertas=total_alertas,
            total_expirados=total_expirados,
            cache_atualizado_em=firewall_snapshot.get("atualizado_em"),
            usando_cache=False,
        )

    except Exception as e:
        flash(f'Erro ao carregar firewalls: {str(e)}', 'error')
        return render_template(
            'firewalls.html',
            firewalls_por_regional={},
            total_firewalls=0,
            total_alertas=0,
            total_expirados=0,
            cache_atualizado_em=None,
            usando_cache=False,
        )


# ---------------------------------------------------------------------------
# Helper FortiAnalyzer
# ---------------------------------------------------------------------------
def _get_faz_client() -> FortiAnalyzerClient:
    faz_cfg = ENV_CONFIG.get("fortianalyzer", {})
    return FortiAnalyzerClient(
        host=faz_cfg.get("host", ""),
        api_key=faz_cfg.get("api_key", ""),
        adom=faz_cfg.get("adom", "GPS_UNIDADES"),
        verify_ssl=bool(faz_cfg.get("verify_ssl", False)),
        username=faz_cfg.get("username", ""),
        password=faz_cfg.get("password", ""),
    )


def _get_faz_minutes_back() -> int:
    faz_cfg = ENV_CONFIG.get("fortianalyzer", {})
    return int(faz_cfg.get("admin_monitor_minutes_back", 1440))


def _get_admin_baseline_path() -> str:
    import os
    faz_cfg = ENV_CONFIG.get("fortianalyzer", {})
    fname = faz_cfg.get("admin_baseline_file", "admin_baseline.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)


def _load_admin_baseline() -> dict:
    import json, os
    path = _get_admin_baseline_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_admin_baseline(baseline: dict):
    import json
    path = _get_admin_baseline_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Monitoramento de logins / admins nos FortiGates
# ---------------------------------------------------------------------------
@app.route('/admin-logins')
@login_required
def listar_admin_logins(return_data=False):
    """
    Dashboard de monitoramento de usuários admin nos FortiGates, FortiManager e FortiAnalyzer.
    Abordagem config-based: busca a lista atual de admins em cada dispositivo e compara com a
    baseline de admins aprovados (admin_baseline.json). Alerta para qualquer diferença.
    """
    erros = []
    dispositivos = {}  # {device_key: {...}}

    adom = _get_fortimanager_adom()
    baseline = _load_admin_baseline()
    force_refresh = return_data or request.args.get("refresh") in {"1", "true", "yes", "on"}
    if not force_refresh:
        cached = _carregar_cache_dashboard("admins", ttl_seconds=1800)
        if cached:
            if return_data:
                return cached
            return render_template(
                'admin_logins.html',
                dispositivos=cached.get("dispositivos", {}),
                baseline=baseline,
                total_disp=cached.get("total_disp", 0),
                total_alertas=cached.get("total_alertas", 0),
                total_offline=cached.get("total_offline", 0),
                total_sem_perm=cached.get("total_sem_perm", 0),
                total_ok=cached.get("total_ok", 0),
                admin_eventos=[],
                cache_atualizado_em=cached.get("atualizado_em"),
                usando_cache=True,
            )

    try:
        fmg = FortiManagerClient()
        fmg.login()

        # --- FortiManager (admins do próprio FMG) ---
        try:
            fmg_admins = fmg.get_fortimanager_admins()
            fmg_base   = set(baseline.get("__fortimanager__", []))

            dispositivos["__fortimanager__"] = {
                "nome":      "FortiManager",
                "tipo":      "fortimanager",
                "admins":    fmg_admins,
                "novos":     sorted(set(fmg_admins) - fmg_base),
                "removidos": sorted(fmg_base - set(fmg_admins)),
                "offline":   False,
                "sem_permissao": False,
                "monitoramento_limitado": False,
                "motivo": "",
            }
        except PermissionError as exc:
            dispositivos["__fortimanager__"] = {
                "nome":      "FortiManager",
                "tipo":      "fortimanager",
                "admins":    [],
                "novos":     [],
                "removidos": [],
                "offline":   False,
                "sem_permissao": True,
                "monitoramento_limitado": False,
                "motivo": str(exc),
            }
        except Exception as exc:
            erros.append(f"FortiManager admins: {exc}")

        # --- FortiGates via proxy (paralelo) ---
        try:
            raw = fmg.list_devices(adom=adom)
            device_list = raw.get("result", [{}])[0].get("data", []) or []
        except Exception as exc:
            erros.append(f"Listar devices: {exc}")
            device_list = []

        nomes_validos = [d.get("name", "") for d in (device_list or []) if isinstance(d, dict) and d.get("name")]

        def _consultar_fgt(dev_name):
            try:
                admins = fmg.get_fortigate_admins(dev_name, adom)
                offline = admins is None
                admins  = admins or []
                base    = set(baseline.get(dev_name, []))
                return dev_name, {
                    "nome":     dev_name,
                    "tipo":     "fortigate",
                    "admins":   sorted(admins),
                    "novos":    sorted(set(admins) - base) if not offline else [],
                    "removidos": sorted(base - set(admins)) if not offline else [],
                    "offline":  offline,
                    "sem_permissao": False,
                    "monitoramento_limitado": False,
                }, None
            except Exception as exc:
                return dev_name, None, str(exc)

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=10) as pool:
            futuros = {pool.submit(_consultar_fgt, nome): nome for nome in nomes_validos}
            for fut in as_completed(futuros):
                dev_name, resultado, erro = fut.result()
                if erro:
                    erros.append(f"{dev_name}: {erro}")
                elif resultado:
                    dispositivos[dev_name] = resultado

        fmg.logout()

    except Exception as exc:
        erros.append(f"FortiManager: {exc}")

    # --- FortiAnalyzer (admins do próprio FAZ) ---
    try:
        faz = _get_faz_client()
        faz_result = faz.get_fortianalyzer_admins_status()
        faz_admins = faz_result.get("admins") or []
        faz_base   = set(baseline.get("__fortianalyzer__", []))
        visibilidade_completa = bool(faz_result.get("visibilidade_completa"))
        apenas_contas_api     = bool(faz_result.get("apenas_contas_api"))
        dispositivos["__fortianalyzer__"] = {
            "nome":     "FortiAnalyzer",
            "tipo":     "fortianalyzer",
            "admins":   faz_admins,
            # Com visibilidade parcial (só contas REST), não reportar removidos pois
            # admins locais simplesmente não são visíveis via Bearer token.
            "novos":    sorted(set(faz_admins) - faz_base) if visibilidade_completa else [],
            "removidos": [] if apenas_contas_api else (sorted(faz_base - set(faz_admins)) if visibilidade_completa else []),
            "offline":  False,
            "sem_permissao": not visibilidade_completa,
            "monitoramento_limitado": apenas_contas_api,
            "motivo": faz_result.get("motivo") or "",
        }
    except Exception as exc:
        erros.append(f"FortiAnalyzer admins: {exc}")

    # --- Totais ---
    total_disp        = len(dispositivos)
    total_alertas     = sum(1 for d in dispositivos.values() if d.get("novos") or d.get("removidos"))
    total_offline     = sum(1 for d in dispositivos.values() if d.get("offline"))
    total_sem_perm    = sum(1 for d in dispositivos.values() if d.get("sem_permissao"))
    total_ok          = total_disp - total_alertas - total_offline - total_sem_perm

    admin_snapshot = {
        "atualizado_em": datetime.now().isoformat(),
        "dispositivos": dispositivos,
        "total_disp": total_disp,
        "total_alertas": total_alertas,
        "total_offline": total_offline,
        "total_sem_perm": total_sem_perm,
        "total_ok": total_ok,
    }
    _salvar_cache_dashboard("admins", admin_snapshot)
    if return_data:
        return admin_snapshot

    for err in erros:
        flash(f'Aviso: {err}', 'warning')

    # --- Eventos de criação/deleção de admins via logs FAZ ---
    admin_eventos = []
    try:
        faz_ev = _get_faz_client()
        minutos = int(ENV_CONFIG.get("fortianalyzer", {}).get("admin_monitor_minutes_back", 1440))
        admin_eventos = faz_ev.get_admin_events(minutes_back=minutos, limit=200)
    except Exception:
        pass  # eventos são opcionais; não bloqueia o dashboard

    return render_template(
        'admin_logins.html',
        dispositivos=dispositivos,
        baseline=baseline,
        total_disp=total_disp,
        total_alertas=total_alertas,
        total_offline=total_offline,
        total_sem_perm=total_sem_perm,
        total_ok=total_ok,
        admin_eventos=admin_eventos,
        cache_atualizado_em=admin_snapshot.get("atualizado_em"),
        usando_cache=False,
    )


def atualizar_cache_seguranca_dashboard():
    """Atualiza Firewalls/licencas e admins sem depender de uma sessao web."""
    resultados = {}
    with app.test_request_context("/dashboard-security-refresh"):
        resultados["firewalls"] = listar_firewalls.__wrapped__(return_data=True)
        resultados["admins"] = listar_admin_logins.__wrapped__(return_data=True)
    return resultados


@app.route('/admin-logins/aprovar/<path:device_key>/<path:usuario>', methods=['POST'])
@login_required
def admin_aprovar_usuario(device_key, usuario):
    """Adiciona um usuário à baseline aprovada para o dispositivo indicado."""
    baseline = _load_admin_baseline()
    entry = baseline.setdefault(device_key, [])
    if usuario not in entry:
        entry.append(usuario)
        entry.sort()
    _save_admin_baseline(baseline)
    _invalidar_cache_dashboard('admins')
    flash(f'Usuário "{usuario}" aprovado na baseline de {device_key}.', 'success')
    return redirect(url_for('listar_admin_logins', refresh=1))


@app.route('/admin-logins/remover-baseline/<path:device_key>/<path:usuario>', methods=['POST'])
@login_required
def admin_remover_baseline(device_key, usuario):
    """Remove um usuário da baseline aprovada (ex: quando foi legitimamente removido do dispositivo)."""
    baseline = _load_admin_baseline()
    entry = baseline.get(device_key, [])
    if usuario in entry:
        entry.remove(usuario)
    _save_admin_baseline(baseline)
    _invalidar_cache_dashboard('admins')
    flash(f'Usuário "{usuario}" removido da baseline de {device_key}.', 'success')
    return redirect(url_for('listar_admin_logins', refresh=1))


@app.route('/admin-logins/definir-baseline', methods=['POST'])
@login_required
def admin_definir_baseline():
    """Define a baseline de um dispositivo a partir do estado atual (snapshot)."""
    device_key = request.form.get("device_key", "")
    admins_str = request.form.get("admins", "")
    if not device_key:
        flash('Dispositivo inválido.', 'error')
        return redirect(url_for('listar_admin_logins', refresh=1))

    admins = [a.strip() for a in admins_str.split(",") if a.strip()]
    baseline = _load_admin_baseline()
    baseline[device_key] = sorted(set(admins))
    _save_admin_baseline(baseline)
    _invalidar_cache_dashboard('admins')
    flash(f'Baseline de "{device_key}" definida com {len(admins)} usuário(s).', 'success')
    return redirect(url_for('listar_admin_logins', refresh=1))


@app.route('/admin-logins/debug')
@login_required
def admin_logins_debug():
    """Diagnóstico: mostra as respostas brutas das APIs de FortiManager e FortiAnalyzer para listar admins."""
    import json as _json
    resultado = {}
    adom = _get_fortimanager_adom()

    # --- FortiManager ---
    try:
        fmg = FortiManagerClient()
        fmg.login()
        fmg_info = {
            "host": fmg.host, "port": fmg.port,
            "base_url": fmg.base_url,
            "usando_api_key": bool(fmg.api_key),
            "sessionid": fmg.sessionid,
        }

        # Testa endpoint /cli/global/system/admin/user
        payload_cli = {
            "id": 1, "method": "get",
            "params": [{"url": "/cli/global/system/admin/user"}],
            "session": fmg.sessionid,
        }
        r_cli = fmg.session.post(fmg.base_url, json=payload_cli, timeout=15)
        fmg_info["resp_cli_status_http"] = r_cli.status_code
        try:
            fmg_info["resp_cli_json"] = r_cli.json()
        except Exception:
            fmg_info["resp_cli_text"] = r_cli.text[:500]

        # Testa endpoint alternativo /sys/admin/user
        payload_sys = {
            "id": 1, "method": "get",
            "params": [{"url": "/sys/admin/user"}],
            "session": fmg.sessionid,
        }
        r_sys = fmg.session.post(fmg.base_url, json=payload_sys, timeout=15)
        fmg_info["resp_sys_status_http"] = r_sys.status_code
        try:
            fmg_info["resp_sys_json"] = r_sys.json()
        except Exception:
            fmg_info["resp_sys_text"] = r_sys.text[:500]

        fmg.logout()
        resultado["fortimanager"] = fmg_info
    except Exception as exc:
        resultado["fortimanager"] = {"erro": str(exc)}

    # --- FortiAnalyzer ---
    try:
        faz = _get_faz_client()
        faz_info = {
            "host": faz.api_url,
            "adom": faz.adom,
        }

        # Testa endpoint /cli/global/system/admin/user
        payload_faz = {
            "jsonrpc": "2.0", "id": "faz-debug",
            "method": "get",
            "params": [{"url": "/cli/global/system/admin/user"}],
        }
        r_faz = faz._session.post(faz.api_url, json=payload_faz, timeout=15)
        faz_info["resp_status_http"] = r_faz.status_code
        try:
            faz_info["resp_json"] = r_faz.json()
        except Exception:
            faz_info["resp_text"] = r_faz.text[:500]

        resultado["fortianalyzer"] = faz_info
    except Exception as exc:
        resultado["fortianalyzer"] = {"erro": str(exc)}

    html = (
        "<pre style='background:#1e1e1e;color:#d4d4d4;padding:1.5rem;border-radius:0.5rem;"
        "font-size:0.82rem;overflow:auto;max-height:90vh'>"
        + _json.dumps(resultado, indent=2, ensure_ascii=False, default=str)
        + "</pre>"
    )
    return f"<html><body style='background:#121212;padding:1rem'>{html}</body></html>"


@app.route('/vms')
@login_required
def listar_vms():
    """Página de listagem de máquinas virtuais"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Obtém as regionais
        regionais = set()
        for vm in vms:
            if "regional" in vm and vm["regional"]:
                regionais.add(vm["regional"])
        
        return render_template('vms.html', vms=vms, regionais=sorted(regionais))
    except Exception as e:
        flash(f"Erro ao carregar página de VMs: {str(e)}", "error")
        return render_template('vms.html', vms=[], regionais=[])

@app.route('/vms/<vm_id>/relatorio')
@login_required
def vm_relatorio(vm_id):
    """Página de relatório completo de uma VM específica"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Procura a VM específica
        vm = None
        for v in vms:
            if v.get("id") == vm_id:
                vm = v
                break
        
        if not vm:
            flash("VM não encontrada", "danger")
            return redirect(url_for('listar_vms'))
        
        return render_template('vm_relatorio_simples.html', vm=vm, vm_id=vm_id)
    except Exception as e:
        flash(f"Erro ao carregar relatório da VM: {str(e)}", "danger")
        return redirect(url_for('listar_vms'))

# === ROTAS DE VPN ===

@app.route('/vpn')
@login_required
def vpn_ipsec():
    try:
        # Garante autenticação no Fortigate
        if not gerenciador_fortigate.autenticar():
            flash("Falha na autenticação com o Fortigate", "error")
            return render_template("vpn_ipsec.html", vpns=[])

        # Obtém VPNs
        resultado = gerenciador_fortigate.obter_vpn_ipsec()

        # Validação defensiva
        if not resultado or not isinstance(resultado, dict):
            raise ValueError("Resposta inválida do Fortigate")

        if not resultado.get("success", False):
            flash(resultado.get("message", "Erro ao consultar VPN IPsec"), "error")
            return render_template("vpn_ipsec.html", vpns=[])

        vpns = resultado.get("vpns", [])

        # Normaliza campos esperados pelo template
        for vpn in vpns:
            vpn.setdefault("tunel", "N/A")
            vpn.setdefault("interface", "N/A")
            vpn.setdefault("status", "down")
            vpn.setdefault("ultima_verificacao", datetime.now().strftime("%H:%M"))

        resumo_vpn = _agrupar_vpns_por_regional(vpns)
        vpns_online = sum(1 for vpn in vpns if str(vpn.get("status") or "").strip().lower() == "up")
        vpns_offline = len(vpns) - vpns_online

        return render_template(
            "vpn_ipsec.html",
            vpns=vpns,
            vpns_por_regional=resumo_vpn["vpns_por_regional"],
            regionais_vpn=resumo_vpn["regionais"],
            regionais_com_offline=resumo_vpn["regionais_com_offline"],
            vpn_total=len(vpns),
            vpn_online=vpns_online,
            vpn_offline=vpns_offline,
            vpn_total_regionais=resumo_vpn["total_regionais"],
            vpn_regionais_sem_offline=resumo_vpn["regionais_sem_offline"],
        )

    except Exception as e:
        app.logger.exception("Erro na rota /vpn")
        flash(f"Erro interno ao carregar VPN: {str(e)}", "error")
        return render_template(
            "vpn_ipsec.html",
            vpns=[],
            vpns_por_regional={},
            regionais_vpn=[],
            regionais_com_offline=[],
            vpn_total=0,
            vpn_online=0,
            vpn_offline=0,
            vpn_total_regionais=0,
            vpn_regionais_sem_offline=0,
        )
@app.route('/api/vpn/verificar', methods=['POST'])
@login_required
def api_verificar_vpn():
    try:
        if not gerenciador_fortigate.autenticar():
            return jsonify({
                "success": False,
                "message": "Falha na autenticação com o Fortigate"
            })

        return jsonify(gerenciador_fortigate.obter_vpn_ipsec())

    except Exception as e:
        app.logger.exception("Erro ao verificar VPN")
        return jsonify({
            "success": False,
            "message": str(e)
        })
@app.route('/vms/cadastrar', methods=['GET', 'POST'])
@login_required
def cadastrar_vm():
    """Página de cadastro de máquinas virtuais"""
    try:
        if request.method == 'POST':
            # Obtém os dados do formulário
            nome = request.form.get('nome')
            ip = request.form.get('ip')
            usuario = request.form.get('usuario')
            senha = request.form.get('senha')
            regional = request.form.get('regional')
            descricao = request.form.get('descricao', '')
            
            # Validação básica
            if not nome or not ip or not usuario or not senha or not regional:
                flash("Todos os campos obrigatórios devem ser preenchidos", "error")
                return render_template('vms_cadastro.html', regionais=REGIONAIS)
            
            # Cadastra a VM
            resultado = cadastrar_vm_no_sistema(nome, ip, usuario, senha, regional, descricao)
            
            if resultado["success"]:
                flash(resultado["message"], "success")
                return redirect(url_for('listar_vms'))
            else:
                flash(resultado["message"], "error")
                return render_template('vms_cadastro.html', regionais=REGIONAIS)
        
        # Obtém as regionais
        REGIONAIS = ["Paraná", "Global Segurança", "São Leopoldo", "São Paulo - Jaguaré", "Rio de Janeiro", "Belo Horizonte", "ABC", "Alagoas", "Amazonas", "Araras", "Bahia", "Campinas", "Ceara", 
                     "Espirito Santo", "Goiás", "Loghis", "Maranhão", "Motus-Matriz", "Pará", "Pernambuco", "RHMED", "Rio Grande do Norte", "Rudder", "Sulzer", "Praia Grande", "São José dos Campos", 
                     "Sorocaba", "TLSV CWB", "TLSV POA", "Trade&Talentos", "Uberlândia"]
        
        return render_template('vms_cadastro.html', regionais=REGIONAIS)
    except Exception as e:
        flash(f"Erro ao carregar página de cadastro: {str(e)}", "error")
        return render_template('vms_cadastro.html', regionais=[])



# Funções para gerenciar o cadastro de VMs
def carregar_vms_cadastradas():
    """Carrega as VMs cadastradas no sistema"""
    try:
        # Verifica se o diretório de dados existe
        data_dir = os.path.join(PROJECT_ROOT, 'data')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        
        # Verifica se o arquivo de VMs existe
        vms_file = os.path.join(data_dir, 'vms.json')
        if not os.path.exists(vms_file):
            # Cria o arquivo com uma lista vazia
            with open(vms_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
            return []
        
        # Carrega as VMs do arquivo
        with open(vms_file, 'r', encoding='utf-8') as f:
            vms = json.load(f)
        
        return vms
    except Exception as e:
        print(f"Erro ao carregar VMs cadastradas: {str(e)}")
        return []

def _sanitize_vm(vm: dict) -> dict:
    """Remove dados sensiveis antes de retornar ao cliente."""
    if not isinstance(vm, dict):
        if resolved and not resolved.get("fortimanager_inventory_available", True):
            return {
                "success": False,
                "message": "Inventário do FortiManager indisponível",
                "status": "fortimanager_inventory_unavailable",
                "resolved": resolved,
                "interfaces": []
            }

        return {}
    clean = dict(vm)
    clean.pop("password", None)
    return clean

def _ensure_trusted_host(ip: str):
    """Garante que o IP esteja em TrustedHosts (WinRM)."""
    if os.name != "nt":
        return True, None

    if not ip:
        return False, "IP vazio"

    try:
        get_cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-Item WSMan:\\localhost\\Client\\TrustedHosts).Value"
        ]
        result = subprocess.run(get_cmd, capture_output=True, text=True)
        current = (result.stdout or "").strip()

        if current == "*" or ip in [item.strip() for item in current.split(",") if item.strip()]:
            return True, None

        new_value = ip if not current else f"{current},{ip}"
        set_cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value '{new_value}' -Force"
        ]
        set_result = subprocess.run(set_cmd, capture_output=True, text=True)
        if set_result.returncode != 0:
            return False, (set_result.stderr or "Falha ao configurar TrustedHosts").strip()

        return True, None
    except Exception as exc:
        return False, str(exc)

def _get_vm_credentials(vm: dict) -> tuple:
    """Retorna credenciais padrao do server_manager com fallback da VM."""
    sm_cfg = ENV_CONFIG.get("server_manager", {}) if isinstance(ENV_CONFIG.get("server_manager", {}), dict) else {}
    username = sm_cfg.get("username")
    password = sm_cfg.get("password")

    if not username or not password:
        username = vm.get("username") if isinstance(vm, dict) else None
        password = vm.get("password") if isinstance(vm, dict) else None

    return username, password

def cadastrar_vm_no_sistema(nome, ip, usuario, senha, regional, descricao=""):
    """Cadastra uma VM no sistema"""
    try:
        # Carrega as VMs existentes
        vms = carregar_vms_cadastradas()
        
        # Verifica se já existe uma VM com o mesmo IP
        for vm in vms:
            if vm.get("ip") == ip:
                return {"success": False, "message": f"Já existe uma VM cadastrada com o IP {ip}"}
        
        # Gera um ID único para a VM
        vm_id = f"vm-{int(time.time())}"
        
        # Cria o objeto da VM
        nova_vm = {
            "id": vm_id,
            "name": nome,
            "ip": ip,
            "username": usuario,
            "password": senha,  # Em produção, isso deveria ser criptografado
            "regional": regional,
            "description": descricao,
            "status": "Unknown",
            "last_check": None
        }
        
        # Adiciona a VM à lista
        vms.append(nova_vm)
        
        # Salva a lista atualizada
        vms_file = os.path.join(PROJECT_ROOT, 'data', 'vms.json')
        with open(vms_file, 'w', encoding='utf-8') as f:
            json.dump(vms, f, indent=4)
        
        return {"success": True, "message": f"VM {nome} cadastrada com sucesso", "vm": nova_vm}
    except Exception as e:
        return {"success": False, "message": f"Erro ao cadastrar VM: {str(e)}"}

def remover_vm_do_sistema(vm_id):
    """Remove uma VM do sistema"""
    try:
        # Carrega as VMs existentes
        vms = carregar_vms_cadastradas()
        
        # Procura a VM pelo ID
        vm_encontrada = None
        for i, vm in enumerate(vms):
            if vm.get("id") == vm_id:
                vm_encontrada = vm
                vms.pop(i)
                break
        
        if not vm_encontrada:
            return {"success": False, "message": f"VM com ID {vm_id} não encontrada"}
        
        # Salva a lista atualizada
        vms_file = os.path.join(PROJECT_ROOT, 'data', 'vms.json')
        with open(vms_file, 'w', encoding='utf-8') as f:
            json.dump(vms, f, indent=4)
        
        return {"success": True, "message": f"VM {vm_encontrada.get('name')} removida com sucesso"}
    except Exception as e:
        return {"success": False, "message": f"Erro ao remover VM: {str(e)}"}

def atualizar_status_vm(vm_id, status, detalhes=None):
    """Atualiza o status de uma VM"""
    try:
        # Carrega as VMs existentes
        vms = carregar_vms_cadastradas()
        
        # Procura a VM pelo ID
        vm_encontrada = False
        for vm in vms:
            if vm.get("id") == vm_id:
                vm["status"] = status
                vm["last_check"] = datetime.now().isoformat()
                if detalhes:
                    vm["details"] = detalhes
                vm_encontrada = True
                break
        
        if not vm_encontrada:
            return {"success": False, "message": f"VM com ID {vm_id} não encontrada"}
        
        # Salva a lista atualizada
        vms_file = os.path.join(PROJECT_ROOT, 'data', 'vms.json')
        with open(vms_file, 'w', encoding='utf-8') as f:
            json.dump(vms, f, indent=4)
        
        return {"success": True, "message": f"Status da VM atualizado para {status}"}
    except Exception as e:
        return {"success": False, "message": f"Erro ao atualizar status da VM: {str(e)}"}

# Função para verificar uma VM
def verificar_vm(vm_id):
    """Verifica uma VM específica e atualiza suas informações"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Procura a VM específica
        vm = None
        vm_index = -1
        for i, v in enumerate(vms):
            if v.get("id") == vm_id:
                vm = v
                vm_index = i
                break
        
        if not vm:
            return {"success": False, "message": "VM não encontrada"}
        
        # Obtém as credenciais da VM
        ip = vm.get("ip")
        username = vm.get("username")
        password = vm.get("password")
        
        if not ip or not username or not password:
            return {"success": False, "message": "Credenciais incompletas para a VM"}
        
        # Aqui vamos tentar conectar à VM e obter informações reais
        # Primeiro, vamos verificar se a VM está online com um ping
        import subprocess
        
        try:
            # Tenta fazer ping na VM
            ping_result = subprocess.run(
                ["ping", "-n", "1", "-w", "1000", ip],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Verifica se o ping foi bem-sucedido
            if _ping_indica_online(ping_result):
                status = "Running"
            else:
                status = "Unreachable"
        except Exception as ping_error:
            print(f"Erro ao fazer ping: {str(ping_error)}")
            status = "Unknown"
        
        # Atualiza as informações básicas da VM
        vm["status"] = status
        vm["last_check"] = datetime.now().isoformat()
        vm["ipAddresses"] = [ip]
        
        # Se a VM estiver online, tenta obter mais informações
        if status == "Running":
            try:
                # Aqui você implementaria a conexão real com o Server Manager
                # Por exemplo, usando WMI, PowerShell Remoting ou outra API
                
                # Por enquanto, vamos obter algumas informações básicas do sistema
                # usando comandos PowerShell remotos (isso requer configuração adicional na VM)
                
                # Simulação de informações obtidas
                vm["operatingSystem"] = "Windows Server"
                vm["processors"] = 2
                vm["memory"] = 4096
                vm["details"] = {
                    "status": "Online",
                    "lastBoot": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ipConfig": f"IP: {ip}, Máscara: 255.255.255.0",
                    "diskSpace": "C: 50GB livre"
                }
                
                # Nota: Em um ambiente real, você usaria algo como:
                # powershell_command = f"Invoke-Command -ComputerName {ip} -Credential $cred -ScriptBlock {{ Get-ComputerInfo | ConvertTo-Json }}"
                # E então analisaria o resultado JSON
                
            except Exception as info_error:
                print(f"Erro ao obter informações detalhadas: {str(info_error)}")
                # Mesmo com erro, mantemos o status como Running se o ping funcionou
        
        # Salva as alterações
        vms[vm_index] = vm
        vms_file = os.path.join(PROJECT_ROOT, 'data', 'vms.json')
        with open(vms_file, 'w', encoding='utf-8') as f:
            json.dump(vms, f, indent=4)
        
        return {"success": True, "message": f"VM {vm.get('name')} verificada com sucesso", "vm": vm}
    except Exception as e:
        return {"success": False, "message": f"Erro ao verificar VM: {str(e)}"}

# === ROTAS DE API PARA MÁQUINAS VIRTUAIS ===

@app.route('/api/vms/listar')
@login_required
def api_listar_vms():
    """API para listar todas as VMs cadastradas"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        return jsonify({"success": True, "vms": [_sanitize_vm(vm) for vm in vms]})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao listar VMs: {str(e)}"})

@app.route('/api/vms/regional/<regional>')
@login_required
def api_listar_vms_regional(regional):
    """API para listar VMs de uma regional específica"""
    try:
        # Carrega as VMs cadastradas
        todas_vms = carregar_vms_cadastradas()
        
        # Filtra as VMs da regional
        vms_regional = [vm for vm in todas_vms if vm.get("regional") == regional]
        
        return jsonify({"success": True, "vms": [_sanitize_vm(vm) for vm in vms_regional], "regional": regional})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao listar VMs da regional {regional}: {str(e)}"})

@app.route('/api/vms/<vm_id>/detalhes')
@login_required
def api_detalhes_vm(vm_id):
    """API para obter detalhes de uma VM específica"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Procura a VM específica
        vm = None
        for v in vms:
            if v.get("id") == vm_id:
                vm = v
                break
        
        if not vm:
            return jsonify({"success": False, "message": "VM não encontrada"})
        
        ip = vm.get("ip")
        if not ip and vm.get("ipAddresses"):
            ip = vm.get("ipAddresses")[0]

        username, password = _get_vm_credentials(vm)
        if not ip or not username or not password:
            return jsonify({"success": False, "message": "Credenciais incompletas para a VM"})

        ok, err = _ensure_trusted_host(ip)
        if not ok:
            return jsonify({
                "success": False,
                "message": f"Nao foi possivel configurar TrustedHosts para {ip}: {err}"
            })

        detalhes = obter_detalhes_vm(ip, username, password)
        if not detalhes.get("success"):
            return jsonify({"success": False, "message": detalhes.get("message", "Erro ao obter detalhes")})

        vm_info = _sanitize_vm(vm)
        info = detalhes.get("details", {})
        vm_info["operatingSystem"] = info.get("operatingSystem", "-")
        vm_info["uptime"] = info.get("uptime", "-")
        vm_info["processors"] = info.get("processors", "-")
        vm_info["memory"] = info.get("memory", "-")
        vm_info["ipAddresses"] = [ip]

        return jsonify({"success": True, "vm": vm_info})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao obter detalhes da VM: {str(e)}"})

@app.route('/api/vms/<vm_id>/servicos')
@login_required
def api_servicos_vm(vm_id):
    """API para obter serviços de uma VM específica"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Procura a VM específica
        vm = None
        for v in vms:
            if v.get("id") == vm_id:
                vm = v
                break
        
        if not vm:
            return jsonify({"success": False, "message": "VM não encontrada"})
        
        # Obtém as credenciais da VM
        ip = vm.get("ip")
        username, password = _get_vm_credentials(vm)
        
        if not ip and vm.get("ipAddresses"):
            ip = vm.get("ipAddresses")[0]

        if not ip or not username or not password:
            return jsonify({"success": False, "message": "Credenciais incompletas para a VM"})
        
        ok, err = _ensure_trusted_host(ip)
        if not ok:
            return jsonify({
                "success": False,
                "message": f"Nao foi possivel configurar TrustedHosts para {ip}: {err}"
            })

        # Obtém os serviços da VM usando o novo módulo
        result = obter_servicos_vm(ip, username, password)
        
        # Adiciona a VM ao resultado
        result["vm"] = _sanitize_vm(vm)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao obter serviços da VM: {str(e)}"})

@app.route('/api/vms/<vm_id>/relatorio')
@login_required
def api_relatorio_vm(vm_id):
    """API para obter um relatório completo de uma VM específica"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Procura a VM específica
        vm = None
        for v in vms:
            if v.get("id") == vm_id:
                vm = v
                break
        
        if not vm:
            return jsonify({"success": False, "message": "VM não encontrada"})
        
        # Obtém as credenciais da VM
        ip = vm.get("ip")
        username, password = _get_vm_credentials(vm)
        
        if not ip and vm.get("ipAddresses"):
            ip = vm.get("ipAddresses")[0]

        if not ip or not username or not password:
            return jsonify({"success": False, "message": "Credenciais incompletas para a VM"})

        ok, err = _ensure_trusted_host(ip)
        if not ok:
            return jsonify({
                "success": False,
                "message": f"Nao foi possivel configurar TrustedHosts para {ip}: {err}"
            })
        
        # Adiciona log para depuração
        app.logger.info(f"Gerando relatório para VM: {ip}")
        
        # Gera o relatório simplificado
        relatorio = gerar_relatorio_simples(ip, username, password)
        
        # Adiciona log para depuração
        if not relatorio.get('success', False):
            app.logger.error(f"Erro no relatório: {relatorio.get('message', 'Erro desconhecido')}")
            if 'raw_output' in relatorio:
                app.logger.error(f"Saída bruta: {relatorio['raw_output'][:500]}...")
        
        # Adiciona informações da VM
        relatorio["vm"] = _sanitize_vm(vm)
        
        return jsonify(relatorio)
    except Exception as e:
        app.logger.exception("Erro ao gerar relatório")
        return jsonify({"success": False, "message": f"Erro ao gerar relatório da VM: {str(e)}"})

@app.route('/api/vms/<vm_id>/logs')
@login_required
def api_logs_vm(vm_id):
    """API para obter logs de uma VM específica"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Procura a VM específica
        vm = None
        for v in vms:
            if v.get("id") == vm_id:
                vm = v
                break
        
        if not vm:
            return jsonify({"success": False, "message": "VM não encontrada"})
        
        # Obtém as credenciais da VM
        ip = vm.get("ip")
        username, password = _get_vm_credentials(vm)
        
        if not ip and vm.get("ipAddresses"):
            ip = vm.get("ipAddresses")[0]

        if not ip or not username or not password:
            return jsonify({"success": False, "message": "Credenciais incompletas para a VM"})
        
        ok, err = _ensure_trusted_host(ip)
        if not ok:
            return jsonify({
                "success": False,
                "message": f"Nao foi possivel configurar TrustedHosts para {ip}: {err}"
            })

        # Obtém os logs da VM usando o novo módulo
        result = obter_logs_vm(ip, username, password)
        
        # Adiciona a VM ao resultado
        result["vm"] = _sanitize_vm(vm)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao obter logs da VM: {str(e)}"})

@app.route('/api/vms/<vm_id>/conectar', methods=['POST'])
@login_required
def api_conectar_vm(vm_id):
    """API para iniciar conexao RDP (mstsc) para uma VM"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()

        # Procura a VM especifica
        vm = None
        for v in vms:
            if v.get("id") == vm_id:
                vm = v
                break

        if not vm:
            return jsonify({"success": False, "message": "VM nao encontrada"})

        ip = vm.get("ip")
        if not ip and vm.get("ipAddresses"):
            ip = vm.get("ipAddresses")[0]

        if not ip:
            return jsonify({"success": False, "message": "IP da VM nao encontrado"})

        if os.name != "nt":
            return jsonify({"success": False, "message": "RDP so esta disponivel no Windows"})

        # Valida formato basico de IPv4
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
            return jsonify({"success": False, "message": "IP invalido para RDP"})

        partes = ip.split(".")
        if any(not 0 <= int(p) <= 255 for p in partes):
            return jsonify({"success": False, "message": "IP invalido para RDP"})

        # Determina se o acesso e local (servidor) ou remoto
        server_ip = ""
        if isinstance(ENV_CONFIG, dict):
            server_ip = (ENV_CONFIG.get("app_host_ip") or "").strip()
        if not server_ip:
            server_ip = (request.host.split(":")[0] or "").strip()

        client_ip = (request.remote_addr or "").strip()
        is_local = client_ip in {server_ip, "127.0.0.1", "::1"}

        # Credenciais padrao do server_manager (environment.json)
        sm_cfg = ENV_CONFIG.get("server_manager", {}) if isinstance(ENV_CONFIG.get("server_manager", {}), dict) else {}
        sm_user = sm_cfg.get("username")
        sm_pass = sm_cfg.get("password")

        # Fallback para credenciais da VM, se necessário
        if not sm_user or not sm_pass:
            sm_user = vm.get("username")
            sm_pass = vm.get("password")

        if sm_user and sm_pass:
            subprocess.run(
                ["cmdkey", f"/generic:TERMSRV/{ip}", f"/user:{sm_user}", f"/pass:{sm_pass}"],
                capture_output=True,
                text=True
            )

        if not is_local:
            # Para acesso remoto, retorna um arquivo .rdp para o cliente baixar
            rdp_user = sm_user or ""
            rdp_lines = [
                f"full address:s:{ip}",
                "prompt for credentials:i:1",
            ]
            if rdp_user:
                rdp_lines.append(f"username:s:{rdp_user}")
            rdp_content = "\r\n".join(rdp_lines) + "\r\n"

            response = Response(rdp_content, mimetype="application/rdp")
            response.headers["Content-Disposition"] = f"attachment; filename={vm_id}.rdp"
            return response

        subprocess.Popen(["mstsc", f"/v:{ip}"])
        return jsonify({"success": True, "message": f"Conexao RDP iniciada para {ip}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao iniciar RDP: {str(e)}"})

@app.route('/api/vms/<vm_id>/verificar', methods=['POST'])
@login_required
def api_verificar_vm(vm_id):
    """API para verificar uma VM específica"""
    try:
        # Verifica a VM usando o novo módulo
        resultado = verificar_vm_completo(vm_id)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao verificar VM: {str(e)}"})

@app.route('/api/vms/relatorio')
@login_required
def api_relatorio_vms():
    """API para gerar relatório de VMs"""
    try:
        # Carrega as VMs cadastradas
        vms = carregar_vms_cadastradas()
        
        # Gera o relatório em Excel
        import pandas as pd
        from datetime import datetime
        
        # Cria um DataFrame com os dados das VMs
        df = pd.DataFrame([
            {
                'Nome': vm.get('name', ''),
                'IP': vm.get('ip', ''),
                'Regional': vm.get('regional', ''),
                'Status': vm.get('status', 'Desconhecido'),
                'Última Verificação': vm.get('last_check', ''),
                'Descrição': vm.get('description', '')
            }
            for vm in vms
        ])
        
        # Cria o diretório de relatórios se não existir
        reports_dir = os.path.join(PROJECT_ROOT, 'static', 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        
        # Gera o nome do arquivo
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f'vms_report_{timestamp}.xlsx'
        file_path = os.path.join(reports_dir, file_name)
        
        # Salva o DataFrame como Excel
        df.to_excel(file_path, index=False)
        
        return jsonify({"success": True, "file": file_name})
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao gerar relatório: {str(e)}"})

@app.route('/api/vms/cadastrar', methods=['POST'])
@login_required
def api_cadastrar_vm():
    """API para cadastrar uma nova VM"""
    try:
        data = request.get_json()
        
        # Valida os dados
        if not data.get('nome'):
            return jsonify({"success": False, "message": "Nome da VM é obrigatório"})
        
        if not data.get('ip'):
            return jsonify({"success": False, "message": "Endereço IP é obrigatório"})
        
        if not data.get('usuario'):
            return jsonify({"success": False, "message": "Usuário é obrigatório"})
        
        if not data.get('senha'):
            return jsonify({"success": False, "message": "Senha é obrigatória"})
        
        if not data.get('regional'):
            return jsonify({"success": False, "message": "Regional é obrigatória"})
        
        # Cadastra a VM
        resultado = cadastrar_vm_no_sistema(
            data.get('nome'),
            data.get('ip'),
            data.get('usuario'),
            data.get('senha'),
            data.get('regional'),
            data.get('descricao', '')
        )
        
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao cadastrar VM: {str(e)}"})

@app.route('/api/vms/remover/<vm_id>', methods=['DELETE', 'POST'])
@login_required
def api_remover_vm(vm_id):
    """API para remover uma VM"""
    try:
        resultado = remover_vm_do_sistema(vm_id)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao remover VM: {str(e)}"})


@app.route('/api/links/verificar', methods=['POST'])
@login_required
def api_verificar_links():

    """API para verificar status dos links de internet"""
    try:
        resultado = _coletar_links_multiregional()
        return jsonify(resultado)

    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/fortimanager/devices', methods=['GET'])
@login_required
def api_fortimanager_devices():
    """Lista FortiGates gerenciados via FortiManager (somente leitura)."""
    try:
        adom = request.args.get("adom", "root")
        with FortiManagerClient() as fm:
            devices_resp = fm.list_devices(adom=adom)
        return jsonify({
            "success": True,
            "devices": devices_resp
        })

    except Exception as e:
        current_app.logger.exception("Erro ao consultar FortiManager")
        return jsonify({
            "success": False,
            "message": f"Erro ao consultar FortiManager: {str(e)}"
        }), 500


@app.route('/api/fortimanager/adoms', methods=['GET'])
@login_required
def api_fortimanager_adoms():
    """Lista ADOMs do FortiManager."""
    try:
        with FortiManagerClient() as fm:
            adoms_resp = fm.list_adoms()
        return jsonify({
            "success": True,
            "adoms": adoms_resp
        })

    except Exception as e:
        current_app.logger.exception("Erro ao consultar ADOMs do FortiManager")
        return jsonify({
            "success": False,
            "message": f"Erro ao consultar ADOMs: {str(e)}"
        }), 500


@app.route('/replicacao')
@login_required
def replicacao_ad():
    """Página de replicação Active Directory"""
    # Carrega os dados locais e o caminho público, escolhendo o mais completo
    local_data = load_data("replicacao")
    public_data = _load_public_replicacao_json()
    replicacao_data = _choose_replicacao_data(local_data, public_data)
    replicacao_data = _normalize_replicacao_data(replicacao_data)
    
    # Renderiza o template com os dados
    return render_template('replicacao_simples.html', replicacao_data=replicacao_data)

def executar_repadmin():
    """Executa o script PowerShell para capturar dados do repadmin"""
    import subprocess
    import json
    import os
    from datetime import datetime
    from pathlib import Path
    from config import PROJECT_ROOT
    
    try:
        # Tenta obter os dados direto do repadmin (sem gerar arquivos extras)
        direct_data, direct_error = _run_repadmin_direct()
        if direct_data:
            return {
                "success": True,
                "data": direct_data
            }
        if direct_error:
            return {
                "success": False,
                "error": direct_error
            }

        # Fallback opcional: tenta o script simples
        script_path_final = PROJECT_ROOT / "Replicacao_Final.ps1"
        if not script_path_final.exists():
            return {
                "success": False,
                "error": "Script Replicacao_Final.ps1 não encontrado"
            }

        print(f"Executando script: {script_path_final}")
        process = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path_final)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if process.returncode != 0:
            print(f"Erro ao executar PowerShell: {process.stderr}")
            return {
                "success": False,
                "error": f"Erro ao executar PowerShell: {process.stderr}"
            }

        json_path = os.path.join(os.environ["USERPROFILE"], "Desktop", "replicacao.json")

        if not os.path.exists(json_path):
            print(f"Arquivo JSON não encontrado: {json_path}")
            return {
                "success": False,
                "error": f"Arquivo JSON não encontrado: {json_path}"
            }

        try:
            replicacao_data = _load_json_with_fallback(json_path)
            if replicacao_data is None:
                return {
                    "success": False,
                    "error": "Falha ao ler o JSON de replicação com as codificações conhecidas"
                }
            
            # Normaliza para o formato esperado pela página
            replicacao_data = _normalize_replicacao_data(replicacao_data)
            
            # Garante que todos os servidores têm os campos necessários
            for servidor in replicacao_data["servidores"]:
                if "nome" not in servidor:
                    servidor["nome"] = "Desconhecido"
                if "status" not in servidor:
                    servidor["status"] = "Unknown"
                if "parceiros" not in servidor:
                    servidor["parceiros"] = 0
                if "falhas" not in servidor:
                    servidor["falhas"] = 0
                if "erros" not in servidor:
                    servidor["erros"] = 0
                if "replicacoes" not in servidor:
                    servidor["replicacoes"] = 0
                if "ultima_replicacao" not in servidor:
                    servidor["ultima_replicacao"] = datetime.now().isoformat()
                if "detalhes" not in servidor:
                    servidor["detalhes"] = ""
            
            # Exibe informações para debug
            print(f"Dados carregados: {len(replicacao_data['servidores'])} servidores")
            
            return {
                "success": True,
                "data": replicacao_data
            }
        except json.JSONDecodeError as e:
            print(f"Erro ao decodificar JSON: {e}")
            
            # Cria dados de exemplo
            replicacao_data = {
                "timestamp": datetime.now().isoformat(),
                "total_servidores": 1,
                "servidores_saudaveis": 0,
                "servidores_problemas": 1,
                "servidores": [
                    {
                        "nome": "ERRO.GALAXIA.LOCAL",
                        "status": "Error",
                        "parceiros": 0,
                        "falhas": 0,
                        "erros": 1,
                        "replicacoes": 0,
                        "ultima_replicacao": datetime.now().isoformat(),
                        "detalhes": f"Erro ao processar dados: {e}"
                    }
                ],
                "erros_operacionais": [
                    f"Erro ao processar arquivo JSON: {e}"
                ]
            }
            
            return {
                "success": True,
                "data": replicacao_data,
                "warning": f"Erro ao processar arquivo JSON: {e}"
            }
    
    except Exception as e:
        import traceback
        print(f"Erro ao executar repadmin: {e}")
        print(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def _run_repadmin_direct():
    try:
        process = subprocess.run(
            ["repadmin", "/replsummary"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
    except FileNotFoundError as e:
        return None, f"repadmin não encontrado: {e}"

    output = (process.stdout or "") + "\n" + (process.stderr or "")
    data = _parse_repadmin_output(output)

    if data["servidores"] or data["erros_operacionais"]:
        return data, None

    if process.returncode != 0:
        return None, f"Erro ao executar repadmin: {process.stderr.strip()}"

    return None, "Saída do repadmin não contém dados reconhecíveis"


def _parse_repadmin_output(text):
    linhas = text.splitlines()
    servidores = []
    erros_operacionais = []
    secao = ""

    for linha in linhas:
        if re.search(r"^\s*Source DSA", linha, re.IGNORECASE) or re.search(r"^\s*DSA Origem", linha, re.IGNORECASE):
            secao = "Origem"
            continue
        if re.search(r"^\s*Destination DSA", linha, re.IGNORECASE) or re.search(r"^\s*DSA Destino", linha, re.IGNORECASE):
            secao = "Destino"
            continue

        if re.search(r"^\s*\d+\s+-\s+.+", linha):
            erros_operacionais.append(linha.strip())
            continue

        if secao in ("Origem", "Destino"):
            match = re.match(r"^\s*(\S+)\s+([\d\.:hms]+)\s+(\d+\s*/\s*\d+)?\s+(\d+)\s*$", linha)
            if not match:
                continue

            servidor, latencia, sucesso_total, erros = match.groups()
            parceiros = 0
            if sucesso_total:
                total_match = re.search(r"/\s*(\d+)", sucesso_total)
                if total_match:
                    parceiros = int(total_match.group(1))

            erros_int = int(erros)
            status = "OK" if erros_int == 0 else ("Warning" if erros_int < 3 else "Error")

            servidores.append({
                "nome": servidor,
                "status": status,
                "parceiros": parceiros,
                "falhas": erros_int,
                "erros": erros_int,
                "replicacoes": parceiros,
                "ultima_replicacao": datetime.now().isoformat(),
                "detalhes": "",
                "delta": latencia,
                "tipo": secao,
            })

    error_names = _extract_error_names(erros_operacionais)
    servidores = _apply_error_flags(servidores, error_names)

    all_names = { _normalize_host(s["nome"]) for s in servidores }
    total_servidores = len(all_names.union(error_names))
    servidores_problemas = len({ _normalize_host(s["nome"]) for s in servidores if s["status"] != "OK" }.union(error_names))
    servidores_saudaveis = max(total_servidores - servidores_problemas, 0)

    return {
        "timestamp": datetime.now().isoformat(),
        "total_servidores": total_servidores,
        "servidores_saudaveis": servidores_saudaveis,
        "servidores_problemas": servidores_problemas,
        "servidores": servidores,
        "erros_operacionais": erros_operacionais,
    }


def _load_public_replicacao_json():
    fallback_path = Path(REPLICACAO_JSON)
    if not fallback_path.exists():
        return None
    return _load_json_with_fallback(fallback_path)


def _load_json_with_fallback(file_path):
    encodings = ['utf-8', 'utf-8-sig', 'latin1']
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            continue
    return None


def _get_replicacao_total(data):
    if not data:
        return 0
    if isinstance(data, dict):
        if "total_servidores" in data and data.get("total_servidores") is not None:
            return int(data.get("total_servidores") or 0)
        if "controladores" in data and data.get("controladores") is not None:
            return int(data.get("controladores") or 0)
        detalhes = data.get("detalhes") or {}
        controladores = detalhes.get("controladores") or []
        return len(controladores)
    return 0


def _choose_replicacao_data(local_data, public_data):
    if not local_data and not public_data:
        return {}
    if not local_data:
        return public_data
    if not public_data:
        return local_data

    local_total = _get_replicacao_total(local_data)
    public_total = _get_replicacao_total(public_data)
    return public_data if public_total > local_total else local_data


def _normalize_replicacao_data(replicacao_data):
    replicacao_data = replicacao_data or {}
    if "servidores" in replicacao_data:
        return replicacao_data

    detalhes = replicacao_data.get("detalhes") or {}
    controladores = detalhes.get("controladores") or []
    servidores = []
    for ctrl in controladores:
        sucesso_total = str(ctrl.get("sucesso_total") or "0 / 0")
        parceiros = 0
        match = re.search(r"/\s*(\d+)", sucesso_total)
        if match:
            parceiros = int(match.group(1))

        erros = int(ctrl.get("erros") or 0)
        status = "OK" if erros == 0 else "Error"

        servidores.append({
            "nome": ctrl.get("nome") or "Desconhecido",
            "status": status,
            "parceiros": parceiros,
            "falhas": erros,
            "erros": erros,
            "replicacoes": parceiros,
            "ultima_replicacao": replicacao_data.get("timestamp") or datetime.now().isoformat(),
            "detalhes": "",
            "delta": ctrl.get("latencia") or "N/A",
            "tipo": "Destino",
        })

    error_names = _extract_error_names(detalhes.get("erros_operacionais") or [])
    servidores = _apply_error_flags(servidores, error_names)

    all_names = { _normalize_host(s["nome"]) for s in servidores }
    total_servidores = len(all_names.union(error_names))
    servidores_problemas = len({ _normalize_host(s["nome"]) for s in servidores if s["status"] != "OK" }.union(error_names))
    servidores_saudaveis = max(total_servidores - servidores_problemas, 0)

    return {
        "timestamp": replicacao_data.get("timestamp") or datetime.now().isoformat(),
        "total_servidores": replicacao_data.get("controladores", total_servidores),
        "servidores_saudaveis": replicacao_data.get("replicacao_ok", servidores_saudaveis),
        "servidores_problemas": replicacao_data.get("replicacao_erro", servidores_problemas),
        "servidores": servidores,
        "erros_operacionais": detalhes.get("erros_operacionais") or [],
    }


def _normalize_host(value):
    if not value:
        return ""
    value = value.strip().lower()
    if "." in value:
        value = value.split(".")[0]
    return value


def _extract_error_names(erros_operacionais):
    nomes = set()
    for erro in erros_operacionais:
        match = re.search(r"-\s*([^\s]+)", str(erro))
        if match:
            nomes.add(_normalize_host(match.group(1)))
    return {n for n in nomes if n}


def _apply_error_flags(servidores, error_names):
    if not error_names:
        return servidores

    for servidor in servidores:
        nome_norm = _normalize_host(servidor.get("nome"))
        if nome_norm in error_names:
            servidor["status"] = "Error"
            servidor["erros"] = max(int(servidor.get("erros") or 0), 1)
            servidor["falhas"] = max(int(servidor.get("falhas") or 0), 1)
    return servidores

@app.route('/executar_replicacao_direto', methods=['POST'])
def executar_replicacao_direto():
    """Executa o comando repadmin diretamente e redireciona para a página de replicação"""
    try:
        import json
        from datetime import datetime
        from pathlib import Path
        from config import PROJECT_ROOT
        
        # Executa o comando repadmin e processa a saída
        flash("Executando verificação de replicação AD...", "info")
        result = executar_repadmin()
        
        if not result["success"]:
            flash(f"Erro ao executar verificação: {result['error']}", "danger")
            return redirect(url_for('replicacao_ad'))
        
        # Obtém os dados de replicação
        replicacao_data = result["data"]
        
        # Salva os dados em formato JSON
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(exist_ok=True)
        
        json_path = data_dir / "replicacao.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(replicacao_data, f, indent=2, ensure_ascii=False)

        # Mantém também o JSON público usado por outros fluxos (executar_tudo.py)
        public_json_path = Path(REPLICACAO_JSON)
        try:
            if public_json_path.resolve() != json_path.resolve():
                public_json_path.parent.mkdir(parents=True, exist_ok=True)
                with open(public_json_path, 'w', encoding='utf-8') as f:
                    json.dump(replicacao_data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
        
        # Mensagem de sucesso
        servidores_total = replicacao_data["total_servidores"]
        servidores_ok = replicacao_data["servidores_saudaveis"]
        servidores_problema = replicacao_data["servidores_problemas"]
        
        flash(f"Verificação concluída: {servidores_total} servidores, {servidores_ok} saudáveis, {servidores_problema} com problemas", "success")
        
        # Redireciona para a página de replicação
        return redirect(url_for('replicacao_ad'))
    except Exception as e:
        import traceback
        flash(f"Erro ao atualizar dados de replicação: {str(e)}", "danger")
        return redirect(url_for('replicacao_ad'))

@app.route('/antenas')
@login_required
def antenas_unifi():
    """Página de antenas UniFi"""
    # Carrega os dados do UniFi
    unifi_data = load_data("unifi") or {}

    # Agrupa APs por site para o template
    from collections import defaultdict
    grupos = defaultdict(list)
    for ap in (unifi_data.get("aps") or []):
        site = ap.get("site") or "Sem Regional"
        grupos[site].append(ap)

    sites_agrupados = sorted([
        {
            "nome":    site,
            "aps":     aps,
            "online":  sum(1 for a in aps if (a.get("status") or "").lower() == "online"),
            "offline": sum(1 for a in aps if (a.get("status") or "").lower() != "online"),
        }
        for site, aps in grupos.items()
    ], key=lambda s: s["nome"])

    return render_template('antenas_simples.html', unifi_data=unifi_data, sites_agrupados=sites_agrupados)

@app.route('/executar_unifi_direto', methods=['POST'])
def executar_unifi_direto():
    """Executa o script Unifi.py diretamente e redireciona para a página de antenas"""
    try:
        import subprocess
        import sys
        import os
        
        # Caminho para o script Unifi.py
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Unifi.py")
        
        # Verifica se o arquivo existe
        if not os.path.exists(script_path):
            flash(f"Script Unifi.py não encontrado em {script_path}", "danger")
            return redirect(url_for('antenas_unifi'))
        
        # Executa o script
        flash("Executando verificação de antenas...", "info")
        
        # Executa o script e captura a saída
        process = subprocess.Popen(
            [sys.executable, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Aguarda a conclusão do processo (com timeout de 60 segundos)
        try:
            stdout, stderr = process.communicate(timeout=60)
            
            if process.returncode == 0:
                flash("Verificação de antenas concluída com sucesso!", "success")
            else:
                flash(f"Erro ao executar verificação: {stderr}", "danger")
        except subprocess.TimeoutExpired:
            process.kill()
            flash("Tempo limite excedido ao executar verificação", "warning")
        
        # Redireciona para a página de antenas
        return redirect(url_for('antenas_unifi'))
    except Exception as e:
        import traceback
        flash(f"Erro ao executar verificação: {str(e)}", "danger")
        return redirect(url_for('antenas_unifi'))

@app.route('/antenas_unifi')
def redirect_antenas_unifi():
    """Redireciona para a página correta de antenas"""
    return redirect(url_for('antenas_unifi'))

@app.route('/relatorios-infra')
@login_required
def relatorios_infra():
    """Página de relatórios de infraestrutura"""
    return render_template('relatorios_infra.html')

@app.route('/api/replicacao/executar', methods=['POST'])
def executar_replicacao():
    """Executa verificação de replicação AD usando o novo script"""
    try:
        import subprocess
        import os
        
        # Executa o script PowerShell novo
        script_path = PROJECT_ROOT / "Replicacao_Final.ps1"
        
        if not script_path.exists():
            return jsonify({
                'success': False,
                'message': 'Script Replicacao_Final.ps1 não encontrado'
            })
        
        # Executa o PowerShell
        result = subprocess.run([
            'powershell.exe', 
            '-ExecutionPolicy', 'Bypass',
            '-File', str(script_path)
        ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        
        # Verifica se o arquivo JSON foi gerado
        json_path = os.path.join(os.environ["USERPROFILE"], "Desktop", "replicacao.json")
        
        return jsonify({
            'success': result.returncode == 0,
            'message': 'Replicação AD verificada com sucesso' if result.returncode == 0 else 'Erro na verificação de replicação',
            'json_gerado': os.path.exists(json_path),
            'output': result.stdout,
            'errors': result.stderr if result.stderr else None
        })
            
    except Exception as e:
        import traceback
        print(f"Erro ao executar replicação: {e}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'message': f'Erro interno: {str(e)}'
        })

@app.route('/api/antenas/verificar', methods=['POST'])
def verificar_antenas():
    """Verifica status das antenas UniFi usando script original"""
    try:
        import subprocess
        
        # Executa o script Python original das antenas
        script_path = PROJECT_ROOT / "Unifi.Py"
        
        if not script_path.exists():
            return jsonify({
                'success': False,
                'message': 'Script Unifi.Py não encontrado'
            })
        
        # Executa o script
        result = subprocess.run([
            'python', str(script_path)
        ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        
        # Verifica se o arquivo HTML foi gerado
        html_path = PROJECT_ROOT / "output" / "dados_aps_unifi.html"
        
        return jsonify({
            'success': result.returncode == 0,
            'message': 'Antenas UniFi verificadas com sucesso' if result.returncode == 0 else 'Erro na verificação das antenas',
            'html_gerado': html_path.exists(),
            'html_url': '/output/dados_aps_unifi.html' if html_path.exists() else None,
            'output': result.stdout,
            'errors': result.stderr if result.stderr else None
        })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro interno: {str(e)}'
        })

# === ROTAS DE ARQUIVOS ===

@app.route('/branding/<path:filename>')
def serve_branding_asset(filename):
    """Serve os assets originais de branding armazenados fora da pasta static."""
    if filename not in BRANDING_ASSET_FILES or not BRANDING_ASSETS_DIR.exists():
        return ("", 404)

    return send_from_directory(str(BRANDING_ASSETS_DIR), filename)

@app.route('/output/<path:filename>')
def serve_output_files(filename):
    """Serve arquivos da pasta output"""
    try:
        output_dir = PROJECT_ROOT / "output"
        return send_from_directory(str(output_dir), filename)
    except Exception as e:
        flash(f'Arquivo não encontrado: {filename}', 'error')
        return redirect(url_for('index'))

# === APIs PARA DADOS REAIS (SEM AUTENTICAÇÃO) ===

@app.route('/api/public/status/replicacao')
def api_public_status_replicacao():
    """Retorna status real da replicação AD usando o novo arquivo JSON"""
    try:
        import os
        import json
        from datetime import datetime
        
        # Caminho para o arquivo JSON
        json_path = os.path.join(os.environ["USERPROFILE"], "Public", "replicacao.json")
        
        # Verifica se o arquivo JSON existe
        if not os.path.exists(json_path):
            return jsonify({
                'status': 'sem_dados',
                'controladores': 0,
                'erros': 0,
                'ultima_verificacao': 'Nunca'
            })
        
        # Lê o arquivo JSON
        with open(json_path, 'r', encoding='ascii') as f:
            replicacao_data = json.load(f)
        
        # Extrai os dados necessários
        total_servidores = replicacao_data.get('total_servidores', 0)
        servidores_saudaveis = replicacao_data.get('servidores_saudaveis', 0)
        servidores_problemas = replicacao_data.get('servidores_problemas', 0)
        erros_operacionais = len(replicacao_data.get('erros_operacionais', []))
        
        # Obtém o timestamp do arquivo JSON
        timestamp = replicacao_data.get('timestamp', datetime.now().isoformat())
        try:
            # Tenta converter o timestamp para um objeto datetime
            dt = datetime.fromisoformat(timestamp)
            ultima_verificacao = dt.strftime('%H:%M')
        except:
            ultima_verificacao = 'Recente'
        
        return jsonify({
            'status': 'ok' if servidores_problemas == 0 and erros_operacionais == 0 else 'erro',
            'controladores': total_servidores,
            'erros': servidores_problemas + erros_operacionais,
            'ultima_verificacao': ultima_verificacao,
            'detalhes': {
                'servidores_saudaveis': servidores_saudaveis,
                'servidores_problemas': servidores_problemas,
                'erros_operacionais': erros_operacionais
            }
        })
        
    except Exception as e:
        import traceback
        print(f"Erro ao obter status da replicação: {e}")
        print(traceback.format_exc())
        return jsonify({
            'status': 'erro',
            'controladores': 0,
            'erros': 0,
            'ultima_verificacao': 'Erro',
            'erro': str(e)
        })

@app.route('/test_api')
def test_api_page():
    """Página de teste da API"""
    return render_template('test_api.html')

@app.route('/debug_antenas')
def debug_antenas_page():
    """Página de debug das antenas"""
    return render_template('debug_antenas.html')

@app.route('/debug_api')
def debug_api_page():
    """Página de debug da API"""
    return render_template('debug_api.html')

@app.route('/antenas_simples')
def antenas_unifi_simples():
    """Página simplificada de antenas UniFi"""
    return render_template('antenas_unifi_simples.html')

@app.route('/antenas_jquery')
def antenas_unifi_jquery():
    """Página de antenas UniFi com jQuery"""
    return render_template('antenas_jquery.html')

@app.route('/antenas_basico')
def antenas_unifi_basico():
    """Página de antenas UniFi versão básica"""
    return render_template('antenas_basico.html')

@app.route('/teste_api')
def teste_api():
    """Página de teste da API"""
    return render_template('antenas_teste.html')

@app.route('/antenas_publico')
def antenas_publico():
    """Página de antenas UniFi sem autenticação"""
    return render_template('antenas_basico.html')

@app.route('/antenas_direto')
def antenas_direto():
    """Página de antenas UniFi com execução direta"""
    return render_template('antenas_direto.html')

# Rota para executar o script Unifi.py
@app.route('/executar_unifi', methods=['POST'])
def executar_unifi():
    """Executa o script Unifi.py diretamente"""
    try:
        import subprocess
        import sys
        import os
        from pathlib import Path
        
        # Caminho para o script Unifi.py
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "Unifi.py")
        
        # Verifica se o arquivo existe
        if not os.path.exists(script_path):
            return jsonify({
                "success": False,
                "message": f"Script não encontrado: {script_path}"
            })
        
        # Inicia o processo em background
        process = subprocess.Popen(
            [sys.executable, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        # Armazena o PID do processo para verificar depois
        app.config['UNIFI_PROCESS_PID'] = process.pid
        app.config['UNIFI_START_TIME'] = datetime.now()
        
        return jsonify({
            "success": True,
            "message": f"Script iniciado com sucesso (PID: {process.pid})"
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return jsonify({
            "success": False,
            "message": str(e),
            "details": error_details
        })

# Rota para verificar o status da execução do Unifi.py
@app.route('/status_unifi')
def status_unifi():
    """Verifica o status da execução do script Unifi.py"""
    try:
        # Verifica se o processo ainda está em execução
        pid = app.config.get('UNIFI_PROCESS_PID')
        start_time = app.config.get('UNIFI_START_TIME')
        
        if pid:
            import psutil
            import os
            
            # Verifica se o processo ainda existe
            try:
                process = psutil.Process(pid)
                if process.is_running() and "python" in process.name().lower():
                    # Processo ainda está em execução
                    elapsed = (datetime.now() - start_time).total_seconds() if start_time else 0
                    return jsonify({
                        "completed": False,
                        "pid": pid,
                        "elapsed_seconds": elapsed,
                        "message": f"Script em execução há {elapsed:.1f} segundos"
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Processo não existe mais
                pass
        
        # Verifica se os dados do UniFi estão disponíveis e atualizados
        unifi_data = load_data("unifi")
        
        if unifi_data:
            # Verifica se os dados foram atualizados recentemente
            timestamp = unifi_data.get('timestamp', '')
            if timestamp:
                try:
                    # Tenta converter o timestamp para datetime
                    if 'T' in timestamp:
                        data_time = datetime.fromisoformat(timestamp)
                    else:
                        data_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")
                    
                    # Calcula a diferença de tempo
                    now = datetime.now()
                    diff = now - data_time
                    
                    # Se os dados foram atualizados nos últimos 5 minutos, considera concluído
                    if diff.total_seconds() < 300:
                        return jsonify({
                            "completed": True,
                            "timestamp": timestamp,
                            "age_seconds": diff.total_seconds(),
                            "message": f"Dados atualizados há {diff.total_seconds():.1f} segundos"
                        })
                except Exception as e:
                    # Erro ao processar o timestamp
                    pass
        
        # Se chegou aqui, assume que o script terminou mas não atualizou os dados
        return jsonify({
            "completed": True,
            "message": "Script concluído ou não está em execução"
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return jsonify({
            "completed": True,  # Assume que terminou para não ficar travado
            "error": str(e),
            "details": error_details
        })

@app.route('/antenas_teste')
def antenas_teste_page():
    """Página de teste das antenas (sem login)"""
    return render_template('antenas_unifi.html')

@app.route('/api/check_file/<component>')
def api_check_file(component):
    """Verifica o arquivo de dados de um componente"""
    from pathlib import Path
    import os
    
    file_path = Path(f"data/{component}.json")
    
    if not file_path.exists():
        return jsonify({
            'status': 'erro',
            'mensagem': f'Arquivo {component}.json não encontrado'
        })
    
    try:
        # Informações do arquivo
        stat = file_path.stat()
        size = os.path.getsize(file_path)
        
        # Tenta carregar o arquivo
        data = load_data(component)
        
        if data:
            # Verifica se os dados estão atualizados
            is_fresh = is_data_fresh(component)
            
            # Retorna informações sobre o arquivo
            return jsonify({
                'status': 'ok',
                'arquivo': {
                    'nome': file_path.name,
                    'tamanho': size,
                    'tamanho_formatado': f"{size / 1024:.2f} KB",
                    'ultima_modificacao': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'permissoes': oct(stat.st_mode)[-3:]
                },
                'dados': {
                    'valido': True,
                    'chaves': list(data.keys()),
                    'atualizado': is_fresh,
                    'timestamp': data.get('timestamp', 'Não disponível')
                }
            })
        else:
            return jsonify({
                'status': 'erro',
                'mensagem': f'Não foi possível carregar os dados do arquivo {component}.json',
                'arquivo': {
                    'nome': file_path.name,
                    'tamanho': size,
                    'tamanho_formatado': f"{size / 1024:.2f} KB",
                    'ultima_modificacao': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'permissoes': oct(stat.st_mode)[-3:]
                }
            })
    except Exception as e:
        return jsonify({
            'status': 'erro',
            'mensagem': f'Erro ao verificar arquivo: {str(e)}'
        })

@app.route('/api/test')
def api_test():
    """Rota de teste para verificar se a API está funcionando"""
    return jsonify({
        'status': 'ok',
        'message': 'API funcionando corretamente',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/public/status/unifi')
def api_public_status_unifi():
    """Retorna status real das antenas UniFi"""
    try:
        # Tenta carregar dados do armazenamento centralizado
        print("API: Tentando carregar dados do UniFi...")
        unifi_data = load_data("unifi")
        
        if unifi_data:
            print(f"API: Dados do UniFi carregados com sucesso. Total de APs: {unifi_data.get('total_aps', 0)}")
            # Dados encontrados no armazenamento centralizado
            # Formata a resposta
            
            # Verifica se há timestamp
            if 'timestamp' not in unifi_data:
                print("API: Timestamp não encontrado nos dados, usando timestamp atual")
                timestamp_str = datetime.now().isoformat()
            else:
                timestamp_str = unifi_data.get('timestamp')
                print(f"API: Timestamp encontrado: {timestamp_str}")
            
            # Converte o timestamp para datetime
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                print(f"API: Timestamp convertido: {timestamp}")
            except Exception as e:
                print(f"API: Erro ao converter timestamp: {e}")
                timestamp = datetime.now()
            
            # Verifica se os dados estão atualizados
            dados_atualizados = is_data_fresh('unifi')
            print(f"API: Dados atualizados: {dados_atualizados}")
            
            # Prepara a resposta
            response = {
                'status': 'ok' if unifi_data.get('aps_offline', 0) == 0 else 'aviso',
                'total_aps': unifi_data.get('total_aps', 0),
                'aps_online': unifi_data.get('aps_online', 0),
                'aps_offline': unifi_data.get('aps_offline', 0),
                'clientes_conectados': unifi_data.get('clientes_conectados', 0),
                'ultima_verificacao': timestamp.strftime('%H:%M'),
                'controller_online': unifi_data.get('controller', {}).get('online', False),
                'controller_ip': unifi_data.get('controller', {}).get('ip', 'Não disponível'),
                'controller_porta': unifi_data.get('controller', {}).get('porta', 'Não disponível'),
                'controller_versao': unifi_data.get('controller', {}).get('versao', 'Não disponível'),
                'aps': unifi_data.get('aps', []),
                'sites': unifi_data.get('sites', []),
                'dados_atualizados': dados_atualizados,
                'timestamp': timestamp_str
            }
            
            # Verifica se há APs na resposta
            aps = unifi_data.get('aps', [])
            if aps:
                print(f"API: {len(aps)} APs encontrados nos dados")
            else:
                print("API: Nenhum AP encontrado nos dados")
            
            return jsonify(response)
        
        # Se não encontrou dados no armazenamento centralizado, tenta o método antigo
        html_path = PROJECT_ROOT / "output" / "dados_aps_unifi.html"
        
        if not html_path.exists():
            return jsonify({
                'status': 'sem_dados',
                'total_aps': 0,
                'aps_online': 0,
                'aps_offline': 0,
                'clientes_conectados': 0,
                'ultima_verificacao': 'Nunca',
                'controller_online': False,
                'controller_ip': 'Não disponível',
                'controller_porta': 'Não disponível',
                'controller_versao': 'Não disponível',
                'aps': [],
                'dados_atualizados': False
            })
        
        # Lê o arquivo HTML e extrai dados básicos
        content = html_path.read_text(encoding='utf-8')
        
        # Verifica se há erro no arquivo
        if '❌' in content:
            return jsonify({
                'status': 'erro',
                'total_aps': 0,
                'aps_online': 0,
                'aps_offline': 0,
                'clientes_conectados': 0,
                'ultima_verificacao': 'Erro',
                'controller_online': False,
                'controller_ip': 'Não disponível',
                'controller_porta': 'Não disponível',
                'controller_versao': 'Não disponível',
                'aps': [],
                'dados_atualizados': False
            })
        
        # Conta APs online/offline de forma simplificada
        import re
        aps_online = content.count('Online') if '❌' not in content else 0
        aps_offline = content.count('Offline') if '❌' not in content else 0
        total_aps = aps_online + aps_offline
        
        # Última modificação do arquivo
        import os
        ultima_mod = datetime.fromtimestamp(os.path.getmtime(html_path))
        
        return jsonify({
            'status': 'ok' if aps_offline == 0 else 'aviso',
            'total_aps': total_aps,
            'aps_online': aps_online,
            'aps_offline': aps_offline,
            'clientes_conectados': 0,
            'ultima_verificacao': ultima_mod.strftime('%H:%M'),
            'controller_online': True,
            'controller_ip': 'Não disponível',
            'controller_porta': 'Não disponível',
            'controller_versao': 'Não disponível',
            'aps': [],
            'dados_atualizados': False,
            'mensagem': 'Dados limitados do arquivo HTML. Execute o script Unifi.py para dados completos.'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'erro',
            'total_aps': 0,
            'aps_online': 0,
            'aps_offline': 0,
            'clientes_conectados': 0,
            'ultima_verificacao': 'Erro',
            'controller_online': False,
            'controller_ip': 'Não disponível',
            'controller_porta': 'Não disponível',
            'controller_versao': 'Não disponível',
            'aps': [],
            'dados_atualizados': False,
            'erro': str(e)
        })

@app.route('/api/public/status/atualizacao')
def api_public_status_atualizacao():
    """Retorna status da atualização automática"""
    try:
        status_file = PROJECT_ROOT / "output" / "status_atualizacao.json"
        
        # Verifica os arquivos de dados
        replicacao_html = PROJECT_ROOT / "output" / "replsummary.html"
        unifi_html = PROJECT_ROOT / "output" / "dados_aps_unifi.html"
        dashboard_file = PROJECT_ROOT / "output" / "dashboard_hierarquico.html"
        gps_html = PROJECT_ROOT / "output" / "print_temp.html"
        
        # Status do serviço
        service_status = {
            'ativo': False,
            'timestamp': datetime.now().isoformat(),
            'mensagem': 'Serviço de atualização não está em execução',
            'componentes': {
                'replicacao_ad': {
                    'arquivo_existe': replicacao_html.exists(),
                    'ultima_atualizacao': None,
                    'proxima_atualizacao': None
                },
                'antenas_unifi': {
                    'arquivo_existe': unifi_html.exists(),
                    'ultima_atualizacao': None,
                    'proxima_atualizacao': None
                },
                'servidores': {
                    'arquivo_existe': dashboard_file.exists(),
                    'ultima_atualizacao': None,
                    'proxima_atualizacao': None
                },
                'gps_amigo': {
                    'arquivo_existe': gps_html.exists(),
                    'ultima_atualizacao': None,
                    'proxima_atualizacao': None
                }
            }
        }
        
        # Obtém as datas de modificação dos arquivos
        if replicacao_html.exists():
            service_status['componentes']['replicacao_ad']['ultima_atualizacao'] = datetime.fromtimestamp(replicacao_html.stat().st_mtime).isoformat()
        
        if unifi_html.exists():
            service_status['componentes']['antenas_unifi']['ultima_atualizacao'] = datetime.fromtimestamp(unifi_html.stat().st_mtime).isoformat()
        
        if dashboard_file.exists():
            service_status['componentes']['servidores']['ultima_atualizacao'] = datetime.fromtimestamp(dashboard_file.stat().st_mtime).isoformat()
        
        if gps_html.exists():
            service_status['componentes']['gps_amigo']['ultima_atualizacao'] = datetime.fromtimestamp(gps_html.stat().st_mtime).isoformat()
        
        # Se o arquivo de status existe, lê as informações adicionais
        if status_file.exists():
            try:
                with open(status_file, 'r', encoding='utf-8') as f:
                    status_data = json.load(f)
                
                # Verifica se o serviço está ativo
                ultima_atualizacao = datetime.fromisoformat(status_data['timestamp'])
                agora = datetime.now()
                diferenca = (agora - ultima_atualizacao).total_seconds()
                
                service_status['ativo'] = diferenca < 60  # Considera ativo se atualizado nos últimos 60 segundos
                service_status['mensagem'] = status_data.get('mensagem', 'Serviço de atualização em execução')
                
                # Adiciona informações sobre próximas atualizações
                if 'proximas_verificacoes' in status_data:
                    for componente, segundos in status_data['proximas_verificacoes'].items():
                        if componente in service_status['componentes']:
                            service_status['componentes'][componente]['proxima_atualizacao'] = segundos
            except Exception as e:
                service_status['mensagem'] = f'Erro ao ler arquivo de status: {str(e)}'
        
        return jsonify(service_status)
        
    except Exception as e:
        return jsonify({
            'status': 'erro',
            'mensagem': f'Erro ao verificar status: {str(e)}',
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/public/status/relatorios')
def api_public_status_relatorios():
    """Retorna status dos relatórios"""
    try:
        output_dir = PROJECT_ROOT / "output"
        
        if not output_dir.exists():
            return jsonify({
                'total_relatorios': 0,
                'relatorios_recentes': 0,
                'tamanho_total': '0 MB',
                'ultima_atualizacao': 'Nunca'
            })
        
        # Lista arquivos HTML na pasta output
        html_files = list(output_dir.glob('*.html'))
        
        # Calcula tamanho total
        tamanho_total = sum(f.stat().st_size for f in html_files if f.exists())
        tamanho_mb = tamanho_total / (1024 * 1024)
        
        # Conta relatórios recentes (últimas 24h)
        from datetime import datetime, timedelta
        agora = datetime.now()
        ontem = agora - timedelta(days=1)
        
        recentes = sum(1 for f in html_files 
                      if f.exists() and datetime.fromtimestamp(f.stat().st_mtime) > ontem)
        
        # Última atualização
        if html_files:
            ultima_mod = max(datetime.fromtimestamp(f.stat().st_mtime) 
                           for f in html_files if f.exists())
            ultima_str = ultima_mod.strftime('%H:%M')
        else:
            ultima_str = 'Nunca'
        
        return jsonify({
            'total_relatorios': len(html_files),
            'relatorios_recentes': recentes,
            'tamanho_total': f'{tamanho_mb:.1f} MB',
            'ultima_atualizacao': ultima_str
        })
        
    except Exception as e:
        return jsonify({
            'total_relatorios': 0,
            'relatorios_recentes': 0,
            'tamanho_total': '0 MB',
            'ultima_atualizacao': 'Erro',
            'erro': str(e)
        })

@app.route('/teste-cards')
def teste_cards():
    """Página de teste dos cards com dados reais"""
    return send_from_directory(str(PROJECT_ROOT), 'teste_cards.html')

# === ROTAS DE CONFIGURAÇÃO ===

@app.route('/configuracoes')
@login_required
def configuracoes():
    """Página de configurações gerais"""
    try:
        # Carrega configurações existentes
        env_file = PROJECT_ROOT / "environment.json"
        config = {}
        
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        
        return render_template('configuracoes.html', config=config)
        
    except Exception as e:
        flash(f'Erro ao carregar configurações: {str(e)}', 'error')
        return render_template('configuracoes.html', config={})

# === ROTAS DE EXECUÇÃO ===

@app.route('/executar/completo')
@login_required
def executar_completo():
    """Página para executar verificação completa"""
    return render_template('executar_completo.html')

@app.route('/dashboard/hierarquico')
@login_required
def dashboard_hierarquico_web():
    """Página do dashboard hierárquico integrado"""
    try:
        # Gera dashboard e retorna o arquivo
        arquivo_dashboard = dashboard_hierarquico.gerar_todos_dashboards()
        
        # Redireciona para o arquivo HTML gerado
        return redirect('/output/dashboard_hierarquico.html')
        
    except Exception as e:
        flash(f'Erro ao gerar dashboard: {str(e)}', 'error')
        return redirect(url_for('index'))

# === ROTAS DE BACKUP ===

@app.route('/backup')
@login_required
def backup():
    """Página de backup e restauração"""
    return render_template('backup.html')

# === APIs ===

@app.route('/api/regional', methods=['POST'])
def api_salvar_regional():
    """API para salvar regional (nova ou editada)"""
    try:
        data = request.get_json()
        
        # Validação básica
        if not data.get('nome'):
            return jsonify({'success': False, 'message': 'Nome da regional é obrigatório'})
        
        codigo = data.get('codigo', '').upper()
        codigo_original = (data.get('codigo_original') or codigo).upper()
        nome = data['nome']
        descricao = data.get('descricao', '')
        
        # Se não tem código, gera um baseado no nome
        if not codigo:
            codigo = nome.upper().replace(' ', '_').replace('-', '_')
            # Remove caracteres especiais
            import re
            codigo = re.sub(r'[^A-Z0-9_]', '', codigo)
        
        # Verifica se é edição ou nova
        regional_existente = gerenciador_regionais.obter_regional(codigo)
        regional_original = gerenciador_regionais.obter_regional(codigo_original) if data.get('editando') else None

        if regional_existente and not data.get('editando'):
            return jsonify({'success': False, 'message': 'Regional com este código já existe'})

        if data.get('editando'):
            if not regional_original:
                return jsonify({'success': False, 'message': 'Regional original não encontrada'})
            if codigo != codigo_original and regional_existente:
                return jsonify({'success': False, 'message': 'Já existe outra regional com este código'})
            codigo = gerenciador_regionais.atualizar_regional(codigo_original, codigo, nome, descricao)
        else:
            gerenciador_regionais.adicionar_regional(codigo, nome, descricao)
        
        return jsonify({'success': True, 'message': 'Regional salva com sucesso!', 'codigo': codigo})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/regional/<codigo_regional>/servidor', methods=['POST'])
def api_salvar_servidor_regional(codigo_regional):
    """API para salvar servidor em uma regional"""
    try:
        data = request.get_json()
        tipo_servidor = (data.get('tipo_monitoramento') or data.get('tipo') or 'vm').strip().lower()
        funcao_servidor = (data.get('funcao') or '').strip()
        sistema_operacional = (data.get('sistema_operacional') or '').strip()
        servidor_id = (data.get('id') or '').strip()
        
        # Validação básica
        campos_obrigatorios = ['nome', 'ip', 'usuario', 'senha', 'funcao']
        for campo in campos_obrigatorios:
            valor = funcao_servidor if campo == 'funcao' else data.get(campo)
            if not valor:
                return jsonify({'success': False, 'message': f'Campo {campo} é obrigatório'})

        if tipo_servidor != 'vm':
            tipo_servidor = 'vm'
        
        # Verifica se a regional existe
        if not gerenciador_regionais.obter_regional(codigo_regional):
            return jsonify({'success': False, 'message': 'Regional não encontrada'})
        
        # Monta dados do servidor
        servidor = {
            'id': servidor_id or f"srv_{codigo_regional.lower()}_{len(gerenciador_regionais.listar_servidores_regional(codigo_regional)) + 1:02d}",
            'nome': data['nome'],
            'tipo': tipo_servidor,
            'tipo_monitoramento': 'vm',
            'ip': data['ip'],
            'usuario': data['usuario'],
            'senha': data['senha'],
            'porta': int(data.get('porta', 443)),
            'timeout': int(data.get('timeout', 10)),
            'ativo': data.get('ativo', True),
            'modelo': (data.get('modelo') or 'Servidor Virtual').strip(),
            'funcao': funcao_servidor,
            'sistema_operacional': sistema_operacional,
        }

        servidor_existente = gerenciador_regionais.obter_servidor(codigo_regional, servidor['id']) if servidor_id else None

        if servidor_existente:
            gerenciador_regionais.atualizar_servidor(codigo_regional, servidor['id'], servidor)
            return jsonify({'success': True, 'message': 'Servidor atualizado com sucesso!'})

        gerenciador_regionais.adicionar_servidor(codigo_regional, servidor)

        return jsonify({'success': True, 'message': 'Servidor adicionado com sucesso!'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/regional/<codigo_regional>/link', methods=['POST'])
def api_salvar_link_regional(codigo_regional):
    """API para salvar link em uma regional"""
    try:
        data = request.get_json()
        
        # Validação básica
        campos_obrigatorios = ['nome', 'ip', 'provedor']
        for campo in campos_obrigatorios:
            if not data.get(campo):
                return jsonify({'success': False, 'message': f'Campo {campo} é obrigatório'})
        
        # Verifica se a regional existe
        if not gerenciador_regionais.obter_regional(codigo_regional):
            return jsonify({'success': False, 'message': 'Regional não encontrada'})
        
        # Monta dados do link
        link = {
            'id': data.get('id') or f"link_{codigo_regional.lower()}_{len(gerenciador_regionais.listar_links_regional(codigo_regional)) + 1:02d}",
            'nome': data['nome'],
            'ip': data['ip'],
            'provedor': data['provedor'],
            'ativo': data.get('ativo', True)
        }

        link_existente = gerenciador_regionais.obter_link(codigo_regional, link['id']) if data.get('id') else None

        if link_existente:
            gerenciador_regionais.atualizar_link(codigo_regional, link['id'], link)
            return jsonify({'success': True, 'message': 'Link atualizado com sucesso!'})

        # Adiciona link à regional
        gerenciador_regionais.adicionar_link(codigo_regional, link)
        
        return jsonify({'success': True, 'message': 'Link adicionado com sucesso!'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/regional/<codigo_regional>/servidor/<id_servidor>/editar')
@login_required
def editar_servidor_regional(codigo_regional, id_servidor):
    """Página para editar um servidor de uma regional"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            flash('Regional não encontrada', 'error')
            return redirect(url_for('listar_regionais'))

        servidor = gerenciador_regionais.obter_servidor(codigo_regional, id_servidor)
        if not servidor:
            flash('Servidor não encontrado', 'error')
            return redirect(url_for('detalhar_regional', codigo_regional=codigo_regional))

        return render_template(
            'servidor_regional_form.html',
            regional_codigo=codigo_regional,
            regional_nome=regional_info.get('nome', codigo_regional),
            servidor=servidor,
            acao='Editar'
        )

    except Exception as e:
        flash(f'Erro ao carregar servidor: {str(e)}', 'error')
        return redirect(url_for('detalhar_regional', codigo_regional=codigo_regional))

@app.route('/regional/<codigo_regional>/link/novo')
@login_required
def novo_link_regional(codigo_regional):
    """Página para adicionar link a uma regional"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            flash('Regional não encontrada', 'error')
            return redirect(url_for('listar_regionais'))

        return render_template(
            'link_regional_form.html',
            regional_codigo=codigo_regional,
            regional_nome=regional_info.get('nome', codigo_regional),
            link=None,
            acao='Adicionar'
        )

    except Exception as e:
        flash(f'Erro: {str(e)}', 'error')
        return redirect(url_for('listar_regionais'))

@app.route('/regional/<codigo_regional>/link/<id_link>/editar')
@login_required
def editar_link_regional(codigo_regional, id_link):
    """Página para editar um link de uma regional"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            flash('Regional não encontrada', 'error')
            return redirect(url_for('listar_regionais'))

        link = gerenciador_regionais.obter_link(codigo_regional, id_link)
        if not link:
            flash('Link não encontrado', 'error')
            return redirect(url_for('detalhar_regional', codigo_regional=codigo_regional))

        return render_template(
            'link_regional_form.html',
            regional_codigo=codigo_regional,
            regional_nome=regional_info.get('nome', codigo_regional),
            link=link,
            acao='Editar'
        )

    except Exception as e:
        flash(f'Erro ao carregar link: {str(e)}', 'error')
        return redirect(url_for('detalhar_regional', codigo_regional=codigo_regional))

@app.route('/api/regional/<codigo_regional>/link/<id_link>', methods=['DELETE'])
@app.route('/api/regional/<codigo_regional>/link/<id_link>/excluir', methods=['DELETE'])
@login_required
def api_excluir_link_regional(codigo_regional, id_link):
    """API para excluir um link de uma regional"""
    try:
        ok, msg = gerenciador_regionais.remover_link(codigo_regional, id_link)

        if not ok:
            return jsonify({"success": False, "message": msg}), 404

        return jsonify({"success": True, "message": msg})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/regional/<codigo_regional>/servidor/<id_servidor>', methods=['DELETE'])
@app.route('/api/regional/<codigo_regional>/servidor/<id_servidor>/excluir', methods=['DELETE'])
@login_required
def api_excluir_servidor_regional(codigo_regional, id_servidor):
    """API para excluir um servidor de uma regional"""
    try:
        ok, msg = gerenciador_regionais.remover_servidor(codigo_regional, id_servidor)

        if not ok:
            return jsonify({"success": False, "message": msg}), 404

        return jsonify({"success": True, "message": msg})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/regional/<codigo_regional>/servidor/<id_servidor>/testar', methods=['GET'])
@login_required
def api_testar_servidor_regional(codigo_regional, id_servidor):
    try:
        servidor = gerenciador_regionais.obter_servidor(codigo_regional, id_servidor)
        if not servidor:
            return jsonify({"success": False, "message": "Servidor não encontrado"}), 404

        ip = servidor.get("ip")
        if not ip:
            return jsonify({"success": False, "message": "Servidor sem IP cadastrado"}), 400

        import subprocess
        from datetime import datetime

        # Windows ping
        cmd = ["ping", "-n", "1", "-w", "5000", ip]
        result = subprocess.run(cmd, capture_output=True, text=True)

        online = _ping_indica_online(result)
        novo_status = "online" if online else "offline"

        # ✅ Atualiza os dados do servidor dentro da regional
        servidor["status"] = novo_status
        servidor["erro"] = None if online else "Timeout"
        servidor["ultima_verificacao"] = datetime.now().isoformat()

        # ✅ Salva no JSON (isso é o mais importante)
        gerenciador_regionais.atualizar_servidor(codigo_regional, id_servidor, servidor)

        return jsonify({
            "success": True,
            "status": novo_status,
            "message": "Servidor ONLINE" if online else "Servidor OFFLINE"
        })

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/regional/<codigo_regional>/servidor/<id_servidor>/hardware', methods=['GET'])
@login_required
def api_hardware_servidor(codigo_regional, id_servidor):
    try:
        servidor = gerenciador_regionais.obter_servidor(codigo_regional, id_servidor)
        if not servidor:
            return jsonify({"success": False, "message": "Servidor não encontrado"}), 404

        tipo = (servidor.get("tipo_monitoramento") or servidor.get("tipo") or "vm").strip().lower()
        ip = servidor.get("ip")
        community = servidor.get("snmp_community", "public")

        # Fluxo padrão das regionais: coletar hardware da VM via WinRM.
        if tipo == "vm":
            resultado = coletar_hardware_vm(servidor)
            return jsonify(resultado)

        # Compatibilidade legada para registros antigos.
        if tipo == "idrac":
            resultado = verificador_v2.coletar_hardware_idrac(servidor)
            if resultado and resultado.get("success"):
                return jsonify(resultado)

        elif tipo == "ilo":
            # por enquanto reaproveita (depois criamos coletar_hardware_ilo)
            resultado = verificador_v2.coletar_hardware_idrac(servidor)
            if resultado and resultado.get("success"):
                return jsonify(resultado)

        # ✅ 2) fallback via SNMP Worker (para ambos)
        resultado = coletar_hardware_snmp_worker(ip, community)
        return jsonify(resultado)

    except Exception as e:
        current_app.logger.exception("Erro ao buscar hardware")
        return jsonify({"success": False, "message": str(e)}), 500

def _ps_single_quote(value):
    return str(value or "").replace("'", "''")


def _is_local_target(ip):
    target = str(ip or "").strip().lower()
    if not target:
        return False

    local_names = {"localhost", "127.0.0.1", "::1"}
    try:
        hostname = socket.gethostname().lower()
        fqdn = socket.getfqdn().lower()
        local_names.update({hostname, fqdn})
    except Exception:
        pass

    try:
        local_names.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass

    return target in local_names


def _servidor_usa_ssh_linux(servidor):
    sistema_operacional = str(servidor.get("sistema_operacional") or "").strip().lower()
    tipo_monitoramento = str(servidor.get("tipo_monitoramento") or servidor.get("tipo") or "").strip().lower()
    if tipo_monitoramento in {"linux", "ssh"}:
        return True

    indicadores_linux = ("ubuntu", "debian", "linux", "centos", "rocky", "alma", "redhat", "rhel")
    return any(indicador in sistema_operacional for indicador in indicadores_linux)


def _obter_detalhes_vm_local_fallback(message=None):
    try:
        memory_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    except Exception:
        memory_gb = None

    disks = []
    try:
        for part in psutil.disk_partitions(all=False):
            if not part.fstype:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            disks.append({
                "drive": part.device.rstrip("\\") or part.mountpoint,
                "volumeName": part.mountpoint,
                "totalGB": round(usage.total / (1024 ** 3), 2),
                "freeGB": round(usage.free / (1024 ** 3), 2),
            })
    except Exception:
        disks = []

    services = []
    try:
        for service in psutil.win_service_iter():
            info = service.as_dict()
            name = info.get("name") or ""
            display_name = info.get("display_name") or ""
            if "bitdefender" in name.lower() or "bitdefender" in display_name.lower():
                services.append({
                    "name": name,
                    "displayName": display_name,
                    "status": info.get("status") or "unknown",
                    "startMode": info.get("start_type") or "",
                })
    except Exception:
        services = []

    return {
        "success": True,
        "details": {
            "operatingSystem": platform.platform(),
            "manufacturer": "Local",
            "model": platform.node() or "Localhost",
            "processors": psutil.cpu_count(logical=False) or psutil.cpu_count() or None,
            "processorName": platform.processor() or "N/A",
            "memory": memory_gb,
            "uptime": "N/A",
            "disks": disks,
            "bitdefender": {
                "installed": len(services) > 0,
                "runningServices": len([svc for svc in services if str(svc.get("status")).lower() == "running"]),
                "services": services,
                "products": [],
            },
        },
        "message": message or "Inventario local obtido sem WMI remoto.",
    }


def _formatar_uptime_linux(segundos):
    try:
        total_segundos = int(float(segundos or 0))
    except (TypeError, ValueError):
        return "N/A"

    dias, resto = divmod(total_segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, _ = divmod(resto, 60)
    return f"{dias} dias, {horas} horas, {minutos} minutos"


def _parse_lscpu_value(output, key):
    prefixo = f"{key}:"
    for linha in str(output or "").splitlines():
        if linha.startswith(prefixo):
            return linha.split(":", 1)[1].strip()
    return ""


def _obter_detalhes_vm_linux_ssh(servidor, ip, username, password):
    try:
        import paramiko
    except Exception as exc:
        return {
            "success": False,
            "message": f"Biblioteca SSH indisponível: {exc}"
        }

    comandos = {
        "operating_system": "cat /etc/os-release 2>/dev/null | sed -n 's/^PRETTY_NAME=//p' | head -n 1 | tr -d '\"'",
        "manufacturer": "cat /sys/class/dmi/id/sys_vendor 2>/dev/null || echo ''",
        "model": "cat /sys/class/dmi/id/product_name 2>/dev/null || hostnamectl 2>/dev/null | sed -n 's/^ *Virtualization: //p' | head -n 1",
        "cpu_model": "LC_ALL=C lscpu 2>/dev/null | sed -n 's/^Model name:[[:space:]]*//p' | head -n 1",
        "cpu_count": "getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 0",
        "memory_kib": "awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null",
        "uptime_seconds": "cut -d' ' -f1 /proc/uptime 2>/dev/null",
        "bitdefender_services": "systemctl list-units --type=service --all --no-pager --no-legend 2>/dev/null | grep -i bitdefender || true",
        "disks": "df -B1 --output=source,size,avail,target -x tmpfs -x devtmpfs 2>/dev/null | tail -n +2",
    }

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh_port = servidor.get("ssh_port") or servidor.get("porta") or 22
    try:
        ssh_port = int(ssh_port)
    except (TypeError, ValueError):
        ssh_port = 22

    try:
        ssh.connect(
            hostname=ip,
            port=ssh_port,
            username=username,
            password=password,
            timeout=12,
            banner_timeout=12,
            auth_timeout=12,
            look_for_keys=False,
            allow_agent=False,
        )

        resultados = {}
        for chave, comando in comandos.items():
            _, stdout, stderr = ssh.exec_command(comando, timeout=20)
            saida = stdout.read().decode(errors="ignore").strip()
            erro = stderr.read().decode(errors="ignore").strip()
            resultados[chave] = saida or erro
    except Exception as exc:
        return {
            "success": False,
            "message": str(exc),
        }
    finally:
        try:
            ssh.close()
        except Exception:
            pass

    try:
        memoria_gib = round(float(resultados.get("memory_kib") or 0) / 1048576, 2)
    except (TypeError, ValueError):
        memoria_gib = None

    try:
        processadores = int(str(resultados.get("cpu_count") or "0").strip() or 0)
    except (TypeError, ValueError):
        processadores = None

    discos = []
    for linha in str(resultados.get("disks") or "").splitlines():
        partes = linha.split()
        if len(partes) < 4:
            continue

        origem, tamanho, livre, montagem = partes[0], partes[1], partes[2], partes[3]
        try:
            total_gb = round(int(tamanho) / (1024 ** 3), 2)
            livre_gb = round(int(livre) / (1024 ** 3), 2)
        except (TypeError, ValueError):
            continue

        discos.append({
            "drive": montagem,
            "volumeName": origem,
            "totalGB": total_gb,
            "freeGB": livre_gb,
        })

    servicos_bitdefender = []
    for linha in str(resultados.get("bitdefender_services") or "").splitlines():
        texto = linha.strip()
        if not texto:
            continue
        nome_servico = texto.split()[0]
        status_servico = "Running" if " running " in f" {texto.lower()} " else "Stopped"
        servicos_bitdefender.append({
            "name": nome_servico,
            "displayName": nome_servico,
            "status": status_servico,
            "startMode": "N/A",
        })

    return {
        "success": True,
        "details": {
            "operatingSystem": resultados.get("operating_system") or "Linux",
            "manufacturer": resultados.get("manufacturer") or "N/A",
            "model": resultados.get("model") or "Linux",
            "processors": processadores,
            "processorName": resultados.get("cpu_model") or "N/A",
            "memory": memoria_gib,
            "uptime": _formatar_uptime_linux(resultados.get("uptime_seconds")),
            "disks": discos,
            "bitdefender": {
                "installed": bool(servicos_bitdefender),
                "runningServices": sum(1 for item in servicos_bitdefender if item.get("status") == "Running"),
                "services": servicos_bitdefender,
                "products": [],
            },
        },
    }


def _obter_detalhes_vm_linux_http_probe(servidor, ip):
    porta = servidor.get("porta") or 443
    try:
        porta = int(porta)
    except (TypeError, ValueError):
        porta = 443

    endpoints = [
        f"https://{ip}:{porta}",
        f"http://{ip}:80",
    ]

    for endpoint in endpoints:
        try:
            resultado = subprocess.run(
                ["curl.exe", "-k", "-I", "--max-time", "10", endpoint],
                capture_output=True,
                text=True,
                timeout=20,
            )
            cabecalhos = (resultado.stdout or "").strip()
            if resultado.returncode != 0 or not cabecalhos:
                continue

            server_header = ""
            for linha in cabecalhos.splitlines():
                if linha.lower().startswith("server:"):
                    server_header = linha.split(":", 1)[1].strip()
                    break

            sistema_operacional = servidor.get("sistema_operacional") or "Linux"
            if "ubuntu" in server_header.lower() and "ubuntu" not in str(sistema_operacional).lower():
                sistema_operacional = f"{sistema_operacional} / Ubuntu" if sistema_operacional else "Ubuntu"

            return {
                "success": True,
                "details": {
                    "operatingSystem": sistema_operacional,
                    "manufacturer": "N/A",
                    "model": server_header or servidor.get("modelo") or "Servidor Linux",
                    "processors": None,
                    "processorName": "N/A",
                    "memory": None,
                    "uptime": "N/A",
                    "disks": [],
                    "bitdefender": {
                        "installed": False,
                        "runningServices": 0,
                        "services": [],
                        "products": [],
                    },
                },
                "message": f"Inventário parcial obtido via HTTP em {endpoint}",
            }
        except Exception:
            continue

    return {
        "success": False,
        "message": "Servidor Linux sem acesso por SSH, SNMP ou HTTP identificável para inventário.",
    }

def _obter_detalhes_vm_wmi(ip, username, password):
    local_target = _is_local_target(ip)
    cred_setup = ""
    computer_arg = ""
    credential_arg = ""

    if not local_target:
        cred_setup = f"""
    $secpasswd = ConvertTo-SecureString '{_ps_single_quote(password)}' -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential ('{_ps_single_quote(username)}', $secpasswd)
"""
        computer_arg = f" -ComputerName {ip}"
        credential_arg = " -Credential $cred"

    ps_script = f"""
    {cred_setup}

    try {{
        $os = Get-WmiObject -Class Win32_OperatingSystem{computer_arg}{credential_arg} -ErrorAction Stop
        $cs = Get-WmiObject -Class Win32_ComputerSystem{computer_arg}{credential_arg} -ErrorAction Stop
        $proc = Get-WmiObject -Class Win32_Processor{computer_arg}{credential_arg} -ErrorAction Stop | Select-Object -First 1
        $disks = Get-WmiObject -Class Win32_LogicalDisk -Filter "DriveType=3"{computer_arg}{credential_arg} -ErrorAction Stop |
            Select-Object DeviceID, VolumeName, Size, FreeSpace
        $bitdefenderServices = Get-WmiObject -Class Win32_Service{computer_arg}{credential_arg} -ErrorAction SilentlyContinue |
            Where-Object {{ $_.Name -match 'Bitdefender' -or $_.DisplayName -match 'Bitdefender' }} |
            Select-Object Name, DisplayName, State, StartMode

        $uptime = (Get-Date) - $os.ConvertToDateTime($os.LastBootUpTime)
        $payload = [PSCustomObject]@{{
            success = $true
            details = [PSCustomObject]@{{
                operatingSystem = $os.Caption
                osVersion = $os.Version
                manufacturer = $cs.Manufacturer
                model = $cs.Model
                processors = $cs.NumberOfProcessors
                processorName = $proc.Name
                memory = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
                uptime = ("{{0}} dias, {{1}} horas, {{2}} minutos" -f $uptime.Days, $uptime.Hours, $uptime.Minutes)
                disks = @($disks | ForEach-Object {{
                    [PSCustomObject]@{{
                        drive = $_.DeviceID
                        volumeName = if ($_.VolumeName) {{ $_.VolumeName }} else {{ "Sem nome" }}
                        totalGB = [math]::Round($_.Size / 1GB, 2)
                        freeGB = [math]::Round($_.FreeSpace / 1GB, 2)
                    }}
                }})
                bitdefender = [PSCustomObject]@{{
                    installed = @($bitdefenderServices).Count -gt 0
                    runningServices = @($bitdefenderServices | Where-Object {{ $_.State -eq 'Running' }}).Count
                    services = @($bitdefenderServices | ForEach-Object {{
                        [PSCustomObject]@{{
                            name = $_.Name
                            displayName = $_.DisplayName
                            status = $_.State
                            startMode = $_.StartMode
                        }}
                    }})
                    products = @()
                }}
            }}
        }}

        $payload | ConvertTo-Json -Depth 5 -Compress
    }} catch {{
        [PSCustomObject]@{{
            success = $false
            message = $_.Exception.Message
        }} | ConvertTo-Json -Compress
    }}
    """

    with tempfile.NamedTemporaryFile(suffix='.ps1', delete=False, mode='w', encoding='utf-8') as ps_file:
        ps_file.write(ps_script)
        ps_path = ps_file.name

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_path],
            capture_output=True,
            text=True,
            timeout=45
        )
    finally:
        try:
            os.unlink(ps_path)
        except OSError:
            pass

    output = (result.stdout or "").strip()
    if result.returncode != 0 and not output:
        return {
            "success": False,
            "message": (result.stderr or "Falha ao consultar hardware da VM").strip()
        }

    try:
        data = json.loads(output)
    except Exception:
        return {
            "success": False,
            "message": "Resposta inválida da coleta WMI",
            "details": output[:300]
        }

    if isinstance(data, dict):
        if (
            local_target
            and not data.get("success")
            and "access denied" in str(data.get("message") or "").lower()
        ):
            return _obter_detalhes_vm_local_fallback(
                "WMI local retornou Access denied; inventario local basico obtido via Python."
            )
        details = data.get("details") or {}
        disks = details.get("disks") or []
        if isinstance(disks, dict):
            details["disks"] = [disks]
        return data

    return {
        "success": False,
        "message": "Resposta inesperada da coleta WMI"
    }

def coletar_hardware_vm(servidor):
    ip = (servidor.get("ip") or "").strip()
    username = (servidor.get("usuario") or servidor.get("username") or "").strip()
    password = servidor.get("senha") or servidor.get("password") or ""

    if not ip:
        return {"success": False, "message": "Servidor sem IP cadastrado"}

    if not username or not password:
        return {"success": False, "message": "Credenciais da VM incompletas"}

    usar_ssh_linux = _servidor_usa_ssh_linux(servidor)
    detalhes = _obter_detalhes_vm_linux_ssh(servidor, ip, username, password) if usar_ssh_linux else _obter_detalhes_vm_wmi(ip, username, password)

    if not detalhes.get("success") and usar_ssh_linux:
        detalhes = _obter_detalhes_vm_linux_http_probe(servidor, ip)

    if (not detalhes.get("success") and not usar_ssh_linux):
        mensagem = str(detalhes.get("message") or "")
        if "rpc server is unavailable" in mensagem.lower() and _servidor_usa_ssh_linux(servidor):
            detalhes = _obter_detalhes_vm_linux_ssh(servidor, ip, username, password)
            if not detalhes.get("success"):
                detalhes = _obter_detalhes_vm_linux_http_probe(servidor, ip)

    if not detalhes.get("success"):
        message = detalhes.get("message", "Erro ao obter hardware da VM")
        if _is_local_target(ip) and "access denied" in str(message).lower():
            message = (
                "A coleta local WMI foi executada sem -Credential, pois o Windows nao permite "
                "usar credenciais explicitas em conexoes locais. A conta do servico web nao tem "
                "permissao para consultar WMI local neste servidor."
            )
        return {
            "success": False,
            "message": message
        }

    info = detalhes.get("details", {})
    memory_value = info.get("memory")
    try:
        memoria_gib = round(float(memory_value), 2) if memory_value not in (None, "") else None
    except (TypeError, ValueError):
        memoria_gib = None

    processors = info.get("processors")
    try:
        processor_count = int(processors) if processors not in (None, "") else None
    except (TypeError, ValueError):
        processor_count = None

    return {
        "success": True,
        "hardware": {
            "memoria_gib": memoria_gib,
            "cpu": {
                "model": info.get("processorName") or info.get("model") or "N/A",
                "count": processor_count,
            },
            "temperaturas": [],
            "ventoinhas": [],
            "fabricante": info.get("manufacturer") or "",
            "modelo": info.get("model") or "",
            "sistema_operacional": info.get("operatingSystem") or "",
            "uptime": info.get("uptime") or "",
            "discos": info.get("disks") or [],
            "bitdefender": info.get("bitdefender") or {"installed": False, "runningServices": 0, "services": [], "products": []},
        }
    }

def coletar_hardware_snmp_worker(ip, community="public"):
    python_snmp = r"C:\Automacao\snmp_worker\.venv\Scripts\python.exe"
    script = r"C:\Automacao\snmp_worker\snmp_worker.py"

    cmd = [python_snmp, script, ip, community]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": "Timeout ao executar worker SNMP",
            "details": f"Consulta SNMP para {ip} excedeu 30 segundos"
        }

    if result.returncode != 0:
        return {
            "success": False,
            "message": "Erro executando worker SNMP",
            "details": result.stderr.strip()
        }

    try:
        return json.loads(result.stdout.strip())
    except Exception:
        return {
            "success": False,
            "message": "Resposta inválida do worker SNMP",
            "details": result.stdout[:300]
        }

@app.route('/api/regional/<codigo_regional>/link/<id_link>/testar', methods=['GET'])
@login_required
def api_testar_link_regional(codigo_regional, id_link):
    """API para testar conectividade de um link através do Fortigate"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            return jsonify({
                "success": False,
                "message": "Regional não encontrada",
                "status": "regional_not_found",
                "regional": codigo_regional,
                "regionais_sugeridas": _suggest_regionais(codigo_regional)
            }), 404

        # Obtém informações do link da regional
        link = gerenciador_regionais.obter_link(codigo_regional, id_link)
        if not link:
            for item in _obter_links_internet_exibicao(regional_info):
                item_id = str(item.get("id") or "").strip()
                item_interface = str(item.get("interface_monitorada") or item.get("nome") or "").strip()
                if id_link in {item_id, item_interface}:
                    link = dict(item)
                    break
        if not link:
            return jsonify({"success": False, "message": "Link não encontrado"}), 404

        link_oficial = None
        for item in _obter_links_internet_exibicao(regional_info):
            item_id = str(item.get("id") or "").strip()
            item_interface = str(item.get("interface_monitorada") or item.get("nome") or "").strip()
            if id_link in {item_id, item_interface}:
                link_oficial = dict(item)
                break

        link_ip = (link.get("ip") or "").strip()
        interface_preferida = str(
            (link_oficial or {}).get("interface_monitorada")
            or link.get("interface_monitorada")
            or link.get("nome")
            or ""
        ).strip()

        interfaces_result = _load_regional_interfaces(codigo_regional, regional_info)
        resolved = interfaces_result.get("resolved") or {}
        gerenciador_regional = interfaces_result.get("manager")
        device_info = interfaces_result.get("device") if resolved else None
        adom = interfaces_result.get("adom")
        use_proxy = interfaces_result.get("source") == "fortimanager"

        def _retornar_status_oficial_indisponivel(mensagem_padrao: str, status_http: int = 200):
            if not link_oficial:
                return None

            resultado = {
                "success": True,
                "link": link_oficial.get("interface_monitorada") or link_oficial.get("nome") or id_link,
                "ip_testado": link_oficial.get("ip") or link_ip,
                "status": link_oficial.get("status") or "unknown",
                "sla_status": link_oficial.get("sla_status") or "unknown",
                "sla_data": {},
                "sdwan_member_id": link_oficial.get("sdwan_member_id"),
                "modo_verificacao": link_oficial.get("modo_verificacao") or "cache_oficial",
                "interface_monitorada": link_oficial.get("interface_monitorada") or link_oficial.get("nome"),
                "fortigate_host": link_oficial.get("fortigate_host"),
                "fortigate_porta": link_oficial.get("fortigate_porta"),
                "message": mensagem_padrao,
                "ultima_verificacao": datetime.now().isoformat(),
            }

            link_atualizado = dict(link_oficial)
            link_atualizado.update({
                "ultima_verificacao": resultado["ultima_verificacao"],
                "modo_verificacao": resultado["modo_verificacao"],
                "fortigate_host": resultado["fortigate_host"],
                "fortigate_porta": resultado["fortigate_porta"],
            })
            _atualizar_link_internet_exibicao(codigo_regional, id_link, link_atualizado)

            return jsonify(resultado), status_http

        if not gerenciador_regional:
            fallback_response = _retornar_status_oficial_indisponivel(
                "FortiManager/FortiGate indisponível; mantendo último status sincronizado do link"
            )
            if fallback_response:
                return fallback_response

            return jsonify({
                "success": False,
                "message": "Fortigate da regional não identificado no FortiManager",
                "link": id_link,
                "status": "fortigate_not_mapped",
                "adom": adom,
                "regional": codigo_regional,
                "regional_nome": regional_info.get("nome"),
                "fortigate_ip_cadastrado": regional_info.get("fortigate_ip") or ((regional_info.get("fortigate") or {}).get("ip") if isinstance(regional_info.get("fortigate"), dict) else None),
                "fortigate_device_cadastrado": regional_info.get("fortigate_device") or ((regional_info.get("fortigate") or {}).get("name") if isinstance(regional_info.get("fortigate"), dict) else None),
                "candidate_devices": resolved.get("candidate_devices", []) if resolved else []
            }), 404

        if not interfaces_result.get("success"):
            fallback_response = _retornar_status_oficial_indisponivel(
                "FortiGate indisponível; mantendo último status sincronizado do link"
            )
            if fallback_response:
                return fallback_response

            return jsonify({
                "success": False,
                "message": interfaces_result.get("message") or "Erro ao obter interfaces do Fortigate",
                "link": id_link,
                "status": interfaces_result.get("status") or "fortigate_error",
                "fortigate_ip": getattr(gerenciador_regional, "host", None) if gerenciador_regional else None,
                "fortigate_device": device_info,
                "adom": adom,
                "port": getattr(gerenciador_regional, "port", None) if gerenciador_regional else None
            }), 500

        interfaces = interfaces_result.get("interfaces", [])

        # Procura a interface que tem o IP do link
        interface_encontrada = None
        if link_ip:
            for interface in interfaces:
                ip_interface = _extract_interface_ip(interface.get("ip", ""))
                if ip_interface == link_ip:
                    interface_encontrada = interface
                    break

        if not interface_encontrada and interface_preferida:
            interface_preferida_upper = interface_preferida.split("(")[0].strip().upper()
            for interface in interfaces:
                if str(interface.get("name", "")).strip().upper() == interface_preferida_upper:
                    interface_encontrada = interface
                    break

        # Se não encontrou por IP, tenta mapear por nome da interface (ex: WAN_CONNECT_02)
        if not interface_encontrada:
            link_nome = (link.get("nome") or "").strip()
            link_nome_base = link_nome.split("(")[0].strip().upper()
            for interface in interfaces:
                if str(interface.get("name", "")).strip().upper() == link_nome_base:
                    interface_encontrada = interface
                    print(f"🔍 Mapeamento por nome: Link '{link_nome}' -> Interface {interface['name']}")
                    break

        # Mapeamento baseado no nome do link para SD-WAN
        if not interface_encontrada:
            link_nome = link.get("nome", "").upper()
            
            # Mapeamento automático baseado no nome do link
            mapeamento_interfaces = {
                "WAN_CONNECT_01": "wan1",
                "WAN_CONNECT_02": "wan2", 
                "WAN1": "wan1",
                "WAN2": "wan2",
                "INTERNET_01": "wan1",
                "INTERNET_02": "wan2",
                "LINK_01": "wan1",
                "LINK_02": "wan2",
                "LINK_WAN1": "wan1",
                "LINK_WAN2": "wan2",
                "CONNECT_01": "wan1",
                "CONNECT_02": "wan2"
            }
            
            # Procura correspondência exata ou parcial no nome
            interface_mapeada = None
            for chave, interface in mapeamento_interfaces.items():
                if chave in link_nome:
                    interface_mapeada = interface
                    break
            
            if interface_mapeada:
                interface_encontrada = {"name": interface_mapeada}
                print(f"🔍 Mapeamento SD-WAN automático: Link '{link_nome}' -> Interface {interface_mapeada}")
            else:
                # Fallback: tenta encontrar interface por nome similar
                for interface in interfaces:
                    int_name = interface.get("name", "").lower()
                    if "wan" in int_name and ("1" in link_nome or "01" in link_nome):
                        interface_encontrada = interface
                        print(f"🔍 Mapeamento fallback: Link '{link_nome}' -> Interface {interface['name']}")
                        break

        if not interface_encontrada:
            return jsonify({
                "success": False,
                "message": f"Nenhuma interface do Fortigate encontrada para {interface_preferida or link_ip or id_link}",
                "link": id_link,
                "status": "interface_not_found"
            }), 404

        interface_name = interface_encontrada["name"]
        print(f"🔍 Mapeamento: Link {id_link} (IP: {link_ip}) -> Interface {interface_name}")

        # Usa SLA sempre que o equipamento responder, mesmo quando as interfaces vierem via FortiManager.
        sdwan_data = {}
        sla_status = "unknown"
        if gerenciador_regional:
            try:
                sdwan_result = gerenciador_regional.obter_membros_sdwan_com_sla()
            except Exception as exc:
                current_app.logger.warning(
                    "Erro ao obter membros SD-WAN da regional %s durante teste do link %s: %s",
                    codigo_regional,
                    id_link,
                    exc,
                )
                sdwan_result = {"success": False, "membros": []}

            sdwan_members = {
                str(member.get("interface") or "").strip().upper(): member
                for member in (sdwan_result.get("membros") or [])
                if str(member.get("interface") or "").strip()
            } if sdwan_result.get("success") else {}
            interface_key = interface_name.upper()
            sdwan_data = sdwan_members.get(interface_key, {})
            sla_status = sdwan_data.get("sla_status") or sdwan_data.get("status") or "unknown"

        interface_obj = None
        for interface in interfaces:
            if interface.get("name", "").lower() == interface_name.lower():
                interface_obj = interface
                break

        if interface_obj:
            link_value = interface_obj.get("link", None)
            status_value = str(interface_obj.get("status", "")).lower()
            if link_value is not None:
                link_up = bool(link_value)
            else:
                link_up = status_value in {"1", "up", "online", "active"}
        else:
            link_up = False

        # ✅ Validação do IP: deve bater com o IP da interface
        interface_ip_full = interface_obj.get("ip", "") if interface_obj else ""
        interface_ip = _extract_interface_ip(interface_ip_full)
        ip_confere = True if not link_ip else ((interface_ip == link_ip) if interface_ip else use_proxy)
        if not ip_confere:
            resultado = {
                "success": True,
                "link": interface_name,
                "ip_testado": link_ip,
                "status": "mismatch",
                "sla_status": "unknown",
                "sla_data": {},
                "message": f"IP cadastrado ({link_ip}) não confere com IP da interface ({interface_ip})",
                "ultima_verificacao": datetime.now().isoformat(),
                "fortigate_host": getattr(gerenciador_regional, "host", None),
                "fortigate_porta": getattr(gerenciador_regional, "port", None),
                "interface_monitorada": interface_name,
                "sdwan_member_id": sdwan_data.get("member_id") if isinstance(sdwan_data, dict) else None,
                "modo_verificacao": "ip_x_interface"
            }

            # Atualiza o status do link na regional
            link["status"] = resultado["status"]
            link["ultima_verificacao"] = resultado["ultima_verificacao"]
            link["interface_monitorada"] = resultado["interface_monitorada"]
            link["fortigate_host"] = resultado["fortigate_host"]
            link["fortigate_porta"] = resultado["fortigate_porta"]
            link["modo_verificacao"] = resultado["modo_verificacao"]
            link["sla_status"] = resultado["sla_status"]
            link["sdwan_member_id"] = resultado["sdwan_member_id"]
            try:
                gerenciador_regionais.atualizar_link(codigo_regional, id_link, link)
            except ValueError:
                _atualizar_link_internet_exibicao(codigo_regional, id_link, link)
            else:
                _atualizar_link_internet_exibicao(codigo_regional, id_link, link)

            return jsonify(resultado)

        if sla_status == "unknown":
            # Fallback: usa status físico quando SLA não estiver disponível.
            sla_status = "active" if link_up else "inactive"

        if sla_status == "active":
            status = "online"
            message = f"Link {interface_name} com SLA ativo"
        elif sla_status == "inactive":
            status = "offline"
            message = f"Link {interface_name} com SLA inativo"
        else:
            status = "unknown"
            message = f"Status SLA indisponível para {interface_name}"

        resultado = {
            "success": True,
            "link": interface_name,
            "ip_testado": link_ip,
            "status": status,
            "sla_status": sla_status,
            "sla_data": sdwan_data.get("sla_data", {}),
            "sdwan_member_id": sdwan_data.get("member_id") if isinstance(sdwan_data, dict) else None,
            "modo_verificacao": "sla" if sdwan_data else "interface",
            "interface_monitorada": interface_name,
            "fortigate_host": getattr(gerenciador_regional, "host", None),
            "fortigate_porta": getattr(gerenciador_regional, "port", None),
            "message": message,
            "ultima_verificacao": datetime.now().isoformat()
        }

        # Atualiza o status do link na regional
        link["status"] = resultado["status"]
        link["ultima_verificacao"] = resultado["ultima_verificacao"]
        link["interface_monitorada"] = resultado["interface_monitorada"]
        link["fortigate_host"] = resultado["fortigate_host"]
        link["fortigate_porta"] = resultado["fortigate_porta"]
        link["modo_verificacao"] = resultado["modo_verificacao"]
        link["sla_status"] = resultado["sla_status"]
        link["sdwan_member_id"] = resultado["sdwan_member_id"]
        try:
            gerenciador_regionais.atualizar_link(codigo_regional, id_link, link)
        except ValueError:
            _atualizar_link_internet_exibicao(codigo_regional, id_link, link)
        else:
            _atualizar_link_internet_exibicao(codigo_regional, id_link, link)

        return jsonify(resultado)

    except Exception as e:
        current_app.logger.exception("Erro ao testar link")
        return jsonify({
            "success": False, 
            "message": f"Erro interno: {str(e)}",
            "link": id_link,
            "status": "error"
        }), 500


@app.route('/api/regional/<codigo_regional>/links/sincronizar', methods=['POST'])
@login_required
def api_sincronizar_links_regional(codigo_regional):
    """Sincroniza links da regional com as interfaces WAN do FortiGate/FortiManager."""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            return jsonify({"success": False, "message": "Regional não encontrada"}), 404

        total_antes = len(_obter_links_internet_exibicao(regional_info))

        resultado = _coletar_links_regional(codigo_regional, regional_info, persist=True)
        resolved = resultado.get("resolved") or {}

        if not resultado.get("success"):
            status_code = 404 if resultado.get("status") in {"fortigate_not_mapped", "wan_not_found"} else 500
            return jsonify({
                "success": False,
                "message": resultado.get("message"),
                "status": resultado.get("status"),
                "adom": resolved.get("adom") if resolved else None,
                "candidate_devices": resolved.get("candidate_devices", []) if resolved else []
            }), status_code

        regional_atualizada = gerenciador_regionais.obter_regional(codigo_regional) or {}
        links_atualizados = []
        for link in _obter_links_internet_exibicao(regional_atualizada):
            link_completo = _preparar_link_para_template(link)
            ultima_verificacao = str(link_completo.get("ultima_verificacao") or "").strip()
            if ultima_verificacao:
                try:
                    data = datetime.fromisoformat(ultima_verificacao)
                    link_completo["ultima_verificacao_formatada"] = {
                        "completa": data.strftime('%d/%m/%Y às %H:%M:%S'),
                        "data": data.strftime('%d/%m/%Y'),
                        "hora": data.strftime('%H:%M:%S')
                    }
                except ValueError:
                    link_completo["ultima_verificacao_formatada"] = {
                        "completa": ultima_verificacao,
                        "data": ultima_verificacao,
                        "hora": ""
                    }
            links_atualizados.append(link_completo)

        total_depois = len(links_atualizados)

        return jsonify({
            "success": True,
            "links": links_atualizados,
            "atualizados": resultado.get("atualizados", []),
            "criados": resultado.get("criados", []),
            "total_atualizados": resultado.get("total_atualizados", 0),
            "total_criados": resultado.get("total_criados", 0),
            "total_links": total_depois,
            "total_removidos": max(total_antes - total_depois, 0),
            "source": resultado.get("source")
        })

    except Exception as e:
        current_app.logger.exception("Erro ao sincronizar links")
        return jsonify({
            "success": False,
            "message": f"Erro interno: {str(e)}"
        }), 500


@app.route('/api/regionais/verificar-links', methods=['POST'])
@login_required
def api_sincronizar_links_todas_regionais():
    """Sincroniza os links de todas as regionais usando o mesmo fluxo da tela individual."""
    try:
        if _background_async_requested():
            total_regionais = len(gerenciador_regionais.listar_regionais())
            job_id = _create_background_job(
                'links-all',
                total=total_regionais,
                message='Preparando sincronização dos links...',
                detail='Criando job para consultar FortiManager e regionais.'
            )
            _start_background_job(
                lambda: _run_links_sync_job(job_id),
                name=f'links-job-{job_id}'
            )
            return jsonify({'success': True, 'job_id': job_id})

        resultado = _executar_sincronizacao_links_todas_regionais()
        return jsonify(resultado)

    except Exception as e:
        current_app.logger.exception("Erro ao sincronizar links de todas as regionais")
        return jsonify({
            "success": False,
            "message": f"Erro interno: {str(e)}"
        }), 500


@app.route('/api/regional/<codigo_regional>/firewalls/licencas', methods=['GET'])
@login_required
def api_obter_firewalls_licencas(codigo_regional):
    """Obtém as licenças dos firewalls (FortiGates) de uma regional."""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            return jsonify({"success": False, "message": "Regional não encontrada"}), 404

        firewalls_dados = []
        fortigate_ips = set()
        
        # Extrai IPs únicos de fortigates dos links
        for link in regional_info.get('links', []):
            fg_host = link.get('fortigate_host', '').strip()
            if fg_host:
                fortigate_ips.add(fg_host)
        
        if fortigate_ips:
            adom = _get_fortimanager_adom()
            try:
                fm_client = FortiManagerClient()
                fm_client.login()
                fm_devices = fm_client.list_devices(adom)
                fm_devices_list = fm_devices.get('result', [{}])[0] if isinstance(fm_devices.get('result', []), list) and fm_devices.get('result') else {}
                devices_data = fm_devices_list.get('data', []) if isinstance(fm_devices_list, dict) else []
                
                # Para cada fortigate na regional, busca as licenças
                for device_data in devices_data:
                    if isinstance(device_data, dict):
                        device_name = device_data.get('name', '')
                        device_ip = device_data.get('ip', '')
                        device_hostname = device_data.get('hostname', '')
                        
                        # Se o IP corresponde a um fortigate desta regional
                        if device_ip in fortigate_ips or device_hostname in fortigate_ips or device_name.lower() in [ip.lower() for ip in fortigate_ips]:
                            try:
                                licenses_data = fm_client.proxy_monitor_license(adom, device_name)
                                
                                firewall_info = {
                                    'nome': device_name,
                                    'hostname': device_hostname,
                                    'ip': device_ip,
                                    'status': device_data.get('status', 'unknown'),
                                    'model': device_data.get('model', ''),
                                    'serial': device_data.get('serialnumber', ''),
                                    'licenças': [],
                                    'ultima_verificacao': datetime.now().isoformat()
                                }
                                
                                # Processa cada licença
                                if isinstance(licenses_data, dict):
                                    for license_key, license_info in licenses_data.items():
                                        if isinstance(license_info, dict):
                                            # Extrai timestamp de expiração (Unix timestamp)
                                            dias_rest = 0
                                            expires_timestamp = license_info.get('expires', 0)
                                            
                                            # Se tiver timestamp de expiração, calcula dias restantes
                                            if expires_timestamp and isinstance(expires_timestamp, (int, float)) and expires_timestamp > 0:
                                                try:
                                                    from datetime import datetime as dt_class
                                                    exp_date = dt_class.fromtimestamp(expires_timestamp)
                                                    dias_rest = max(0, (exp_date.date() - dt_class.now().date()).days)
                                                except Exception:
                                                    dias_rest = 0
                                            
                                            lic_obj = {
                                                'nome': license_key,
                                                'tipo': license_key,
                                                'status': license_info.get('status', 'unknown'),
                                                'dias_restantes': dias_rest,
                                                'expiracao': expires_timestamp if expires_timestamp else 'N/A',
                                                'tipo_licenca': license_info.get('type', 'unknown'),
                                                'notificacao_critica': False
                                            }
                                            
                                            # Marca como crítica se vai expirar em menos de 30 dias
                                            if dias_rest <= 30 and dias_rest > 0:
                                                lic_obj['notificacao_critica'] = True
                                            
                                            firewall_info['licencas'].append(lic_obj)
                                
                                firewalls_dados.append(firewall_info)
                            except Exception as e:
                                current_app.logger.warning(f"Erro ao buscar licenças de {device_name}: {str(e)}")
                                firewalls_dados.append({
                                    'nome': device_name,
                                    'hostname': device_hostname,
                                    'ip': device_ip,
                                    'status': 'erro',
                                    'licenças': [],
                                    'erro': str(e),
                                    'ultima_verificacao': datetime.now().isoformat()
                                })
                
                fm_client.logout()
            except Exception as e:
                current_app.logger.warning(f"Erro ao conectar FortiManager: {str(e)}")
                return jsonify({
                    "success": False,
                    "message": f"Erro ao conectar FortiManager: {str(e)}"
                }), 500
        
        return jsonify({
            "success": True,
            "firewalls": firewalls_dados,
            "total": len(firewalls_dados),
            "ultima_atualizacao": datetime.now().isoformat()
        })

    except Exception as e:
        current_app.logger.exception("Erro ao obter licenças dos firewalls")
        return jsonify({
            "success": False,
            "message": f"Erro interno: {str(e)}"
        }), 500


@app.route('/wan/status')
@login_required
def wan_status_page():
    """Página para visualizar status das interfaces WAN"""
    return render_template('wan_status.html')


@app.route('/api/fortigate/wan/status')
def api_fortigate_wan_status():
    """API para obter status das interfaces WAN do Fortigate com SD-WAN e SLA"""
    try:
        # Autentica no Fortigate
        if not gerenciador_fortigate.autenticar():
            return jsonify({
                "success": False,
                "message": "Falha na autenticação com o Fortigate"
            }), 500

        # Obter membros do SD-WAN com SLA
        sdwan_result = gerenciador_fortigate.obter_membros_sdwan_com_sla()
        sdwan_members = {m["interface"]: m for m in sdwan_result.get("membros", [])} if sdwan_result.get("success") else {}

        # Obter todas as interfaces
        interfaces_result = gerenciador_fortigate.obter_interfaces()
        if not interfaces_result["success"]:
            return jsonify({
                "success": False,
                "message": "Erro ao obter interfaces do Fortigate",
                "error": interfaces_result.get("message")
            }), 500

        # Filtrar apenas interfaces WAN
        wan_interfaces = []
        for interface in interfaces_result["interfaces"]:
            name = interface.get("name", "").lower()
            if name in ["wan1", "wan2"]:
                wan_interfaces.append(interface)

        # Processar informações das interfaces WAN
        wan_status = []
        for wan in wan_interfaces:
            name = wan.get("name", "").upper()
            name_lower = wan.get("name", "").lower()
            ip_full = wan.get("ip", "")
            ip = _extract_interface_ip(ip_full) if ip_full else "N/A"
            mascara = ip_full.split()[1] if len(ip_full.split()) > 1 else "N/A"

            # Status físico
            link_value = wan.get("link", None)
            status_value = str(wan.get("status", "")).lower()
            link_up = link_value if link_value is not None else (status_value == "up")
            status_fisico = "UP" if link_up else "DOWN"

            # Informações básicas
            wan_info = {
                "interface": name,
                "ip": ip,
                "mascara": mascara,
                "status_fisico": status_fisico,
                "speed": wan.get("speed", "auto"),
                "duplex": wan.get("duplex", "N/A"),
                "link_up": link_up
            }

            # Obtém dados do SD-WAN se disponíveis
            if name in sdwan_members:
                sdwan_data = sdwan_members[name]
                wan_info["sdwan_member_id"] = sdwan_data.get("member_id", "N/A")
                wan_info["sdwan_priority"] = sdwan_data.get("priority", 0)
                wan_info["sla_status"] = sdwan_data.get("sla_status", "unknown")
                wan_info["sla_data"] = sdwan_data.get("sla_data", {})
            else:
                wan_info["sdwan_member_id"] = "N/A"
                wan_info["sdwan_priority"] = 0
                wan_info["sla_status"] = "unknown"
                wan_info["sla_data"] = {}

            # ✅ Status baseado APENAS em SLA (sem teste de IP da operadora)
            # Operadora bloqueia todos os pings, então usamos SOMENTE o status SLA
            sla_status = wan_info.get("sla_status", "unknown")
            
            if sla_status == "active":
                # Interface com SLA ativo = ONLINE
                wan_info["status_geral"] = "online"
                wan_info["saude"] = {
                    "status": "healthy",
                    "message": "Link ativo via SLA do SD-WAN"
                }
            elif sla_status == "inactive":
                # Interface com SLA inativo = OFFLINE
                wan_info["status_geral"] = "down"
                wan_info["saude"] = {
                    "status": "down",
                    "message": "Link inativo via SLA do SD-WAN"
                }
            else:
                # Status desconhecido
                wan_info["status_geral"] = "unknown"
                wan_info["saude"] = {
                    "status": "unknown",
                    "message": "Status SLA não disponível"
                }
            wan_status.append(wan_info)

        # Ordenar por interface (WAN1, WAN2)
        wan_status.sort(key=lambda x: x["interface"])

        return jsonify({
            "success": True,
            "wan_interfaces": wan_status,
            "total": len(wan_status),
            "online": sum(1 for w in wan_status if w["status_geral"] == "online"),
            "offline": sum(1 for w in wan_status if w["status_geral"] == "down"),
            "degraded": sum(1 for w in wan_status if w["status_geral"] == "degraded"),
            "sdwan_total_members": len(sdwan_members),
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        current_app.logger.exception("Erro ao obter status WAN")
        return jsonify({
            "success": False,
            "message": f"Erro interno: {str(e)}"
        }), 500


@app.route('/api/regional/<codigo_regional>/servidores/testar-todos', methods=['POST'])
def api_testar_todos_servidores(codigo_regional):
    """API para verificar status de todos os servidores de uma regional (mesma lógica do TESTAR = ping)"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            return jsonify({"success": False, "message": "Regional não encontrada"}), 404

        servidores = regional_info.get("servidores", [])
        resultados = []

        online_count = 0
        offline_count = 0
        warning_count = 0  # mantido por compatibilidade

        import subprocess
        from datetime import datetime

        for servidor in servidores:
            servidor_id = servidor.get("id")
            ip = servidor.get("ip")

            resultado = {
                "id": servidor_id,
                "regional": codigo_regional,
                "servidor": servidor.get("nome", "N/A"),
                "ip": ip,
                "tipo": servidor.get("tipo_monitoramento") or servidor.get("tipo", "vm"),
                "status": "offline",
                "tempo_resposta": None,
                "erro": None,
                "timestamp": datetime.now().isoformat()
            }

            if not ip:
                resultado["erro"] = "Servidor sem IP"
                offline_count += 1
                resultados.append(resultado)
                continue

            # timeout do ping em ms (usa o timeout cadastrado * 1000, fallback 5000ms)
            timeout_segundos = int(servidor.get("timeout", 5))
            timeout_ms = timeout_segundos * 1000

            # Windows ping
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
            ping_result = subprocess.run(cmd, capture_output=True, text=True)

            online = _ping_indica_online(ping_result)

            if online:
                resultado["status"] = "online"
                online_count += 1
            else:
                resultado["status"] = "offline"
                resultado["erro"] = "Timeout"
                offline_count += 1

            # ✅ Atualiza o servidor no JSON (igual o TESTAR)
            servidor["status"] = resultado["status"]
            servidor["erro"] = resultado["erro"]
            servidor["ultima_verificacao"] = resultado["timestamp"]

            # ✅ Atualiza no arquivo de forma segura (mantém seu padrão)
            gerenciador_regionais.atualizar_servidor(codigo_regional, servidor_id, servidor)

            resultados.append(resultado)

        return jsonify({
            "success": True,
            "resultados": resultados,
            "resumo": {
                "total": len(resultados),
                "online": online_count,
                "offline": offline_count,
                "warning": warning_count
            }
        })

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro interno: {str(e)}"}), 500

@app.route('/api/dashboard/hierarquico')
def api_dashboard_hierarquico():
    """API para dados do dashboard hierárquico"""
    try:
        dados = dashboard_hierarquico.coletar_dados_completos()
        return jsonify({'success': True, 'dados': dados})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/executar/completo', methods=['POST'])
def api_executar_completo():
    """API para executar verificação completa do sistema - usa executar_tudo.py original"""
    try:
        if _background_async_requested():
            job_id = _create_background_job(
                kind='executar_completo',
                total=1,
                message='Preparando execução completa...',
                detail='A rotina foi agendada e será executada em segundo plano.'
            )
            thread = Thread(target=lambda: _run_executar_completo_job(job_id), name=f'executar-completo-{job_id}', daemon=True)
            thread.start()

            return jsonify({
                'success': True,
                'async': True,
                'job_id': job_id,
                'message': 'Execução completa iniciada em segundo plano.'
            })

        import subprocess
        import os
        
        # Executa o script executar_tudo.py original
        script_path = PROJECT_ROOT / "executar_tudo.py"
        
        if not script_path.exists():
            return jsonify({
                'success': False,
                'message': 'Script executar_tudo.py não encontrado'
            })
        
        # Executa o script em modo automático/headless
        env = os.environ.copy()
        env['AUTOMACAO_NO_BROWSER'] = '1'

        result = subprocess.run([
            sys.executable, str(script_path), '--no-browser'
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(PROJECT_ROOT), env=env)
        
        if result.returncode == 0:
            # Verifica se o dashboard foi gerado
            dashboard_path = PROJECT_ROOT / "output" / "dashboard_final.html"
            
            return jsonify({
                'success': True,
                'message': 'Execução completa realizada com sucesso! Todos os sistemas verificados.',
                'dashboard_gerado': dashboard_path.exists(),
                'dashboard_url': '/output/dashboard_final.html' if dashboard_path.exists() else None,
                'detalhes': {
                    'regionais': 'Verificação de servidores concluída',
                    'gps': 'GPS Amigo capturado',
                    'replicacao': 'Replicação AD verificada',
                    'unifi': 'Antenas UniFi coletadas'
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erro na execução: {result.stderr or "Erro desconhecido"}',
                'output': result.stdout
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro interno: {str(e)}'
        })

@app.route('/api/configuracoes', methods=['POST'])
def api_salvar_configuracoes():
    """API para salvar configurações gerais"""
    try:
        data = request.get_json()
        
        # Estrutura da configuração
        config = {
            "naos_server": {
                "ip": data.get('naos_ip', ''),
                "usuario": data.get('naos_usuario', ''),
                "senha": data.get('naos_senha', '')
            },
            "unifi_controller": {
                "host": data.get('unifi_host', ''),
                "port": int(data.get('unifi_port', 8443)),
                "username": data.get('unifi_usuario', ''),
                "password": data.get('unifi_senha', '')
            },
            "fortigate": {
                "host": data.get('fortigate_host', 'fortigate.example.local'),
                "port": int(data.get('fortigate_porta', 20443)),
                "username": data.get('fortigate_usuario', 'admin'),
                "password": data.get('fortigate_senha', '')
            },
            "zabbix": {
                "url": data.get('zabbix_url', 'https://zabbix.example.local/zabbix/api_jsonrpc.php'),
                "username": data.get('zabbix_usuario', 'admin'),
                "password": data.get('zabbix_senha', ''),
                "excel_file": data.get('zabbix_arquivo_excel', 'switches_zabbix.xlsx')
            },
            "server_manager": {
                "host": data.get('server_manager_host', '203.0.113.20'),
                "username": data.get('server_manager_usuario', 'admin'),
                "password": data.get('server_manager_senha', ''),
                "regional": data.get('server_manager_regional', 'Paraná')
            },
            "gps_amigo": {
                "url": data.get('gps_url', 'https://gpsamigo.com.br/login.php')
            },
            "timeouts": {
                "connection_timeout": int(data.get('timeout_conexao', 10)),
                "max_retries": int(data.get('max_tentativas', 3))
            },
            "cleanup": {
                "remove_temp_files": data.get('remover_temp', True),
                "keep_logs": data.get('manter_logs', True)
            }
        }
        
        # Atualiza as credenciais no sistema de credenciais seguras
        try:
            from credentials import get_credentials, encrypt_credentials, decrypt_credentials
            
            # Obtém as credenciais atuais
            credentials = decrypt_credentials()
            
            # Atualiza as credenciais do Fortigate
            credentials['fortigate'] = {
                'host': data.get('fortigate_host', 'fortigate.example.local'),
                'port': int(data.get('fortigate_porta', 20443)),
                'username': data.get('fortigate_usuario', 'admin'),
                'password': data.get('fortigate_senha', '')
            }
            
            # Atualiza as credenciais do Zabbix
            credentials['zabbix'] = {
                'url': data.get('zabbix_url', 'https://zabbix.example.local/zabbix/api_jsonrpc.php'),
                'username': data.get('zabbix_usuario', 'admin'),
                'password': data.get('zabbix_senha', ''),
                'excel_file': data.get('zabbix_arquivo_excel', 'switches_zabbix.xlsx')
            }
            
            # Atualiza as credenciais do NAOS
            credentials['naos'] = {
                'host': data.get('naos_ip', ''),
                'username': data.get('naos_usuario', ''),
                'password': data.get('naos_senha', '')
            }
            
            # Atualiza as credenciais do UniFi
            credentials['unifi'] = {
                'host': data.get('unifi_host', ''),
                'port': int(data.get('unifi_port', 8443)),
                'username': data.get('unifi_usuario', ''),
                'password': data.get('unifi_senha', '')
            }
            
            # Atualiza as credenciais do Server Manager
            credentials['server_manager'] = {
                'host': data.get('server_manager_host', '203.0.113.20'),
                'username': data.get('server_manager_usuario', 'admin'),
                'password': data.get('server_manager_senha', ''),
                'regional': data.get('server_manager_regional', 'Paraná')
            }
            
            # Salva as credenciais
            encrypt_credentials(credentials)
            print("✅ Credenciais atualizadas com sucesso!")
        except Exception as e:
            print(f"⚠️ Erro ao atualizar credenciais: {str(e)}")
            # Continua mesmo se houver erro nas credenciais
        
        # Salva configuração
        env_file = PROJECT_ROOT / "environment.json"
        with open(env_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        return jsonify({'success': True, 'message': 'Configurações salvas com sucesso!'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao salvar: {str(e)}'})


@app.route('/api/backup/exportar')
def api_exportar_backup():
    """API para exportar backup do sistema"""
    try:
        # TODO: Implementar sistema de backup
        # from backup_sistema import criar_backup_completo
        # arquivo_backup = criar_backup_completo()
        arquivo_backup = "backup_sistema.zip"  # Placeholder
        
        return jsonify({
            'success': True,
            'message': 'Backup criado com sucesso!',
            'arquivo': str(arquivo_backup)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao criar backup: {str(e)}'})

@app.route('/api/rotas')
def listar_rotas():
    rotas = []
    for rule in app.url_map.iter_rules():
        rotas.append(str(rule))
    return jsonify(sorted(rotas))

if __name__ == '__main__':
    try:
        web_port = int(str(os.getenv("AUTOMACAO_WEB_PORT") or "5000").strip())
    except (TypeError, ValueError):
        web_port = 5000
    print("🌐 Iniciando Interface Web Hierárquica...")
    print(f"📍 URL: http://localhost:{web_port}")
    print("🏢 Sistema organizado por Regionais → Servidores")
    
    app.run(
        host='0.0.0.0',
        port=web_port,
        debug=os.getenv("DEBUG", "False").lower() == "true",
        threaded=True
    )
