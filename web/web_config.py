"""
Interface Web para Sistema de Automação - Versão Hierárquica
Sistema organizado por Regionais → Servidores
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, login_required, current_user

# Configuração do projeto
from config import PROJECT_ROOT
from data_store import load_data, is_data_fresh

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
        # Carrega regionais diretamente
        regionais = gerenciador_regionais.listar_regionais()
        
        # Estatísticas básicas
        total_servidores = 0
        regionais_resumo = []
        
        for codigo_regional in regionais:
            regional_info = gerenciador_regionais.obter_regional(codigo_regional)
            if regional_info:
                servidores = regional_info.get('servidores', [])
                total_servidores += len(servidores)
                
                regionais_resumo.append({
                    'codigo': codigo_regional,
                    'nome': regional_info.get('nome', codigo_regional),
                    'descricao': regional_info.get('descricao', ''),
                    'total_servidores': len(servidores),
                    'servidores_online': 0,  # Será atualizado via verificação
                    'servidores_offline': len(servidores),
                    'percentual_online': 0
                })
        
        stats = {
            'total_regionais': len(regionais),
            'total_servidores': total_servidores,
            'servidores_online': 0,
            'servidores_offline': total_servidores,
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

# === ROTAS DE INFRAESTRUTURA ===


@app.route('/replicacao')
@login_required
def replicacao_ad():
    """Página de replicação Active Directory"""
    return render_template('replicacao_ad.html')

@app.route('/antenas')
@login_required
def antenas_unifi():
    """Página de antenas UniFi"""
    return render_template('antenas_unifi.html')

@app.route('/relatorios-infra')
@login_required
def relatorios_infra():
    """Página de relatórios de infraestrutura"""
    return render_template('relatorios_infra.html')

@app.route('/api/replicacao/executar', methods=['POST'])
def executar_replicacao():
    """Executa verificação de replicação AD usando script original"""
    try:
        import subprocess
        
        # Executa o script PowerShell original
        script_path = PROJECT_ROOT / "Replicacao_Servers.ps1"
        
        if not script_path.exists():
            return jsonify({
                'success': False,
                'message': 'Script Replicacao_Servers.ps1 não encontrado'
            })
        
        # Executa o PowerShell
        result = subprocess.run([
            'powershell.exe', 
            '-ExecutionPolicy', 'Bypass',
            '-File', str(script_path)
        ], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        
        # Verifica se o arquivo HTML foi gerado
        html_path = PROJECT_ROOT / "output" / "replsummary.html"
        
        return jsonify({
            'success': result.returncode == 0,
            'message': 'Replicação AD verificada com sucesso' if result.returncode == 0 else 'Erro na verificação de replicação',
            'html_gerado': html_path.exists(),
            'html_url': '/output/replsummary.html' if html_path.exists() else None,
            'output': result.stdout,
            'errors': result.stderr if result.stderr else None
        })
            
    except Exception as e:
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
    """Retorna status real da replicação AD"""
    try:
        html_path = PROJECT_ROOT / "output" / "replsummary.html"
        
        if not html_path.exists():
            return jsonify({
                'status': 'sem_dados',
                'controladores': 0,
                'erros': 0,
                'ultima_verificacao': 'Nunca'
            })
        
        # Lê o arquivo HTML e extrai dados
        content = html_path.read_text(encoding='utf-8')
        
        # Conta controladores e erros
        import re
        
        # Busca por linhas da tabela
        table_rows = re.findall(r"<tr[^>]*>.*?<td[^>]*>([A-Z0-9\-]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>(\d+)</td>.*?</tr>", content, re.IGNORECASE | re.DOTALL)
        
        # Busca por erros operacionais
        replication_errors = re.findall(r"\d+\s*-\s*([A-Z0-9\.\-]+\.(?:[A-Z0-9\-]+\.)?local)", content, re.IGNORECASE)
        
        controladores = len(table_rows)
        erros_tabela = sum(1 for _, _, _, erros in table_rows if int(erros.strip()) > 0)
        erros_operacionais = len(replication_errors)
        total_erros = erros_tabela + erros_operacionais
        
        # Última modificação do arquivo
        import os
        from datetime import datetime
        ultima_mod = datetime.fromtimestamp(os.path.getmtime(html_path))
        
        return jsonify({
            'status': 'ok' if total_erros == 0 else 'erro',
            'controladores': controladores,
            'erros': total_erros,
            'ultima_verificacao': ultima_mod.strftime('%H:%M'),
            'detalhes': {
                'erros_tabela': erros_tabela,
                'erros_operacionais': erros_operacionais
            }
        })
        
    except Exception as e:
        return jsonify({
            'status': 'erro',
            'controladores': 0,
            'erros': 0,
            'ultima_verificacao': 'Erro',
            'erro': str(e)
        })

@app.route('/api/public/status/unifi')
def api_public_status_unifi():
    """Retorna status real das antenas UniFi"""
    try:
        # Tenta carregar dados do armazenamento centralizado
        unifi_data = load_data("unifi")
        
        if unifi_data:
            # Dados encontrados no armazenamento centralizado
            # Formata a resposta
            timestamp = datetime.fromisoformat(unifi_data.get('timestamp', datetime.now().isoformat()))
            
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
                'dados_atualizados': is_data_fresh('unifi')
            }
            
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
        debug=True,
        threaded=True
    )