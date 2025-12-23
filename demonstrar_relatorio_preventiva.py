"""
Script para demonstrar como funcionará o novo sistema de Relatório Preventiva
"""
from config import (
    DASHBOARD_FINAL, 
    DASHBOARD_FINAL_ORIGINAL,
    RELATORIO_PREVENTIVA_DIR,
    ensure_directories,
    get_dashboard_filename
)
from datetime import datetime
import webbrowser

def criar_relatorio_demo():
    """Cria um relatório de demonstração"""
    print("🎯 DEMONSTRAÇÃO DO RELATÓRIO PREVENTIVA")
    print("=" * 60)
    
    # Garante que as pastas existem
    ensure_directories()
    
    # Cria um HTML de demonstração
    html_demo = f"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relatório Preventiva - Demonstração</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 40px;
        }}
        .title {{
            font-size: 3rem;
            font-weight: bold;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }}
        .subtitle {{
            font-size: 1.2rem;
            color: #666;
            margin-bottom: 20px;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        .info-card {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        }}
        .info-card h3 {{
            margin: 0 0 10px 0;
            font-size: 1.3rem;
        }}
        .info-card p {{
            margin: 5px 0;
            opacity: 0.9;
        }}
        .success-message {{
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            font-size: 1.1rem;
            margin-top: 30px;
        }}
        .path-info {{
            background: #f8f9fa;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
            font-family: 'Courier New', monospace;
        }}
        .path-info h4 {{
            margin: 0 0 15px 0;
            color: #495057;
        }}
        .path {{
            background: #e9ecef;
            padding: 10px;
            border-radius: 5px;
            word-break: break-all;
            color: #495057;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="title">📊 Relatório Preventiva</h1>
            <p class="subtitle">Sistema de Monitoramento de Infraestrutura</p>
            <p><strong>Data/Hora de Geração:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
        </div>
        
        <div class="info-grid">
            <div class="info-card">
                <h3>📁 Nova Estrutura de Pastas</h3>
                <p><strong>Local:</strong> Área de Trabalho</p>
                <p><strong>Pasta Base:</strong> Relatório Preventiva</p>
                <p><strong>Organização:</strong> Ano/Mês/Dia</p>
                <p><strong>Arquivo:</strong> Com timestamp</p>
            </div>
            
            <div class="info-card">
                <h3>🎯 Benefícios</h3>
                <p>✅ Organização automática por data</p>
                <p>✅ Fácil localização dos relatórios</p>
                <p>✅ Histórico preservado</p>
                <p>✅ Backup automático</p>
            </div>
            
            <div class="info-card">
                <h3>📈 Informações Coletadas</h3>
                <p>🖥️ Servidores (iDRAC/iLO)</p>
                <p>🔄 Replicação Active Directory</p>
                <p>💻 Máquinas Virtuais</p>
                <p>🌐 Switches de Rede</p>
                <p>📡 Access Points UniFi</p>
                <p>🌍 Links de Internet</p>
            </div>
            
            <div class="info-card">
                <h3>⚙️ Configuração</h3>
                <p><strong>Criação automática:</strong> Sim</p>
                <p><strong>Verificação de pastas:</strong> Automática</p>
                <p><strong>Compatibilidade:</strong> Mantida</p>
                <p><strong>Backup:</strong> Duplo local</p>
            </div>
        </div>
        
        <div class="path-info">
            <h4>📂 Estrutura de Pastas Criada:</h4>
            <div class="path">
                Desktop/Relatório Preventiva/{datetime.now().year}/{datetime.now().month:02d}/{datetime.now().day:02d}/
            </div>
        </div>
        
        <div class="path-info">
            <h4>📄 Localização do Arquivo:</h4>
            <div class="path">
                {DASHBOARD_FINAL}
            </div>
        </div>
        
        <div class="success-message">
            🎉 <strong>Sistema Configurado com Sucesso!</strong><br>
            O relatório será salvo automaticamente na estrutura de pastas organizada por data.
        </div>
    </div>
</body>
</html>
"""
    
    # Salva o arquivo de demonstração
    DASHBOARD_FINAL.write_text(html_demo, encoding="utf-8")
    DASHBOARD_FINAL_ORIGINAL.write_text(html_demo, encoding="utf-8")
    
    print(f"✅ Relatório de demonstração criado!")
    print(f"📂 Local principal: {DASHBOARD_FINAL}")
    print(f"📂 Local original: {DASHBOARD_FINAL_ORIGINAL}")
    
    # Abre no navegador
    print(f"\n🌐 Abrindo no navegador...")
    webbrowser.open(DASHBOARD_FINAL.resolve().as_uri())
    
    print(f"\n🎯 RESUMO DA CONFIGURAÇÃO:")
    print(f"   - Pasta base criada: ✅")
    print(f"   - Estrutura por data: ✅")
    print(f"   - Arquivo com timestamp: ✅")
    print(f"   - Compatibilidade mantida: ✅")
    print(f"   - Demonstração funcionando: ✅")

if __name__ == "__main__":
    criar_relatorio_demo()