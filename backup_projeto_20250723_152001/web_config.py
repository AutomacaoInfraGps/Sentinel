#!/usr/bin/env python3
"""
Interface Web para Configuração do Sistema
Servidor Flask com interface moderna e intuitiva
"""

import json
import os
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from gerenciar_servidores import GerenciadorServidores
from gerenciar_regionais import GerenciadorRegionais
from verificar_servidores_v2 import VerificadorServidoresV2
from dashboard_hierarquico import DashboardHierarquico
from config import PROJECT_ROOT, ENV_CONFIG
from auth_ad import verificar_usuario_ad, testar_conexao_ad
from user_model import User, get_user, save_user, remove_user

app = Flask(__name__)
app.secret_key = 'sistema_automacao_2024_secure_key_change_in_production'

# Configuração do Flask
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hora

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    """Carrega usuário para Flask-Login"""
    return get_user(user_id)

# Instâncias globais
gerenciador = GerenciadorServidores()
gerenciador_regionais = GerenciadorRegionais()
verificador_v2 = VerificadorServidoresV2()
dashboard_hierarquico = DashboardHierarquico()

# === ROTAS DE AUTENTICAÇÃO ===

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login"""
    # Se já está logado, redireciona para dashboard
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Usuário e senha são obrigatórios', 'error')
            return render_template('login.html')
        
        # Autentica no AD
        sucesso, user_data, mensagem = verificar_usuario_ad(username, password)
        
        if sucesso:
            # Cria usuário e faz login
            user = User(user_data)
            save_user(user)
            login_user(user, remember=True)
            
            flash(f'Bem-vindo, {user.display_name}!', 'success')
            
            # Redireciona para página solicitada ou dashboard
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash(mensagem, 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Logout do usuário"""
    username = current_user.username
    remove_user(current_user.get_id())
    logout_user()
    flash(f'Logout realizado com sucesso. Até logo, {username}!', 'info')
    return redirect(url_for('login'))

@app.route('/test-ad')
def test_ad():
    """Testa conexão com AD (apenas para debug)"""
    sucesso, mensagem = testar_conexao_ad()
    return jsonify({
        'success': sucesso,
        'message': mensagem
    })

# === ROTAS PRINCIPAIS ===

@app.route('/')
@login_required
def index():
    """Página principal - Dashboard hierárquico"""
    try:
        # Estatísticas da nova estrutura hierárquica
        dados_regionais = dashboard_hierarquico.coletar_dados_completos()
        
        # Estatísticas legadas para compatibilidade
        servidores_legado = gerenciador.listar_servidores(mostrar_inativos=True)
        
        stats = {
            'total_regionais': dados_regionais['estatisticas_gerais']['total_regionais'],
            'total_servidores': dados_regionais['estatisticas_gerais']['total_servidores'],
            'servidores_online': dados_regionais['estatisticas_gerais']['servidores_online'],
            'servidores_offline': dados_regionais['estatisticas_gerais']['servidores_offline'],
            'servidores_warning': dados_regionais['estatisticas_gerais']['servidores_warning'],
            'servidores_legado': len(servidores_legado),
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
        
        return render_template('index.html', stats=stats, regionais=regionais_resumo)
        
    except Exception as e:
        flash(f'Erro ao carregar dashboard: {str(e)}', 'error')
        # Fallback para estatísticas básicas
        servidores = gerenciador.listar_servidores(mostrar_inativos=True)
        stats = {
            'total_regionais': 0,
            'total_servidores': len(servidores),
            'servidores_configurados': len([s for s in servidores if s.get('ativo', True)]),
            'servidores_inativos': len([s for s in servidores if not s.get('ativo', True)]),
            'servidores_online': 0,
            'servidores_offline': 0,
            'config_completa': False,
            'estrutura_hierarquica': False
        }
        return render_template('index.html', stats=stats, regionais=[])

@app.route('/servidores')
@login_required
def listar_servidores():
    """Página de listagem de servidores"""
    try:
        servidores = gerenciador.listar_servidores(mostrar_inativos=True)
        return render_template('servidores.html', servidores=servidores)
    except Exception as e:
        flash(f'Erro ao carregar servidores: {str(e)}', 'error')
        return render_template('servidores.html', servidores=[])

@app.route('/servidor/novo')
@login_required
def novo_servidor():
    """Página para adicionar novo servidor"""
    return render_template('servidor_form.html', servidor=None, acao='Adicionar')

@app.route('/servidor/<servidor_id>/editar')
@login_required
def editar_servidor(servidor_id):
    """Página para editar servidor existente"""
    try:
        servidores = gerenciador.listar_servidores(mostrar_inativos=True)
        servidor = next((s for s in servidores if s['id'] == servidor_id), None)
        
        if not servidor:
            flash('Servidor não encontrado', 'error')
            return redirect(url_for('listar_servidores'))
        
        return render_template('servidor_form.html', servidor=servidor, acao='Editar')
        
    except Exception as e:
        flash(f'Erro ao carregar servidor: {str(e)}', 'error')
        return redirect(url_for('listar_servidores'))

@app.route('/api/servidor', methods=['POST'])
def api_salvar_servidor():
    """API para salvar servidor (novo ou editado)"""
    try:
        data = request.get_json()
        
        # Validação básica
        campos_obrigatorios = ['nome', 'tipo', 'ip', 'usuario', 'senha']
        for campo in campos_obrigatorios:
            if not data.get(campo):
                return jsonify({'success': False, 'message': f'Campo {campo} é obrigatório'})
        
        # Verifica se é edição ou novo
        servidor_id = data.get('id')
        
        if servidor_id:
            # Edição
            sucesso = gerenciador.editar_servidor(
                servidor_id,
                nome=data['nome'],
                tipo=data['tipo'],
                ip=data['ip'],
                usuario=data['usuario'],
                senha=data['senha'],
                grupo=data.get('grupo', 'regionais'),
                descricao=data.get('descricao', ''),
                porta=int(data.get('porta', 443)),
                timeout=int(data.get('timeout', 10)),
                ativo=data.get('ativo', True)
            )
            
            if sucesso:
                gerenciador.gerar_arquivo_conexoes_legado()
                return jsonify({'success': True, 'message': 'Servidor atualizado com sucesso!'})
            else:
                return jsonify({'success': False, 'message': 'Erro ao atualizar servidor'})
        else:
            # Novo servidor
            sucesso = gerenciador.adicionar_servidor(
                nome=data['nome'],
                tipo=data['tipo'],
                ip=data['ip'],
                usuario=data['usuario'],
                senha=data['senha'],
                grupo=data.get('grupo', 'regionais'),
                descricao=data.get('descricao', ''),
                porta=int(data.get('porta', 443)),
                timeout=int(data.get('timeout', 10)),
                ativo=data.get('ativo', True)
            )
            
            if sucesso:
                gerenciador.gerar_arquivo_conexoes_legado()
                return jsonify({'success': True, 'message': 'Servidor adicionado com sucesso!'})
            else:
                return jsonify({'success': False, 'message': 'Erro ao adicionar servidor'})
                
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/servidor/<servidor_id>', methods=['DELETE'])
def api_remover_servidor(servidor_id):
    """API para remover servidor"""
    try:
        sucesso = gerenciador.remover_servidor(servidor_id)
        
        if sucesso:
            gerenciador.gerar_arquivo_conexoes_legado()
            return jsonify({'success': True, 'message': 'Servidor removido com sucesso!'})
        else:
            return jsonify({'success': False, 'message': 'Servidor não encontrado'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/servidor/<servidor_id>/testar')
def api_testar_servidor(servidor_id):
    """API para testar conectividade de um servidor"""
    try:
        sucesso, mensagem = gerenciador.testar_conectividade(servidor_id)
        return jsonify({
            'success': sucesso,
            'message': mensagem,
            'status': 'online' if sucesso else 'offline'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/servidores/testar-todos')
def api_testar_todos_servidores():
    """API para testar conectividade de todos os servidores"""
    try:
        servidores = gerenciador.listar_servidores()
        resultados = []
        
        for servidor in servidores:
            sucesso, mensagem = gerenciador._testar_servidor_simples(servidor)
            resultados.append({
                'id': servidor['id'],
                'nome': servidor['nome'],
                'ip': servidor['ip'],
                'success': sucesso,
                'message': mensagem,
                'status': 'online' if sucesso else 'offline'
            })
        
        sucessos = len([r for r in resultados if r['success']])
        falhas = len(resultados) - sucessos
        
        return jsonify({
            'success': True,
            'resultados': resultados,
            'resumo': {
                'total': len(resultados),
                'sucessos': sucessos,
                'falhas': falhas
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/api/servidores/status-real')
def api_status_real_servidores():
    """API para obter status real de todos os servidores"""
    try:
        stats = gerenciador.obter_estatisticas_reais()
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

@app.route('/configuracoes')
@login_required
def configuracoes():
    """Página de configurações gerais"""
    try:
        # Carrega configuração atual
        env_file = PROJECT_ROOT / "environment.json"
        config_atual = {}
        
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                config_atual = json.load(f)
        
        return render_template('configuracoes.html', config=config_atual)
        
    except Exception as e:
        flash(f'Erro ao carregar configurações: {str(e)}', 'error')
        return render_template('configuracoes.html', config={})

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

# === ROTAS HIERÁRQUICAS ===

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

# === APIs HIERÁRQUICAS ===

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

@app.route('/executar/completo')
@login_required
def executar_completo():
    """Página para executar verificação completa"""
    return render_template('executar_completo.html')

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

@app.route('/backup')
@login_required
def backup():
    """Página de backup e restauração"""
    return render_template('backup.html')

@app.route('/api/backup/exportar')
def api_exportar_backup():
    """API para exportar backup"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        nome_arquivo = f"backup_sistema_{timestamp}.json"
        
        # Dados para backup
        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'versao': '2.0',
            'servidores': gerenciador.servidores,
            'configuracao': {}
        }
        
        # Adiciona configuração se existir
        env_file = PROJECT_ROOT / "environment.json"
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                backup_data['configuracao'] = json.load(f)
        
        return jsonify({
            'success': True,
            'data': backup_data,
            'filename': nome_arquivo
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao exportar: {str(e)}'})

@app.route('/api/backup/importar', methods=['POST'])
def api_importar_backup():
    """API para importar backup"""
    try:
        data = request.get_json()
        backup_data = data.get('backup_data')
        
        if not backup_data:
            return jsonify({'success': False, 'message': 'Dados de backup inválidos'})
        
        # Restaura servidores
        if 'servidores' in backup_data:
            gerenciador.servidores = backup_data['servidores']
            gerenciador._salvar_servidores()
            gerenciador.gerar_arquivo_conexoes_legado()
        
        # Restaura configuração
        if 'configuracao' in backup_data:
            env_file = PROJECT_ROOT / "environment.json"
            with open(env_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data['configuracao'], f, indent=2, ensure_ascii=False)
        
        return jsonify({'success': True, 'message': 'Backup restaurado com sucesso!'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao importar: {str(e)}'})

@app.route('/executar')
@login_required
def executar_sistema():
    """Página para executar o sistema"""
    return render_template('executar.html')

@app.route('/api/executar', methods=['POST'])
@login_required
def api_executar_sistema():
    """API para executar o sistema principal"""
    try:
        import subprocess
        import sys
        import os
        
        # Executa o script principal com codificação UTF-8
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        
        resultado = subprocess.run(
            [sys.executable, 'executar_tudo.py'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',  # Substitui caracteres problemáticos
            timeout=600,  # 10 minutos de timeout
            env=env
        )
        
        if resultado.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Sistema executado com sucesso!',
                'output': resultado.stdout
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Erro na execução',
                'error': resultado.stderr
            })
            
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'message': 'Timeout na execução (10 minutos)'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'})

def main():
    """Função principal"""
    print("🌐 Iniciando Interface Web de Configuração")
    print("=" * 50)
    print("📍 Acesse: http://localhost:5000")
    print("🔧 Para parar: Ctrl+C")
    print("=" * 50)
    
    # Cria diretório de templates se não existir
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    # Inicia servidor
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        use_reloader=False
    )

if __name__ == "__main__":
    main()