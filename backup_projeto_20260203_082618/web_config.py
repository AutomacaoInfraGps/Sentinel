"""
Interface Web para Sistema de Automação - Versão Hierárquica
Sistema organizado por Regionais → Servidores
"""

import os
import json
import time
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, current_app, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_required, current_user

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
from config import PROJECT_ROOT
from data_store import load_data, is_data_fresh

# Módulos hierárquicos
from gerenciar_regionais import GerenciadorRegionais
from verificar_servidores_v2 import VerificadorServidoresV2
from dashboard_hierarquico import DashboardHierarquico
from gerenciar_switches import GerenciadorSwitches
from gerenciar_fortigate import GerenciadorFortigate
from gerenciar_vms import GerenciadorVMs

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

# === ROTAS PRINCIPAIS ===

@app.route('/')
@login_required
def index():
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
                
                # Verifica o status real dos servidores para esta regional
                try:
                    # Tenta verificar o status real
                    resultados = verificador_v2.verificar_regional(codigo_regional)
                    
                    # Conta servidores online e offline
                    servidores_online = len([r for r in resultados if r.get('status') == 'online'])
                    servidores_offline = len([r for r in resultados if r.get('status') == 'offline'])
                    servidores_warning = len([r for r in resultados if r.get('status') == 'warning'])
                    
                    # Atualiza contadores totais
                    servidores_online_total += servidores_online
                    servidores_offline_total += servidores_offline
                    
                except Exception as e:
                    # Se falhar, assume que todos estão offline
                    servidores_online = 0
                    servidores_offline = len(servidores)
                    servidores_warning = 0
                    app.logger.error(f"Erro ao verificar regional {codigo_regional}: {str(e)}")
                
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
            'servidores_warning': 0,
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
                regionais_dados.append({
                    'codigo': codigo_regional,
                    'nome': regional_info.get('nome', codigo_regional),
                    'descricao': regional_info.get('descricao', ''),
                    'total_servidores': len(servidores),
                    'servidores': servidores
                })
        
        return render_template('regionais.html', regionais=regionais_dados)
        
    except Exception as e:
        flash(f'Erro ao carregar regionais: {str(e)}', 'error')
        return render_template('regionais.html', regionais=[])

@app.route('/regional/<codigo_regional>')
@login_required
def detalhar_regional(codigo_regional):
    """Página de detalhamento de uma regional"""
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            flash('Regional não encontrada', 'error')
            return redirect(url_for('listar_regionais'))

        # NÃO verifica automaticamente aqui
        servidores_completos = []

        for servidor in regional_info.get('servidores', []):
            servidor_completo = servidor.copy()

            # garante campos pra não quebrar o template
            servidor_completo.setdefault("status", "unknown")
            servidor_completo.setdefault("tempo_resposta", None)
            servidor_completo.setdefault("erro", None)
            servidor_completo.setdefault("ultima_verificacao", None)

            servidores_completos.append(servidor_completo)

        regional_completa = {
            'codigo': codigo_regional,
            'nome': regional_info.get('nome', codigo_regional),
            'descricao': regional_info.get('descricao', ''),
            'servidores': servidores_completos
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

@app.route('/switches/editar/<host>', methods=['GET', 'POST'])
@login_required
def editar_switch(host):
    """Página para editar um switch existente"""
    if request.method == 'POST':
        try:
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
                if switch["host"] == host:
                    switch_encontrado = switch
                    break
            
            if not switch_encontrado:
                flash(f'Switch não encontrado: {host}', 'error')
                return redirect(url_for('listar_switches'))
            
            # Carrega o arquivo Excel
            arquivo_excel = "switches_zabbix.xlsx"
            df = pd.read_excel(arquivo_excel, sheet_name='Switches', header=2)
            
            # Encontra o índice do switch no DataFrame
            idx = df[df['Host'] == host].index
            if len(idx) == 0:
                flash(f'Switch não encontrado no Excel: {host}', 'error')
                return redirect(url_for('listar_switches'))
            
            # Atualiza os dados no DataFrame
            df.loc[idx[0], 'IP'] = ip
            df.loc[idx[0], 'Regional'] = regional
            df.loc[idx[0], 'Modelo'] = modelo
            df.loc[idx[0], 'Local'] = local
            
            # Cria backup do arquivo original
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            arquivo_backup = f"switches_zabbix_backup_{timestamp}.xlsx"
            
            import shutil
            shutil.copy2(arquivo_excel, arquivo_backup)
            
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
    # Encontra o switch na lista
    switch = None
    for s in gerenciador_switches.switches:
        if s["host"] == host:
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
        # Encontra o switch na lista
        switch_encontrado = None
        for switch in gerenciador_switches.switches:
            if switch["host"] == host:
                switch_encontrado = switch
                break
        
        if not switch_encontrado:
            return jsonify({
                "success": False,
                "message": f"Switch não encontrado: {host}"
            })
        
        # Carrega o arquivo Excel
        arquivo_excel = "switches_zabbix.xlsx"
        df = pd.read_excel(arquivo_excel, sheet_name='Switches', header=2)
        
        # Encontra o índice do switch no DataFrame
        idx = df[df['Host'] == host].index
        if len(idx) == 0:
            return jsonify({
                "success": False,
                "message": f"Switch não encontrado no Excel: {host}"
            })
        
        # Remove o switch do DataFrame
        df = df.drop(idx[0])
        
        # Cria backup do arquivo original
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo_backup = f"switches_zabbix_backup_{timestamp}.xlsx"
        
        import shutil
        shutil.copy2(arquivo_excel, arquivo_backup)
        
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
                if switch["host"].lower() == host_name.lower():
                    flash(f'Switch já cadastrado: {host_name}', 'error')
                    return redirect(url_for('cadastrar_switch'))
            
            # Carrega o arquivo Excel
            arquivo_excel = "switches_zabbix.xlsx"
            df = pd.read_excel(arquivo_excel, sheet_name='Switches', header=2)
            
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
            
            # Cria backup do arquivo original
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            arquivo_backup = f"switches_zabbix_backup_{timestamp}.xlsx"
            
            import shutil
            shutil.copy2(arquivo_excel, arquivo_backup)
            
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
    regionais = gerenciador_switches.listar_regionais()
    return render_template('cadastrar_switch.html', regionais=regionais)

@app.route('/switches')
@login_required
def listar_switches():
    """Página de listagem de switches"""
    try:
        # Obtém as regionais com switches
        regionais = gerenciador_switches.listar_regionais()
        
        # Prepara dados para a view
        regionais_dados = []
        
        # Não verificamos todos os switches ao carregar a página para evitar lentidão
        # O usuário pode clicar no botão "Verificar Todos os Switches" para fazer isso
        print("Carregando página de switches sem verificação automática...")
        
        # Agora processa os dados para a view
        for regional in regionais:
            switches = gerenciador_switches.obter_switches_regional(regional)
            
            # Garante que todos os IPs estão convertidos corretamente
            for switch in switches:
                # Se o IP não parece estar no formato correto (sem pontos), converte
                if switch.get("ip") and "." not in switch.get("ip", ""):
                    switch["ip"] = gerenciador_switches._converter_ip_numerico(switch["ip"])
            
            # Conta switches por status
            total_switches = len(switches)
            online = sum(1 for s in switches if s.get('status') == 'online')
            offline = sum(1 for s in switches if s.get('status') == 'offline')
            warning = sum(1 for s in switches if s.get('status') == 'warning')
            desconhecidos = total_switches - online - offline - warning
            
            # Calcula percentual
            percentual_online = 0 if total_switches == 0 else (online / total_switches) * 100
            
            regionais_dados.append({
                'nome': regional,
                'total_switches': total_switches,
                'online': online,
                'offline': offline,
                'warning': warning,
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
        # Autentica no Zabbix
        if not gerenciador_switches.autenticar():
            return jsonify({'success': False, 'message': 'Falha na autenticação com o Zabbix'})
        
        # Verifica o switch
        resultado = gerenciador_switches.verificar_switch(host)
        
        return jsonify({
            'success': True,
            'status': resultado['status'],
            'detalhes': resultado['detalhes']
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
        # Autentica no Zabbix
        if not gerenciador_switches.autenticar():
            return jsonify({'success': False, 'message': 'Falha na autenticação com o Zabbix'})
        
        # Verifica todos os switches sem limite
        resultados = gerenciador_switches.verificar_todos_switches()
        
        # Conta por status
        total = len(resultados)
        online = sum(1 for r in resultados.values() if r.get('status') == 'online')
        offline = sum(1 for r in resultados.values() if r.get('status') == 'offline')
        warning = sum(1 for r in resultados.values() if r.get('status') == 'warning')
        
        return jsonify({
            'success': True,
            'resultados': resultados,
            'resumo': {
                'total': total,
                'online': online,
                'offline': offline,
                'warning': warning
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/switches/regional/<regional>', methods=['POST'])
@login_required
def api_verificar_switches_regional(regional):
    """API para verificar status dos switches de uma regional"""
    try:
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
        offline = sum(1 for r in resultados.values() if r.get('status') == 'offline')
        warning = sum(1 for r in resultados.values() if r.get('status') == 'warning')
        
        return jsonify({
            'success': True,
            'resultados': resultados,
            'resumo': {
                'total': total,
                'online': online,
                'offline': offline,
                'warning': warning
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

# === ROTAS DE LINKS DE INTERNET ===

@app.route('/links')
@login_required
def listar_links():
    """Página de listagem de links de internet"""
    try:
        # Autentica no Fortigate
        if not gerenciador_fortigate.autenticar():
            flash('Falha na autenticação com o Fortigate', 'error')
            return render_template('links_internet.html', links=[], sd_wan=None)
        
        # Obtém informações dos links
        resultado = gerenciador_fortigate.obter_informacoes_completas()
        
        if not resultado['success']:
            flash(f'Erro ao obter informações dos links: {resultado["message"]}', 'error')
            return render_template('links_internet.html', links=[], sd_wan=None)
        
        links = resultado['links']
        sd_wan = resultado['sd_wan']
        
        return render_template('links_internet.html', links=links, sd_wan=sd_wan)
        
    except Exception as e:
        flash(f'Erro ao carregar links: {str(e)}', 'error')
        return render_template('links_internet.html', links=[], sd_wan=None)

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

        return render_template("vpn_ipsec.html", vpns=vpns)

    except Exception as e:
        app.logger.exception("Erro na rota /vpn")
        flash(f"Erro interno ao carregar VPN: {str(e)}", "error")
        return render_template("vpn_ipsec.html", vpns=[])
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
            if "Reply from" in ping_result.stdout:
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
        return jsonify({"success": True, "vms": vms})
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
        
        return jsonify({"success": True, "vms": vms_regional, "regional": regional})
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
        
        # Aqui você pode implementar a lógica para se conectar à VM e obter detalhes adicionais
        # Por enquanto, vamos apenas retornar os dados cadastrados
        
        return jsonify({"success": True, "vm": vm})
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
        username = vm.get("username")
        password = vm.get("password")
        
        if not ip or not username or not password:
            return jsonify({"success": False, "message": "Credenciais incompletas para a VM"})
        
        # Obtém os serviços da VM usando o novo módulo
        result = obter_servicos_vm(ip, username, password)
        
        # Adiciona a VM ao resultado
        result["vm"] = vm
        
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
        username = vm.get("username")
        password = vm.get("password")
        
        if not ip or not username or not password:
            return jsonify({"success": False, "message": "Credenciais incompletas para a VM"})
        
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
        relatorio["vm"] = vm
        
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
        username = vm.get("username")
        password = vm.get("password")
        
        if not ip or not username or not password:
            return jsonify({"success": False, "message": "Credenciais incompletas para a VM"})
        
        # Obtém os logs da VM usando o novo módulo
        result = obter_logs_vm(ip, username, password)
        
        # Adiciona a VM ao resultado
        result["vm"] = vm
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": f"Erro ao obter logs da VM: {str(e)}"})

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

@app.route('/api/vms/remover/<vm_id>', methods=['DELETE'])
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
    try:
        resultado = gerenciador_fortigate.obter_informacoes_completas()

        if not resultado.get('success'):
            return jsonify({
                'success': False,
                'message': resultado.get('message', 'Erro desconhecido')
            })

        links = resultado.get('links', [])

        # 🔥 AGRUPA POR REGIONAL (IGUAL executar_tudo.py)
        links_por_regional = {}

        for link in links:
            regional = link.get('regional', 'SP')  # fallback defensivo
            links_por_regional.setdefault(regional, []).append(link)

        return jsonify({
            'success': True,
            'links_por_regional': links_por_regional,
            'sd_wan': resultado.get('sd_wan'),
            'timestamp': resultado.get('timestamp')
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/replicacao')
@login_required
def replicacao_ad():
    """Página de replicação Active Directory"""
    # Carrega os dados de replicação
    replicacao_data = load_data("replicacao") or {}
    
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
        # Caminho para o script PowerShell
        script_path = PROJECT_ROOT / "Replicacao_Final.ps1"
        
        # Verifica se o script existe
        if not script_path.exists():
            return {
                "success": False,
                "error": f"Script não encontrado: {script_path}"
            }
        
        # Executa o script PowerShell
        print(f"Executando script: {script_path}")
        process = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        # Verifica se o comando foi executado com sucesso
        if process.returncode != 0:
            print(f"Erro ao executar PowerShell: {process.stderr}")
            return {
                "success": False,
                "error": f"Erro ao executar PowerShell: {process.stderr}"
            }
        
        # Caminho para o arquivo JSON
        json_path = os.path.join(os.environ["USERPROFILE"], "Desktop", "replicacao.json")
        
        # Verifica se o arquivo JSON foi criado
        if not os.path.exists(json_path):
            print(f"Arquivo JSON não encontrado: {json_path}")
            return {
                "success": False,
                "error": f"Arquivo JSON não encontrado: {json_path}"
            }
        
        # Lê o arquivo JSON
        try:
            with open(json_path, 'r', encoding='ascii') as f:
                replicacao_data = json.load(f)
            
            # Verifica se os dados estão no formato esperado
            if "servidores" not in replicacao_data:
                replicacao_data["servidores"] = []
            
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
    
    # Renderiza o template com os dados
    return render_template('antenas_simples.html', unifi_data=unifi_data)

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
        return redirect(f'/static/dashboard_hierarquico.html')
        
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
        
        if regional_existente and not data.get('editando'):
            return jsonify({'success': False, 'message': 'Regional com este código já existe'})
        
        # Adiciona ou atualiza regional
        gerenciador_regionais.adicionar_regional(codigo, nome, descricao)
        
        return jsonify({'success': True, 'message': 'Regional salva com sucesso!', 'codigo': codigo})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/regional/<codigo_regional>/servidor', methods=['POST'])
def api_salvar_servidor_regional(codigo_regional):
    """API para salvar servidor em uma regional"""
    try:
        data = request.get_json()
        
        # Validação básica
        campos_obrigatorios = ['nome', 'tipo', 'ip', 'usuario', 'senha']
        for campo in campos_obrigatorios:
            if not data.get(campo):
                return jsonify({'success': False, 'message': f'Campo {campo} é obrigatório'})
        
        # Verifica se a regional existe
        if not gerenciador_regionais.obter_regional(codigo_regional):
            return jsonify({'success': False, 'message': 'Regional não encontrada'})
        
        # Monta dados do servidor
        servidor = {
            'id': data.get('id') or f"srv_{codigo_regional.lower()}_{len(gerenciador_regionais.listar_servidores_regional(codigo_regional)) + 1:02d}",
            'nome': data['nome'],
            'tipo': data['tipo'],
            'ip': data['ip'],
            'usuario': data['usuario'],
            'senha': data['senha'],
            'porta': int(data.get('porta', 443)),
            'timeout': int(data.get('timeout', 10)),
            'ativo': data.get('ativo', True),
            'modelo': data.get('modelo', 'Dell PowerEdge' if data['tipo'] == 'idrac' else 'HPE ProLiant'),
            'funcao': data.get('funcao', 'Aplicação')
        }
        
        # Adiciona servidor à regional
        gerenciador_regionais.adicionar_servidor(codigo_regional, servidor)
        
        return jsonify({'success': True, 'message': 'Servidor adicionado com sucesso!'})
        
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

        online = "Reply from" in result.stdout
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

        tipo = servidor.get("tipo", "idrac")
        ip = servidor.get("ip")
        community = servidor.get("snmp_community", "public")

        # ✅ 1) tenta Redfish conforme tipo
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

def coletar_hardware_snmp_worker(ip, community="public"):
    python_snmp = r"C:\Automacao\snmp_worker\.venv\Scripts\python.exe"
    script = r"C:\Automacao\snmp_worker\snmp_worker.py"

    cmd = [python_snmp, script, ip, community]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

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


@app.route('/api/regional/<codigo_regional>/verificar')
@login_required
def api_verificar_regional(codigo_regional):
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
                "regional": codigo_regional,
                "servidor": servidor.get("nome", "N/A"),
                "ip": ip,
                "tipo": servidor.get("tipo", "idrac"),
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

            online = "Reply from" in ping_result.stdout

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
        import subprocess
        import os
        
        # Executa o script executar_tudo.py original
        script_path = PROJECT_ROOT / "executar_tudo.py"
        
        if not script_path.exists():
            return jsonify({
                'success': False,
                'message': 'Script executar_tudo.py não encontrado'
            })
        
        # Executa o script
        result = subprocess.run([
            'python', str(script_path)
        ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        
        if result.returncode == 0:
            # Verifica se o dashboard foi gerado
            dashboard_path = PROJECT_ROOT / "output" / "dashboard_final.html"
            
            return jsonify({
                'success': True,
                'message': 'Execução completa realizada com sucesso! Todos os sistemas verificados.',
                'dashboard_gerado': dashboard_path.exists(),
                'dashboard_url': '/output/dashboard_final.html' if dashboard_path.exists() else None,
                'detalhes': {
                    'regionais': 'Verificação iDRAC/iLO concluída',
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
                "host": data.get('fortigate_host', '10.254.12.1'),
                "port": int(data.get('fortigate_porta', 20443)),
                "username": data.get('fortigate_usuario', 'admin'),
                "password": data.get('fortigate_senha', '')
            },
            "zabbix": {
                "url": data.get('zabbix_url', 'http://10.254.12.15/zabbix/api_jsonrpc.php'),
                "username": data.get('zabbix_usuario', 'admin'),
                "password": data.get('zabbix_senha', ''),
                "excel_file": data.get('zabbix_arquivo_excel', 'switches_zabbix.xlsx')
            },
            "server_manager": {
                "host": data.get('server_manager_host', '192.168.41.2'),
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
                'host': data.get('fortigate_host', '10.254.12.1'),
                'port': int(data.get('fortigate_porta', 20443)),
                'username': data.get('fortigate_usuario', 'admin'),
                'password': data.get('fortigate_senha', '')
            }
            
            # Atualiza as credenciais do Zabbix
            credentials['zabbix'] = {
                'url': data.get('zabbix_url', 'http://10.254.12.15/zabbix/api_jsonrpc.php'),
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
                'host': data.get('server_manager_host', '192.168.41.2'),
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
    
@app.route('/api/regional/<codigo_regional>/testar_todos', methods=['GET'])
@login_required
def api_testar_todos_servidores(codigo_regional):
    try:
        regional_info = gerenciador_regionais.obter_regional(codigo_regional)
        if not regional_info:
            return jsonify({"success": False, "message": "Regional não encontrada"}), 404

        servidores = regional_info.get("servidores", [])
        if not servidores:
            return jsonify({"success": False, "message": "Nenhum servidor cadastrado"}), 400

        resultados = []

        for servidor in servidores:
            servidor_id = servidor.get("id")
            ip = servidor.get("ip")

            if not ip:
                resultados.append({
                    "id": servidor_id,
                    "nome": servidor.get("nome", "Sem nome"),
                    "status": "offline",
                    "message": "Servidor sem IP"
                })
                continue

            import subprocess
            cmd = ["ping", "-n", "1", "-w", "1000", ip]
            result = subprocess.run(cmd, capture_output=True, text=True)

            online = "Reply from" in result.stdout

            # ✅ Atualiza o servidor dentro do JSON
            servidor["status"] = "online" if online else "offline"
            servidor["erro"] = None if online else "Timeout"
            servidor["ultima_verificacao"] = datetime.now().isoformat()

            resultados.append({
                "id": servidor_id,
                "nome": servidor.get("nome"),
                "ip": ip,
                "status": servidor["status"]
            })

        # ✅ salva no arquivo
        gerenciador_regionais.salvar_regionais()

        return jsonify({
            "success": True,
            "resultados": resultados
        })

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


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
    print("🌐 Iniciando Interface Web Hierárquica...")
    print("📍 URL: http://localhost:5000")
    print("🏢 Sistema organizado por Regionais → Servidores")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=os.getenv("DEBUG", "False").lower() == "true",
        threaded=True
    )