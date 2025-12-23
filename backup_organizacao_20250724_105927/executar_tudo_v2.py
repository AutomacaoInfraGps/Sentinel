"""
Executar Tudo - Versão 2.0 com Estrutura Hierárquica
Integra todos os sistemas com a nova estrutura Regional → Servidores
"""

import subprocess
from pathlib import Path
import webbrowser
import os
import re
from datetime import datetime
import sys
import json

# Configuração para Windows - força UTF-8
if sys.platform == "win32":
    import codecs
    import locale
    
    # Tenta configurar UTF-8
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except:
        pass

# Função para print seguro
def safe_print(message):
    """Print seguro que funciona no Windows"""
    try:
        print(message)
    except UnicodeEncodeError:
        import re
        clean_message = re.sub(r'[^\x00-\x7F]+', '[EMOJI]', message)
        print(clean_message)

# Importa as configurações dinâmicas
from config import (
    CONEXOES_FILE, REGIONAL_HTMLS_DIR, GPS_HTML, REPLICACAO_HTML, 
    UNIFI_HTML, DASHBOARD_FINAL, ensure_directories, get_regional_html_path,
    validate_config, PROJECT_ROOT
)

# Importa os novos módulos hierárquicos
from gerenciar_regionais import GerenciadorRegionais
from verificar_servidores_v2 import VerificadorServidoresV2
from dashboard_hierarquico import DashboardHierarquico

# === VALIDAÇÃO E INICIALIZAÇÃO ===
config_errors = validate_config()
if config_errors:
    print("[ERRO] Erros de configuração encontrados:")
    for error in config_errors:
        print(f"   - {error}")
    sys.exit(1)

ensure_directories()

class ExecutorCompleto:
    """Executor completo com estrutura hierárquica"""
    
    def __init__(self):
        self.gerenciador = GerenciadorRegionais()
        self.verificador = VerificadorServidoresV2()
        self.dashboard = DashboardHierarquico()
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)
        
    def executar_verificacao_completa(self):
        """Executa verificação completa de todas as regionais"""
        
        safe_print("🚀 Iniciando verificação completa...")
        safe_print("=" * 60)
        
        # 1. Verifica estrutura de regionais
        safe_print("\n📋 1. Verificando estrutura de regionais...")
        regionais = self.gerenciador.listar_regionais()
        total_servidores = len(self.gerenciador.listar_todos_servidores())
        
        safe_print(f"   Regionais encontradas: {len(regionais)}")
        safe_print(f"   Total de servidores: {total_servidores}")
        
        for regional in regionais:
            info = self.gerenciador.obter_regional(regional)
            servidores_count = len(info.get("servidores", []))
            safe_print(f"   - {info.get('nome', regional)}: {servidores_count} servidores")
        
        # 2. Executa verificação de conectividade
        safe_print("\n🔍 2. Verificando conectividade dos servidores...")
        resultados = self.verificador.verificar_todas_regionais()
        
        # 3. Gera relatórios
        safe_print("\n📊 3. Gerando relatórios...")
        relatorio = self.verificador.gerar_relatorio_detalhado()
        
        # Salva relatório
        arquivo_relatorio = self.output_dir / f"relatorio_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(arquivo_relatorio, 'w', encoding='utf-8') as f:
            f.write(relatorio)
        
        safe_print(f"   Relatório salvo: {arquivo_relatorio}")
        
        # 4. Gera dashboards
        safe_print("\n🌐 4. Gerando dashboards hierárquicos...")
        dashboard_principal = self.dashboard.gerar_todos_dashboards()
        
        # 5. Executa scripts legados (se necessário)
        safe_print("\n⚙️ 5. Executando verificações complementares...")
        self.executar_scripts_complementares()
        
        # 6. Gera dashboard final integrado
        safe_print("\n🎯 6. Gerando dashboard final integrado...")
        dashboard_final = self.gerar_dashboard_final_integrado()
        
        safe_print("\n✅ Verificação completa finalizada!")
        safe_print(f"📊 Dashboard principal: {dashboard_principal}")
        safe_print(f"🎯 Dashboard final: {dashboard_final}")
        
        return dashboard_final
    
    def executar_scripts_complementares(self):
        """Executa scripts complementares (GPS, Replicação, etc.)"""
        
        scripts_complementares = [
            ("Chelist.py", "Verificação de checklist"),
            ("get_replicacao_path.py", "Verificação de replicação"),
            ("Unifi.Py", "Verificação UniFi")
        ]
        
        for script, descricao in scripts_complementares:
            script_path = Path(script)
            if script_path.exists():
                try:
                    safe_print(f"   Executando: {descricao}...")
                    subprocess.run([sys.executable, script], 
                                 capture_output=True, 
                                 timeout=60,
                                 cwd=PROJECT_ROOT)
                    safe_print(f"   ✅ {descricao} concluído")
                except subprocess.TimeoutExpired:
                    safe_print(f"   ⏰ {descricao} - timeout")
                except Exception as e:
                    safe_print(f"   ❌ {descricao} - erro: {e}")
            else:
                safe_print(f"   ⚠️ {script} não encontrado")
    
    def gerar_dashboard_final_integrado(self):
        """Gera dashboard final que integra tudo"""
        
        # Coleta dados de todas as fontes
        dados_regionais = self.dashboard.coletar_dados_completos()
        
        # Verifica se existem outros HTMLs gerados
        htmls_complementares = []
        
        for html_file in [GPS_HTML, REPLICACAO_HTML, UNIFI_HTML]:
            if html_file.exists():
                htmls_complementares.append({
                    "nome": html_file.stem.replace("_", " ").title(),
                    "arquivo": html_file.name,
                    "caminho": html_file
                })
        
        # Gera HTML integrado
        html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Integrado - Sistema Completo</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            text-align: center;
        }}
        
        .header h1 {{
            color: #2c3e50;
            font-size: 3em;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .stats-overview {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
        }}
        
        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 10px;
        }}
        
        .stat-label {{
            color: #7f8c8d;
            font-size: 1em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .stat-online {{ color: #27ae60; }}
        .stat-offline {{ color: #e74c3c; }}
        .stat-warning {{ color: #f39c12; }}
        .stat-total {{ color: #3498db; }}
        
        .dashboards-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 25px;
            margin-bottom: 30px;
        }}
        
        .dashboard-card {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease;
        }}
        
        .dashboard-card:hover {{
            transform: translateY(-5px);
        }}
        
        .dashboard-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }}
        
        .dashboard-content {{
            padding: 20px;
        }}
        
        .dashboard-link {{
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-decoration: none;
            padding: 12px 24px;
            border-radius: 25px;
            font-weight: bold;
            transition: transform 0.3s ease;
        }}
        
        .dashboard-link:hover {{
            transform: scale(1.05);
        }}
        
        .regionais-summary {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }}
        
        .regional-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            margin-bottom: 10px;
            background: #f8f9fa;
            border-radius: 10px;
            border-left: 4px solid #3498db;
        }}
        
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            color: white;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Dashboard Integrado</h1>
            <p>Sistema Completo de Monitoramento - Regional → Servidores</p>
            <p>Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
        </div>
        
        <div class="stats-overview">
            <div class="stat-card">
                <div class="stat-number stat-total">{dados_regionais['estatisticas_gerais']['total_regionais']}</div>
                <div class="stat-label">Regionais</div>
            </div>
            <div class="stat-card">
                <div class="stat-number stat-total">{dados_regionais['estatisticas_gerais']['total_servidores']}</div>
                <div class="stat-label">Servidores</div>
            </div>
            <div class="stat-card">
                <div class="stat-number stat-online">{dados_regionais['estatisticas_gerais']['servidores_online']}</div>
                <div class="stat-label">Online</div>
            </div>
            <div class="stat-card">
                <div class="stat-number stat-offline">{dados_regionais['estatisticas_gerais']['servidores_offline']}</div>
                <div class="stat-label">Offline</div>
            </div>
        </div>
        
        <div class="dashboards-grid">
            <div class="dashboard-card">
                <div class="dashboard-header">
                    <h3>🏢 Dashboard Hierárquico</h3>
                </div>
                <div class="dashboard-content">
                    <p>Visão completa das regionais e servidores organizados hierarquicamente.</p>
                    <br>
                    <a href="dashboard_hierarquico.html" class="dashboard-link">Abrir Dashboard</a>
                </div>
            </div>
"""
        
        # Adiciona cards para dashboards complementares
        for html_comp in htmls_complementares:
            html += f"""
            <div class="dashboard-card">
                <div class="dashboard-header">
                    <h3>📊 {html_comp['nome']}</h3>
                </div>
                <div class="dashboard-content">
                    <p>Relatório específico de {html_comp['nome'].lower()}.</p>
                    <br>
                    <a href="{html_comp['arquivo']}" class="dashboard-link">Abrir Relatório</a>
                </div>
            </div>
"""
        
        html += """
        </div>
        
        <div class="regionais-summary">
            <h2>📍 Resumo das Regionais</h2>
            <br>
"""
        
        # Adiciona resumo das regionais
        for codigo_regional, regional_data in dados_regionais["regionais"].items():
            online_count = sum(1 for srv in regional_data["servidores"] if srv["status"] == "online")
            total_count = len(regional_data["servidores"])
            
            html += f"""
            <div class="regional-item">
                <div>
                    <strong>{regional_data['nome']}</strong>
                    <br>
                    <small>{regional_data['descricao']}</small>
                </div>
                <div>
                    <strong>{online_count}/{total_count}</strong> servidores online
                </div>
            </div>
"""
        
        html += f"""
        </div>
        
        <div class="footer">
            <p>🕐 Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
            <p>Sistema Integrado de Monitoramento - Versão 2.0</p>
        </div>
    </div>
    
    <script>
        // Auto-refresh a cada 10 minutos
        setTimeout(function() {{
            location.reload();
        }}, 600000);
    </script>
</body>
</html>
"""
        
        # Salva dashboard final
        dashboard_final = self.output_dir / "dashboard_final_integrado.html"
        with open(dashboard_final, 'w', encoding='utf-8') as f:
            f.write(html)
        
        return dashboard_final
    
    def abrir_dashboard_final(self):
        """Executa tudo e abre o dashboard final"""
        
        dashboard_final = self.executar_verificacao_completa()
        
        safe_print(f"\n🌐 Abrindo dashboard final: {dashboard_final}")
        webbrowser.open(dashboard_final.resolve().as_uri())
        
        return dashboard_final

def main():
    """Função principal"""
    
    executor = ExecutorCompleto()
    
    safe_print("🎯 Executor Completo - Versão 2.0")
    safe_print("Sistema Integrado com Estrutura Hierárquica")
    safe_print("=" * 60)
    
    while True:
        safe_print("\n📋 MENU PRINCIPAL:")
        safe_print("1. Executar verificação completa")
        safe_print("2. Apenas gerar dashboards")
        safe_print("3. Verificar estrutura de regionais")
        safe_print("4. Executar scripts complementares")
        safe_print("5. Abrir dashboard final")
        safe_print("0. Sair")
        
        opcao = input("\nEscolha uma opção: ")
        
        if opcao == "1":
            executor.abrir_dashboard_final()
        
        elif opcao == "2":
            safe_print("\n🌐 Gerando dashboards...")
            dashboard_principal = executor.dashboard.gerar_todos_dashboards()
            dashboard_final = executor.gerar_dashboard_final_integrado()
            safe_print(f"✅ Dashboard principal: {dashboard_principal}")
            safe_print(f"✅ Dashboard final: {dashboard_final}")
        
        elif opcao == "3":
            safe_print("\n📋 Estrutura de regionais:")
            regionais = executor.gerenciador.listar_regionais()
            for regional in regionais:
                info = executor.gerenciador.obter_regional(regional)
                servidores_count = len(info.get("servidores", []))
                safe_print(f"   🏢 {info.get('nome', regional)}: {servidores_count} servidores")
        
        elif opcao == "4":
            safe_print("\n⚙️ Executando scripts complementares...")
            executor.executar_scripts_complementares()
        
        elif opcao == "5":
            dashboard_final = executor.gerar_dashboard_final_integrado()
            safe_print(f"\n🌐 Abrindo: {dashboard_final}")
            webbrowser.open(dashboard_final.resolve().as_uri())
        
        elif opcao == "0":
            break
        
        else:
            safe_print("❌ Opção inválida")

if __name__ == "__main__":
    main()