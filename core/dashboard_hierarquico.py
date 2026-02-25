"""
Dashboard Hierárquico - Regional → Servidores
Integra com a nova estrutura hierárquica
"""

import json
import os
from datetime import datetime
from pathlib import Path
import webbrowser
from gerenciar_regionais import GerenciadorRegionais
from verificar_servidores_v2 import VerificadorServidoresV2

class DashboardHierarquico:
    """Dashboard com estrutura hierárquica Regional → Servidores"""
    
    def __init__(self):
        self.gerenciador = GerenciadorRegionais()
        self.verificador = VerificadorServidoresV2()
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)
        
    def coletar_dados_completos(self):
        """Coleta dados completos de todas as regionais"""
        print("🔍 Coletando dados de todas as regionais...")
        
        # Verifica status de todos os servidores
        resultados_verificacao = self.verificador.verificar_todas_regionais()
        
        # Monta dados completos
        dados_completos = {
            "timestamp": datetime.now().isoformat(),
            "regionais": {},
            "estatisticas_gerais": {
                "total_regionais": 0,
                "total_servidores": 0,
                "servidores_online": 0,
                "servidores_offline": 0,
                "servidores_warning": 0
            }
        }
        
        # Processa cada regional
        for codigo_regional in self.gerenciador.listar_regionais():
            regional_info = self.gerenciador.obter_regional(codigo_regional)
            if not regional_info:
                continue
                
            # Dados da regional
            dados_regional = {
                "nome": regional_info.get("nome", codigo_regional),
                "descricao": regional_info.get("descricao", ""),
                "servidores": []
            }
            
            # Processa servidores da regional
            resultados_regional = resultados_verificacao.get(codigo_regional, [])
            
            for resultado in resultados_regional:
                # Busca dados completos do servidor
                servidor_info = None
                for srv in regional_info.get("servidores", []):
                    if srv.get("ip") == resultado.get("ip"):
                        servidor_info = srv
                        break
                
                if servidor_info:
                    dados_servidor = {
                        "id": servidor_info.get("id"),
                        "nome": servidor_info.get("nome"),
                        "ip": servidor_info.get("ip"),
                        "tipo": servidor_info.get("tipo"),
                        "modelo": servidor_info.get("modelo", "N/A"),
                        "funcao": servidor_info.get("funcao", "N/A"),
                        "status": resultado.get("status"),
                        "tempo_resposta": resultado.get("tempo_resposta"),
                        "erro": resultado.get("erro"),
                        "ultima_verificacao": resultado.get("timestamp")
                    }
                    
                    dados_regional["servidores"].append(dados_servidor)
                    
                    # Atualiza estatísticas
                    dados_completos["estatisticas_gerais"]["total_servidores"] += 1
                    if resultado.get("status") == "online":
                        dados_completos["estatisticas_gerais"]["servidores_online"] += 1
                    elif resultado.get("status") == "offline":
                        dados_completos["estatisticas_gerais"]["servidores_offline"] += 1
                    else:
                        dados_completos["estatisticas_gerais"]["servidores_warning"] += 1
            
            dados_completos["regionais"][codigo_regional] = dados_regional
            dados_completos["estatisticas_gerais"]["total_regionais"] += 1
        
        return dados_completos
    
    def gerar_dashboard_principal(self, dados):
        """Gera o dashboard principal hierárquico"""
        
        html = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Hierárquico - Regionais e Servidores</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            text-align: center;
        }
        
        .header h1 {
            color: #2c3e50;
            font-size: 2.5em;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .header .subtitle {
            color: #7f8c8d;
            font-size: 1.2em;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
        }
        
        .stat-number {
            font-size: 3em;
            font-weight: bold;
            margin-bottom: 10px;
        }
        
        .stat-label {
            color: #7f8c8d;
            font-size: 1.1em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .stat-online { color: #27ae60; }
        .stat-offline { color: #e74c3c; }
        .stat-warning { color: #f39c12; }
        .stat-total { color: #3498db; }
        
        .regionais-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 25px;
        }
        
        .regional-card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease;
        }
        
        .regional-card:hover {
            transform: translateY(-5px);
        }
        
        .regional-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }
        
        .regional-title {
            font-size: 1.4em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .regional-subtitle {
            opacity: 0.9;
            font-size: 0.9em;
        }
        
        .servidores-list {
            padding: 20px;
        }
        
        .servidor-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 15px;
            margin-bottom: 10px;
            background: #f8f9fa;
            border-radius: 10px;
            border-left: 4px solid #ddd;
            transition: all 0.3s ease;
        }
        
        .servidor-item:hover {
            background: #e9ecef;
            transform: translateX(5px);
        }
        
        .servidor-item.online {
            border-left-color: #27ae60;
            background: linear-gradient(90deg, rgba(39, 174, 96, 0.1) 0%, #f8f9fa 100%);
        }
        
        .servidor-item.offline {
            border-left-color: #e74c3c;
            background: linear-gradient(90deg, rgba(231, 76, 60, 0.1) 0%, #f8f9fa 100%);
        }
        
        .servidor-item.warning {
            border-left-color: #f39c12;
            background: linear-gradient(90deg, rgba(243, 156, 18, 0.1) 0%, #f8f9fa 100%);
        }
        
        .servidor-info {
            flex: 1;
        }
        
        .servidor-nome {
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 5px;
        }
        
        .servidor-detalhes {
            font-size: 0.9em;
            color: #7f8c8d;
        }
        
        .servidor-status {
            text-align: right;
        }
        
        .status-badge {
            display: inline-block;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .status-online {
            background: #27ae60;
            color: white;
        }
        
        .status-offline {
            background: #e74c3c;
            color: white;
        }
        
        .status-warning {
            background: #f39c12;
            color: white;
        }
        
        .tempo-resposta {
            font-size: 0.8em;
            color: #7f8c8d;
            margin-top: 5px;
        }
        
        .footer {
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            color: white;
        }
        
        .refresh-btn {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 50%;
            width: 60px;
            height: 60px;
            font-size: 1.5em;
            cursor: pointer;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease;
            transform: none;
        }
        
        .refresh-btn:hover {
            transform: scale(1.05);
        }
        
        @media (max-width: 768px) {
            .regionais-grid {
                grid-template-columns: 1fr;
            }
            
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .header h1 {
                font-size: 2em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏢 Dashboard Hierárquico</h1>
            <p class="subtitle">Monitoramento de Regionais e Servidores iDRAC/ILO</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number stat-total">""" + str(dados["estatisticas_gerais"]["total_regionais"]) + """</div>
                <div class="stat-label">Regionais</div>
            </div>
            <div class="stat-card">
                <div class="stat-number stat-total">""" + str(dados["estatisticas_gerais"]["total_servidores"]) + """</div>
                <div class="stat-label">Servidores</div>
            </div>
            <div class="stat-card">
                <div class="stat-number stat-online">""" + str(dados["estatisticas_gerais"]["servidores_online"]) + """</div>
                <div class="stat-label">Online</div>
            </div>
            <div class="stat-card">
                <div class="stat-number stat-offline">""" + str(dados["estatisticas_gerais"]["servidores_offline"]) + """</div>
                <div class="stat-label">Offline</div>
            </div>
        </div>
        
        <div class="regionais-grid">
"""
        
        # Gera cards das regionais
        for codigo_regional, regional_data in dados["regionais"].items():
            html += f"""
            <div class="regional-card">
                <div class="regional-header">
                    <div class="regional-title">{regional_data['nome']}</div>
                    <div class="regional-subtitle">{len(regional_data['servidores'])} servidores</div>
                </div>
                <div class="servidores-list">
"""
            
            # Gera lista de servidores
            for servidor in regional_data["servidores"]:
                status_class = servidor["status"]
                status_text = servidor["status"].upper()
                
                tempo_info = ""
                if servidor["tempo_resposta"]:
                    tempo_info = f'<div class="tempo-resposta">Resposta: {servidor["tempo_resposta"]}s</div>'
                
                erro_info = ""
                if servidor["erro"]:
                    erro_info = f' - {servidor["erro"]}'
                
                tipo_icon = "🔧" if servidor["tipo"] == "idrac" else "⚙️"
                
                html += f"""
                    <div class="servidor-item {status_class}">
                        <div class="servidor-info">
                            <div class="servidor-nome">{tipo_icon} {servidor['nome']}</div>
                            <div class="servidor-detalhes">
                                {servidor['ip']} • {servidor['modelo']} • {servidor['funcao']}{erro_info}
                            </div>
                        </div>
                        <div class="servidor-status">
                            <div class="status-badge status-{status_class}">{status_text}</div>
                            {tempo_info}
                        </div>
                    </div>
"""
            
            html += """
                </div>
            </div>
"""
        
        html += f"""
        </div>
        
        <div class="footer">
            <p>🕐 Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
            <p>Sistema de Monitoramento Hierárquico - Regional → Servidores</p>
        </div>
    </div>
    
    <button class="refresh-btn" onclick="location.reload()" title="Atualizar">
        Update
    </button>
    
    <script>
        // Auto-refresh a cada 5 minutos
        setTimeout(function() {{
            location.reload();
        }}, 300000);
        
        // Animação de entrada
        document.addEventListener('DOMContentLoaded', function() {{
            const cards = document.querySelectorAll('.regional-card, .stat-card');
            cards.forEach((card, index) => {{
                card.style.opacity = '0';
                card.style.transform = 'translateY(20px)';
                setTimeout(() => {{
                    card.style.transition = 'all 0.5s ease';
                    card.style.opacity = '1';
                    card.style.transform = 'translateY(0)';
                }}, index * 100);
            }});
        }});
    </script>
</body>
</html>
"""
        
        return html
    
    def gerar_dashboard_regional(self, codigo_regional, dados):
        """Gera dashboard específico de uma regional"""
        
        regional_data = dados["regionais"].get(codigo_regional)
        if not regional_data:
            return None
        
        html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - {regional_data['nome']}</title>
    <style>
        /* Mesmo CSS do dashboard principal, mas focado em uma regional */
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
            max-width: 1000px;
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
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        
        .servidor-card {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }}
        
        .servidor-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        
        .status-online {{ color: #27ae60; }}
        .status-offline {{ color: #e74c3c; }}
        .status-warning {{ color: #f39c12; }}
        
        .detalhes-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        
        .detalhe-item {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }}
        
        .detalhe-label {{
            color: #7f8c8d;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}
        
        .detalhe-valor {{
            font-weight: bold;
            color: #2c3e50;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏢 {regional_data['nome']}</h1>
            <p>{regional_data['descricao']}</p>
            <p><a href="dashboard_hierarquico.html">← Voltar ao Dashboard Principal</a></p>
        </div>
"""
        
        # Gera cards detalhados dos servidores
        for servidor in regional_data["servidores"]:
            status_class = f"status-{servidor['status']}"
            tipo_icon = "🔧" if servidor["tipo"] == "idrac" else "⚙️"
            
            html += f"""
        <div class="servidor-card">
            <div class="servidor-header">
                <h2>{tipo_icon} {servidor['nome']}</h2>
                <h3 class="{status_class}">{servidor['status'].upper()}</h3>
            </div>
            
            <div class="detalhes-grid">
                <div class="detalhe-item">
                    <div class="detalhe-label">IP</div>
                    <div class="detalhe-valor">{servidor['ip']}</div>
                </div>
                <div class="detalhe-item">
                    <div class="detalhe-label">Tipo</div>
                    <div class="detalhe-valor">{servidor['tipo'].upper()}</div>
                </div>
                <div class="detalhe-item">
                    <div class="detalhe-label">Modelo</div>
                    <div class="detalhe-valor">{servidor['modelo']}</div>
                </div>
                <div class="detalhe-item">
                    <div class="detalhe-label">Função</div>
                    <div class="detalhe-valor">{servidor['funcao']}</div>
                </div>
"""
            
            if servidor["tempo_resposta"]:
                html += f"""
                <div class="detalhe-item">
                    <div class="detalhe-label">Tempo Resposta</div>
                    <div class="detalhe-valor">{servidor['tempo_resposta']}s</div>
                </div>
"""
            
            if servidor["erro"]:
                html += f"""
                <div class="detalhe-item">
                    <div class="detalhe-label">Erro</div>
                    <div class="detalhe-valor" style="color: #e74c3c;">{servidor['erro']}</div>
                </div>
"""
            
            html += """
            </div>
        </div>
"""
        
        html += """
    </div>
</body>
</html>
"""
        
        return html
    
    def gerar_todos_dashboards(self):
        """Gera todos os dashboards"""
        
        print("🚀 Gerando dashboards hierárquicos...")
        
        # Coleta dados
        dados = self.coletar_dados_completos()
        
        # Dashboard principal
        html_principal = self.gerar_dashboard_principal(dados)
        arquivo_principal = self.output_dir / "dashboard_hierarquico.html"
        
        with open(arquivo_principal, 'w', encoding='utf-8') as f:
            f.write(html_principal)
        
        print(f"✅ Dashboard principal: {arquivo_principal}")
        
        # Dashboards por regional
        for codigo_regional in dados["regionais"].keys():
            html_regional = self.gerar_dashboard_regional(codigo_regional, dados)
            if html_regional:
                arquivo_regional = self.output_dir / f"dashboard_{codigo_regional.lower()}.html"
                
                with open(arquivo_regional, 'w', encoding='utf-8') as f:
                    f.write(html_regional)
                
                print(f"✅ Dashboard regional: {arquivo_regional}")
        
        # Salva dados JSON para referência
        arquivo_dados = self.output_dir / "dados_dashboard.json"
        with open(arquivo_dados, 'w', encoding='utf-8') as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Dados salvos: {arquivo_dados}")
        
        return arquivo_principal
    
    def abrir_dashboard(self):
        """Gera e abre o dashboard principal"""
        
        arquivo_principal = self.gerar_todos_dashboards()
        
        print(f"\n🌐 Abrindo dashboard: {arquivo_principal}")
        webbrowser.open(arquivo_principal.resolve().as_uri())
        
        return arquivo_principal

def main():
    """Função principal"""
    
    dashboard = DashboardHierarquico()
    
    print("🏢 Dashboard Hierárquico - Regional → Servidores")
    print("=" * 50)
    
    while True:
        print("\n📋 MENU:")
        print("1. Gerar e abrir dashboard principal")
        print("2. Gerar todos os dashboards")
        print("3. Apenas coletar dados")
        print("0. Sair")
        
        opcao = input("\nEscolha uma opção: ")
        
        if opcao == "1":
            dashboard.abrir_dashboard()
        
        elif opcao == "2":
            dashboard.gerar_todos_dashboards()
        
        elif opcao == "3":
            dados = dashboard.coletar_dados_completos()
            print("\n📊 Dados coletados:")
            print(f"   Regionais: {dados['estatisticas_gerais']['total_regionais']}")
            print(f"   Servidores: {dados['estatisticas_gerais']['total_servidores']}")
            print(f"   Online: {dados['estatisticas_gerais']['servidores_online']}")
            print(f"   Offline: {dados['estatisticas_gerais']['servidores_offline']}")
        
        elif opcao == "0":
            break
        
        else:
            print("❌ Opção inválida")

if __name__ == "__main__":
    main()