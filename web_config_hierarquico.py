"""
Interface Web para Sistema de Automação - Versão Hierárquica
Sistema organizado por Regionais → Servidores
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_required, current_user

# Configuração do projeto
from config import PROJECT_ROOT

# Módulos hierárquicos
from gerenciar_regionais import GerenciadorRegionais
from verificar_servidores_v2 import VerificadorServidoresV2
from dashboard_hierarquico import DashboardHierarquico

# Autenticação AD
from auth_ad import init_auth, get_user

# Configuração Flask
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

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

# === ROTAS PRINCIPAIS ===

@app.route('/')
@login_required
def index():
    """Página principal - Dashboard hierárquico"""
    try:
        # Estatísticas da estrutura hierárquica
        dados_regionais = dashboard_hierarquico.coletar_dados_completos()
        
        stats = {
            'total_regionais': dados_regionais['estatisticas_gerais']['total_regionais'],
            'total_servidores': dados_regionais['estatisticas_gerais']['total_servidores'],
            'servidores_online': dados_regionais['estatisticas_gerais']['servidores_online'],
            'servidores_offline': dados_regionais['estatisticas_gerais']['servidores_offline'],
            'servidores_warning': dados_regionais['estatisticas_gerais']['servidores_warning'],
            'config_completa': (PROJECT_ROOT / "environment.json").exists(),
            'estrutura_hierarquica': True
        }
        
        # Dados das regionais para exibição
        regionais_resumo = []
        for codigo, regional_data in dados_regionais['regionais'].items():
            online_count = sum(1 for srv in regional_data['servidores'] if srv['status'] == 'online')
            total_count = len(regional_data['servidores'])
            
            regionais_resumo.append({
                'codigo': codigo,
                'nome': regional_data['nome'],
                'descricao': regional_data['descricao'],
                'total_servidores': total_count,
                'servidores_online': online_count,
                'servidores_offline': total_count - online_count,
                'percentual_online': (online_count / total_count * 100) if total_count > 0 else 0
            })
        
        return render_template('index_hierarquico.html', stats=stats, regionais=regionais_resumo)
        
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
        return render_template('index_hierarquico.html', stats=stats, regionais=[])

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
        
        # Verifica status dos servidores da regional
        resultados_verificacao = verificador_v2.verificar_regional(codigo_regional)
        
        # Combina dados da regional com status
        servidores_completos = []
        for servidor in regional_info.get('servidores', []):
            # Busca resultado da verificação
            resultado = next((r for r in resultados_verificacao if r.get('ip') == servidor.get('ip')), None)
            
            servidor_completo = servidor.copy()
            if resultado:
                servidor_completo.update({
                    'status': resultado.get('status', 'unknown'),
                    'tempo_resposta': resultado.get('tempo_resposta'),
                    'erro': resultado.get('erro'),
                    'ultima_verificacao': resultado.get('timestamp')
                })
            else:
                servidor_completo.update({
                    'status': 'unknown',
                    'tempo_resposta': None,
                    'erro': 'Não verificado',
                    'ultima_verificacao': None
                })
            
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
        
        return render_template('servidor_regional_form.html', 
                             regional_codigo=codigo_regional,
                             regional_nome=regional_info.get('nome', codigo_regional),
                             servidor=None, 
                             acao='Adicionar')
        
    except Exception as e:
        flash(f'Erro: {str(e)}', 'error')
        return redirect(url_for('listar_regionais'))

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

# ====== APIs de VMs (compatíveis com sua UI) ======

from flask_login import login_required

def _listar_vms_agregadas():
    """Varre todas as regionais e agrega servidores como 'VMs' para a UI."""
    vms = []
    for codigo in gerenciador_regionais.listar_regionais():
        reg = gerenciador_regionais.obter_regional(codigo) or {}
        for s in reg.get("servidores", []):
            vms.append({
                "id": s.get("id") or f"{codigo}_{s.get('ip','semip')}",
                "name": s.get("nome") or s.get("ip") or "SemNome",
                "ipAddresses": [s.get("ip")] if s.get("ip") else [],
                "operatingSystem": s.get("so") or s.get("sistema") or "Desconhecido",
                "host_name": s.get("host") or s.get("modelo") or "-",
                "regional": reg.get("nome", codigo),
                "host_id": reg.get("codigo", codigo),
                "status": s.get("status", "unknown")
            })
    return vms

@app.route("/api/vms/listar")
@login_required
def api_vms_listar():
    """Usado pelo botão 'Atualizar' da tela de VMs."""
    try:
        vms = _listar_vms_agregadas()
        return jsonify(success=True, vms=vms, total=len(vms))
    except Exception as e:
        return jsonify(success=False, message=f"Erro ao listar VMs: {e}"), 500


@app.route("/api/vms/remover/<vm_id>", methods=["DELETE"])
@login_required
def api_vms_remover(vm_id):
    """
    Remove uma 'VM' (servidor) pelo id, procurando em todas as regionais.
    Tenta usar gerenciador_regionais.remover_servidor(...) se existir;
    caso contrário, remove manualmente da lista e tenta persistir.
    """
    try:
        # 1) Se o gerenciador expõe um método direto, use-o
        metodo_remover = getattr(gerenciador_regionais, "remover_servidor", None)
        if callable(metodo_remover):
            # se a assinatura for (codigo_regional, id) precisamos descobrir a regional
            for codigo in gerenciador_regionais.listar_regionais():
                reg = gerenciador_regionais.obter_regional(codigo) or {}
                if any(str(s.get("id")) == str(vm_id) for s in reg.get("servidores", [])):
                    metodo_remover(codigo, vm_id)
                    # tentar salvar se houver
                    for nome_salvar in ("salvar_dados", "salvar", "_salvar", "_salvar_dados"):
                        m = getattr(gerenciador_regionais, nome_salvar, None)
                        if callable(m):
                            try: m()
                            except Exception: pass
                    return jsonify(success=True, message="VM removida com sucesso.")

        # 2) Remoção manual se não existir método
        removido = False
        for codigo in gerenciador_regionais.listar_regionais():
            reg = gerenciador_regionais.obter_regional(codigo) or {}
            servidores = reg.get("servidores", [])
            novo = [s for s in servidores if str(s.get("id")) != str(vm_id)]
            if len(novo) != len(servidores):
                reg["servidores"] = novo
                # tentar persistir chamando métodos comuns
                persistiu = False
                for nome_salvar in ("salvar_dados", "salvar", "_salvar", "_salvar_dados"):
                    m = getattr(gerenciador_regionais, nome_salvar, None)
                    if callable(m):
                        try:
                            m()
                            persistiu = True
                            break
                        except Exception:
                            pass
                # fallback: deixa em memória; na próxima operação o gerenciador pode salvar
                removido = True
                break

        if not removido:
            return jsonify(success=False, message="VM/servidor não encontrado."), 404

        return jsonify(success=True, message="VM removida com sucesso.")
    except Exception as e:
        return jsonify(success=False, message=f"Erro ao remover VM: {e}"), 500


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
        
        if data.get('editando') and regional_existente:
            # Edição: preserva servidores e links, atualiza apenas nome e descrição
            gerenciador_regionais.editar_regional(codigo, nome, descricao)
        else:
            # Nova regional
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
        campos_obrigatorios = ['nome', 'tipo_monitoramento', 'ip', 'usuario', 'senha']
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
            'tipo': data['tipo_monitoramento'],
            'sistema_operacional': data.get('sistema_operacional', ''),
            'ip': data['ip'],
            'usuario': data['usuario'],
            'senha': data['senha'],
            'porta': int(data.get('porta', 443)),
            'timeout': int(data.get('timeout', 10)),
            'ativo': data.get('ativo', True),
            'modelo': data.get('modelo') or 'Servidor Virtual',
            'funcao': data.get('funcao', 'Aplicação')
        }

        servidor_existente = gerenciador_regionais.obter_servidor(codigo_regional, servidor['id']) if data.get('id') else None

        if servidor_existente:
            gerenciador_regionais.atualizar_servidor(codigo_regional, servidor['id'], servidor)
            return jsonify({'success': True, 'message': 'Servidor atualizado com sucesso!'})

        gerenciador_regionais.adicionar_servidor(codigo_regional, servidor)
        
        return jsonify({'success': True, 'message': 'Servidor adicionado com sucesso!'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/regional/<codigo_regional>/verificar')
def api_verificar_regional(codigo_regional):
    """API para verificar status de todos os servidores de uma regional"""
    try:
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
    """API para executar verificação completa do sistema"""
    try:
        from executar_tudo_v2 import ExecutorCompleto
        
        executor = ExecutorCompleto()
        dashboard_final = executor.executar_verificacao_completa()
        
        return jsonify({
            'success': True, 
            'message': 'Verificação completa executada com sucesso!',
            'dashboard_url': str(dashboard_final)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

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
        from backup_sistema import criar_backup_completo
        
        arquivo_backup = criar_backup_completo()
        
        return jsonify({
            'success': True,
            'message': 'Backup criado com sucesso!',
            'arquivo': str(arquivo_backup)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao criar backup: {str(e)}'})

if __name__ == '__main__':
    print("🌐 Iniciando Interface Web Hierárquica...")
    print("📍 URL: http://localhost:5000")
    print("🏢 Sistema organizado por Regionais → Servidores")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )