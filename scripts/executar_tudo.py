import subprocess
from pathlib import Path
import webbrowser
import os
import re
from datetime import datetime
import sys

# Configuração para Windows - força UTF-8
if sys.platform == "win32":
    import codecs
    import locale
    
    # Tenta configurar UTF-8
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except:
        # Se falhar, usa print seguro sem emojis
        pass

# Função para print seguro (sem emojis no Windows)
def safe_print(message):
    """Print seguro que funciona no Windows"""
    try:
        print(message)
    except UnicodeEncodeError:
        # Remove emojis e caracteres especiais
        import re
        clean_message = re.sub(r'[^\x00-\x7F]+', '[EMOJI]', message)
        print(clean_message)

# Importa as configurações dinâmicas
from config import (
    CONEXOES_FILE, REGIONAL_HTMLS_DIR, GPS_HTML, REPLICACAO_HTML, 
    UNIFI_HTML, DASHBOARD_FINAL, ensure_directories, get_regional_html_path,
    validate_config, PROJECT_ROOT
)

# === VALIDAÇÃO E INICIALIZAÇÃO ===
# Valida as configurações antes de continuar
config_errors = validate_config()
if config_errors:
    print("[ERRO] Erros de configuração encontrados:")
    for error in config_errors:
        print(f"   - {error}")
    sys.exit(1)

# Garante que os diretórios necessários existem
ensure_directories()

safe_print(f"[INFO] Usando diretório do projeto: {PROJECT_ROOT}")
safe_print(f"[INFO] Arquivos serão salvos em: {DASHBOARD_FINAL.parent}")
safe_print(f"[INFO] Arquivo de conexões: {CONEXOES_FILE}")
print()

# === DATA E HORA DA EXECUÇÃO ===
# Obtém a data e hora atual para exibir no dashboard
data_execucao = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

# === 1. EXECUTA CHEKLISTS DAS REGIONAIS ===
# Carrega servidores do novo sistema de gerenciamento
try:
    from gerenciar_servidores import GerenciadorServidores
    gerenciador = GerenciadorServidores()
    servidores_configurados = gerenciador.listar_servidores()
    print(f"[INFO] {len(servidores_configurados)} servidores carregados do sistema de gerenciamento")
except Exception as e:
    print(f"[AVISO] Erro ao carregar gerenciador de servidores: {e}")
    print("[INFO] Usando método legado...")
    # Fallback para método antigo
    conteudo = CONEXOES_FILE.read_text(encoding="utf-8")
    blocos = re.split(r"\n\s*\n", conteudo.strip())
    servidores_configurados = []
    
    for bloco in blocos:
        nome_match = re.search(r"Nome:\s*(.+)", bloco, re.IGNORECASE)
        tipo_match = re.search(r"Tipo:\s*(\w+)", bloco, re.IGNORECASE)
        ip_match = re.search(r"IP:\s*([\d\.]+)", bloco, re.IGNORECASE)
        user_match = re.search(r"Usuario:\s*(\S+)", bloco, re.IGNORECASE)
        pass_match = re.search(r"Senha:\s*(\S+)", bloco, re.IGNORECASE)
        
        if all([nome_match, tipo_match, ip_match, user_match, pass_match]):
            servidores_configurados.append({
                'nome': nome_match.group(1).strip(),
                'tipo': tipo_match.group(1).strip().lower(),
                'ip': ip_match.group(1).strip(),
                'usuario': user_match.group(1).strip(),
                'senha': pass_match.group(1).strip(),
                'ativo': True
            })

blocos_html_regionais_with_status = [] # Armazena (html_bloco_string, tem_erro)

# Processa cada servidor configurado
for servidor in servidores_configurados:
    # Pula servidores inativos
    if not servidor.get('ativo', True):
        continue
    
    nome = servidor['nome']
    tipo = servidor['tipo']
    ip = servidor['ip']
    usuario = servidor['usuario']
    senha = servidor['senha']
    html_path = get_regional_html_path(nome)

    current_regional_html_content = ""
    has_error_for_regional = False

    # Executa o script de checklist apropriado baseado no 'tipo'
    try:
        if tipo == "idrac":
            print(f"[EXEC] Coletando {nome} ({ip}) - iDRAC")
            subprocess.run(["python", "Chelist.py", ip, usuario, senha, str(html_path)], check=True)
        elif tipo == "ilo":
            print(f"[EXEC] Coletando {nome} ({ip}) - iLO")
            subprocess.run(["python", "iLOcheck.py", ip, usuario, senha, str(html_path)], check=True)
        else:
            # Trata tipos desconhecidos escrevendo uma mensagem de erro no arquivo HTML
            current_regional_html_content = f"""
            <div class="error-container">
                <div class="error-icon">[ERRO]</div>
                <div class="error-title">Tipo desconhecido</div>
                <div class="error-message">Tipo: {tipo}</div>
            </div>
            """
            has_error_for_regional = True
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(current_regional_html_content)
    except subprocess.CalledProcessError as e:
        print(f"[ERRO] Erro ao executar script para {nome} ({ip}): {e}")
        # Se o subprocess falhar, marca como erro e escreve uma mensagem de erro genérica
        current_regional_html_content = f"""
        <div class="error-container">
            <div class="error-icon">❌</div>
            <div class="error-title">Erro ao executar script</div>
            <div class="error-message">Regional: {nome}<br>IP: {ip}<br>Erro: {e}</div>
        </div>
        """
        has_error_for_regional = True
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(current_regional_html_content)

    # Após tentar executar o subprocess ou tratar tipo desconhecido/erro de subprocess,
    # lê o conteúdo do arquivo HTML gerado se ele existir.
    # Este passo é crucial para capturar erros escritos pelos próprios Chelist.py/iLOcheck.py.
    if html_path.exists():
        file_content = html_path.read_text(encoding="utf-8")
        # Verifica indicadores comuns de erro no conteúdo do arquivo, incluindo o erro específico do iDRAC
        if "❌ Erro" in file_content or "Error" in file_content or "timed out" in file_content or "Connection to" in file_content:
            has_error_for_regional = True
        current_regional_html_content = file_content
    else:
        # Se o arquivo não existir, definitivamente é um erro
        current_regional_html_content = """
        <div class="error-container">
            <div class="error-icon">❌</div>
            <div class="error-title">Erro ao gerar HTML</div>
            <div class="error-message">Arquivo não encontrado</div>
        </div>
        """
        has_error_for_regional = True

    # Constrói o bloco HTML para esta regional
    regional_html_block = f"""
    <details class="regional-item">
      <summary><strong>{nome}</strong></summary>
      <div class="regional-content">
        {current_regional_html_content}
      </div>
    </details>
    """
    blocos_html_regionais_with_status.append((regional_html_block, has_error_for_regional))

# === 2. EXECUTA GPS AMIGO ===
print("[EXEC] Capturando print do GPS Amigo...")
try:
    # Executa o script para capturar print do GPS Amigo
    subprocess.run(["python", "utilizarSession.py"], check=True)
except subprocess.CalledProcessError:
    print("[ERRO] Erro ao executar utilizarSession.py")


# === 3. EXECUTA REPLICAÇÃO AD ===
print("[EXEC] Executando verificação de replicação AD...")
try:
    # Executa o script PowerShell para verificação de replicação AD
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", "Replicacao_Servers.ps1"], check=True)
except subprocess.CalledProcessError:
    print("[ERRO] Erro ao executar Replicacao_Servers.ps1")

# === 4. EXECUTA COLETA DAS APs UNIFI ===
print("[EXEC] Coletando informações das APs UniFi...")
try:
    # Executa o script Python para coletar informações das APs UniFi
    subprocess.run(["python", "Unifi.Py"], check=True)
except subprocess.CalledProcessError:
    print("[ERRO] Erro ao executar Unifi.py")

# === 5. CARREGA HTMLs GERADOS ===
# Carrega o conteúdo dos arquivos HTML gerados. Se um arquivo não existir, fornece uma mensagem de erro.
gps_html = GPS_HTML.read_text(encoding="utf-8") if GPS_HTML.exists() else """
<div class="error-container">
    <div class="error-icon">❌</div>
    <div class="error-title">Arquivo não encontrado</div>
    <div class="error-message">print_temp.html não encontrado</div>
</div>
"""
rep_html = REPLICACAO_HTML.read_text(encoding="utf-8") if REPLICACAO_HTML.exists() else """
<div class="error-container">
    <div class="error-icon">❌</div>
    <div class="error-title">Arquivo não encontrado</div>
    <div class="error-message">replsummary.html não encontrado</div>
</div>
"""
# Reconstrói regionais_html a partir dos blocos armazenados com seus status
regionais_html = "".join([block_string for block_string, _ in blocos_html_regionais_with_status])
if not blocos_html_regionais_with_status:
    regionais_html = """
    <div class="error-container">
        <div class="error-icon">❌</div>
        <div class="error-title">Nenhuma regional processada</div>
        <div class="error-message">Verifique o arquivo de conexões</div>
    </div>
    """
unifi_html = UNIFI_HTML.read_text(encoding="utf-8") if UNIFI_HTML.exists() else """
<div class="error-container">
    <div class="error-icon">❌</div>
    <div class="error-title">Arquivo não encontrado</div>
    <div class="error-message">dados_aps_unifi.html não encontrado</div>
</div>
"""

# === 6. KPIs e dados para os gráficos ===
# Calcula KPIs para verificações regionais baseado no status de erro armazenado
regionais_ok = sum(1 for _, has_error in blocos_html_regionais_with_status if not has_error)
regionais_erro = sum(1 for _, has_error in blocos_html_regionais_with_status if has_error)

# Debug Regionais
print(f"🔍 Debug Regionais:")
print(f"   - Regionais OK: {regionais_ok}")
print(f"   - Regionais com erro: {regionais_erro}")
print(f"   - Total de blocos processados: {len(blocos_html_regionais_with_status)}")
for i, (_, has_error) in enumerate(blocos_html_regionais_with_status):
    status = "ERRO" if has_error else "OK"
    print(f"   - Regional {i+1}: {status}")

# Determina a exibição do status do GPS com ícones
if GPS_HTML.exists():
    gps_status_display = "<i class='fas fa-check-circle text-green-500'></i> Sucesso"
else:
    gps_status_display = "<i class='fas fa-times-circle text-red-500'></i> Erro"

# Conta APs online/offline do conteúdo HTML do UniFi
aps_online = unifi_html.count("Online") if "❌" not in unifi_html else 0
aps_offline = unifi_html.count("Offline") if "❌" not in unifi_html else 0

# Debug UniFi
print(f"🔍 Debug UniFi:")
print(f"   - APs Online: {aps_online}")
print(f"   - APs Offline: {aps_offline}")
print(f"   - HTML UniFi existe: {UNIFI_HTML.exists()}")
if "❌" in unifi_html:
    print(f"   - Erro detectado no HTML UniFi")

# === LÓGICA CORRETA DE CONTAGEM BASEADA EM LATÊNCIA E ERRO ===
# Lista de servidores com falha de replicação explícita (erros operacionais)
# Busca por padrões como "58 - servidor.dominio.local"
replication_errors_list = re.findall(r"\d+\s*-\s*([A-Z0-9\.\-]+\.(?:[A-Z0-9\-]+\.)?local)", rep_html, re.IGNORECASE)

# Busca por dados na tabela HTML - padrão mais flexível
# Procura por linhas da tabela que contenham dados de servidor
table_rows = re.findall(r"<tr[^>]*>.*?<td[^>]*>([A-Z0-9\-]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>(\d+)</td>.*?</tr>", rep_html, re.IGNORECASE | re.DOTALL)

# Conta servidores com erro na tabela (coluna Erros > 0)
table_errors = 0
rep_ok = 0

# Processa cada linha da tabela
for servidor, latencia, sucesso_total, erros in table_rows:
    servidor_clean = servidor.strip().upper()
    erros_num = int(erros.strip())
    
    if erros_num > 0:
        table_errors += 1
    else:
        # Verifica se não está na lista de erros operacionais
        servidor_base = servidor_clean.split('.')[0]  # Remove domínio se houver
        is_in_error_list = any(servidor_base in erro.upper() or servidor_clean in erro.upper() for erro in replication_errors_list)
        
        # Conta como OK se não tem erros e não está na lista de erros operacionais
        if not is_in_error_list:
            rep_ok += 1

# Total de erros = erros operacionais + erros da tabela
rep_fail = len(replication_errors_list) + table_errors
rep_total = rep_ok + rep_fail

# Debug: adiciona informações para troubleshooting
print(f"🔍 Debug Replicação AD:")
print(f"   - Servidores OK: {rep_ok}")
print(f"   - Erros operacionais: {len(replication_errors_list)}")
print(f"   - Erros da tabela: {table_errors}")
print(f"   - Total de erros: {rep_fail}")
print(f"   - Total geral: {rep_total}")
if replication_errors_list:
    print(f"   - Lista de erros operacionais: {replication_errors_list}")
print(f"   - Linhas da tabela encontradas: {len(table_rows)}")

# Ensure rep_ok is not negative
if rep_ok < 0:
    rep_ok = 0

# Determine AD replication status display with icons.
if rep_fail == 0:
    rep_status_display = "<i class='fas fa-check-circle text-green-500'></i> Sucesso"
else:
    rep_status_display = "<i class='fas fa-times-circle text-red-500'></i> Erro"

# === 7. MONTA DASHBOARD FINAL ===
# Construct the final HTML dashboard using f-strings for dynamic content insertion.
dashboard_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Consolidado</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <!-- Font Awesome for icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        :root {{
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --secondary-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            --warning-gradient: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
            --error-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            --neutral-gradient: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            --glass-bg: rgba(255, 255, 255, 0.25);
            --glass-border: rgba(255, 255, 255, 0.18);
            --shadow-soft: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            --shadow-hover: 0 15px 35px rgba(31, 38, 135, 0.2);
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
            background-attachment: fixed;
            color: #2d3748;
            line-height: 1.6;
            min-height: 100vh;
        }}
        
        .main-container {{
            backdrop-filter: blur(10px);
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            margin: 20px;
            padding: 40px;
            box-shadow: var(--shadow-soft);
        }}
        
        .page-title {{
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-size: 3.5rem;
            font-weight: 800;
            text-align: center;
            margin-bottom: 10px;
            letter-spacing: -0.02em;
        }}
        
        .page-subtitle {{
            text-align: center;
            color: rgba(45, 55, 72, 0.8);
            font-size: 1.1rem;
            font-weight: 500;
            margin-bottom: 40px;
        }}
        
        .kpi-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        
        .kpi {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            padding: 24px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }}
        
        .kpi::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
            border-radius: 16px 16px 0 0;
        }}
        
        .kpi:hover {{
            transform: translateY(-8px);
            box-shadow: var(--shadow-hover);
            background: rgba(255, 255, 255, 0.95);
        }}
        
        .kpi-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }}
        
        .kpi-icon {{
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            color: white;
        }}
        
        .kpi-icon.success {{ background: var(--success-gradient); }}
        .kpi-icon.error {{ background: var(--error-gradient); }}
        .kpi-icon.warning {{ background: var(--warning-gradient); }}
        .kpi-icon.info {{ background: var(--primary-gradient); }}
        .kpi-icon.neutral {{ background: var(--neutral-gradient); }}
        
        .kpi-header h3 {{
            font-size: 0.9rem;
            font-weight: 600;
            color: #4a5568;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        
        .kpi-value {{
            font-size: 2.5rem;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 8px;
        }}
        
        .kpi-status {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.9rem;
            font-weight: 500;
        }}
        
        .kpi ul {{
            font-size: 0.85rem;
            margin-top: 12px;
            padding-left: 20px;
            color: #e53e3e;
        }}
        
        .charts-section {{
            margin: 50px 0;
        }}
        
        .section-title {{
            font-size: 2.2rem;
            font-weight: 700;
            text-align: center;
            margin-bottom: 30px;
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 30px;
        }}
        
        .chart-wrapper {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 20px;
            padding: 30px;
            box-shadow: var(--shadow-soft);
            transition: all 0.3s ease;
            min-height: 350px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        
        .chart-wrapper:hover {{
            transform: translateY(-5px);
            box-shadow: var(--shadow-hover);
        }}
        
        .divider {{
            height: 2px;
            background: var(--primary-gradient);
            border: none;
            border-radius: 2px;
            margin: 50px 0;
            opacity: 0.3;
        }}
        
        .details-section {{
            background: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            margin-bottom: 20px;
            overflow: hidden;
            box-shadow: var(--shadow-soft);
            transition: all 0.3s ease;
        }}
        
        .details-section:hover {{
            box-shadow: var(--shadow-hover);
        }}
        
        .details-section summary {{
            background: rgba(255, 255, 255, 0.1);
            padding: 20px 30px;
            cursor: pointer;
            font-size: 1.3rem;
            font-weight: 600;
            color: #2d3748;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
            position: relative;
        }}
        
        .details-section summary:hover {{
            background: rgba(255, 255, 255, 0.2);
        }}
        
        .details-section summary::marker {{
            display: none;
        }}
        
        .details-section summary::before {{
            content: '▶';
            position: absolute;
            right: 30px;
            top: 50%;
            transform: translateY(-50%);
            transition: transform 0.3s ease;
            color: #667eea;
            font-size: 1.2rem;
        }}
        
        .details-section[open] summary::before {{
            transform: translateY(-50%) rotate(90deg);
        }}
        
        .details-content {{
            padding: 30px;
            background: rgba(255, 255, 255, 0.05);
        }}
        
        .regional-item {{
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 12px;
            margin-bottom: 16px;
            overflow: hidden;
            box-shadow: 0 4px 16px rgba(31, 38, 135, 0.15);
        }}
        
        .regional-item summary {{
            background: rgba(255, 255, 255, 0.1);
            padding: 16px 20px;
            font-weight: 600;
            color: #4a5568;
        }}
        
        .regional-content {{
            padding: 20px;
            background: rgba(255, 255, 255, 0.9);
        }}
        
        .error-container {{
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 16px rgba(250, 112, 154, 0.3);
            margin: 10px 0;
        }}
        
        .error-icon {{
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        
        .error-title {{
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        
        .error-message {{
            font-size: 0.9rem;
            opacity: 0.9;
        }}
        
        /* Responsive adjustments */
        @media (max-width: 768px) {{
            .main-container {{
                margin: 10px;
                padding: 20px;
            }}
            
            .page-title {{
                font-size: 2.5rem;
            }}
            
            .kpi-container {{
                grid-template-columns: 1fr;
            }}
            
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="main-container">
        <h1 class="page-title">Dashboard Consolidado</h1>
        <p class="page-subtitle"><strong>Executado em:</strong> {data_execucao}</p>

        <div class="kpi-container">
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon success">
                        <i class="fas fa-check-circle"></i>
                    </div>
                    <h3>Regionais OK</h3>
                </div>
                <div class="kpi-value">{regionais_ok}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon error">
                        <i class="fas fa-times-circle"></i>
                    </div>
                    <h3>Regionais com Erro</h3>
                </div>
                <div class="kpi-value">{regionais_erro}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-wifi"></i>
                    </div>
                    <h3>APs Online</h3>
                </div>
                <div class="kpi-value">{aps_online}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon neutral">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <h3>APs Offline</h3>
                </div>
                <div class="kpi-value">{aps_offline}</div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon warning">
                        <i class="fas fa-map-marker-alt"></i>
                    </div>
                    <h3>Status do GPS</h3>
                </div>
                <div class="kpi-status">
                    {gps_status_display}
                </div>
            </div>
            <div class="kpi">
                <div class="kpi-header">
                    <div class="kpi-icon info">
                        <i class="fas fa-sync-alt"></i>
                    </div>
                    <h3>Replicação AD</h3>
                </div>
                <div class="kpi-status">
                    {rep_status_display}
                </div>
                {"<ul>" + ''.join(f"<li>{srv}</li>" for srv in replication_errors_list) + "</ul>" if replication_errors_list else ""}
            </div>
        </div>

        <!-- GRÁFICOS -->
        <div class="charts-section">
            <h2 class="section-title">📊 Visão Geral em Gráficos</h2>
            <div class="charts-grid">
                <div class="chart-wrapper">
                    <canvas id="chartRegionais"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartUnifi"></canvas>
                </div>
                <div class="chart-wrapper">
                    <canvas id="chartReplicacao"></canvas>
                </div>
            </div>
        </div>

        <hr class="divider">

        <details open id="regionais" class="details-section">
            <summary>🖥️ Status das Regionais (iDRAC/iLO)</summary>
            <div class="details-content">
                {regionais_html}
            </div>
        </details>

        <details id="gps" class="details-section">
            <summary>📍 Print GPS Amigo</summary>
            <div class="details-content">
                {gps_html}
            </div>
        </details>

        <details id="replicacao" class="details-section">
            <summary>🔄 Status de Replicação do Active Directory</summary>
            <div class="details-content">
                {rep_html}
            </div>
        </details>

        <details id="unifi" class="details-section">
            <summary>📡 Status das Antenas UniFi (por site)</summary>
            <div class="details-content">
                {unifi_html}
            </div>
        </details>
    </div>

<script>
// Global configuration to make charts responsive
Chart.defaults.responsive = true;
Chart.defaults.maintainAspectRatio = false; // Important to allow the container to control the aspect ratio

new Chart(document.getElementById('chartRegionais'), {{
    type: 'doughnut',
    data: {{
        labels: ['OK', 'Erro'],
        datasets: [{{
            data: [{regionais_ok}, {regionais_erro}],
            backgroundColor: ['#4CAF50', '#F44336'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Status Servidores iDRAC/iLO',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartUnifi'), {{
    type: 'doughnut',
    data: {{
        labels: ['Online', 'Offline'],
        datasets: [{{
            data: [{aps_online}, {aps_offline}],
            backgroundColor: ['#2196F3', '#B0BEC5'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'APs Online vs Offline',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});

new Chart(document.getElementById('chartReplicacao'), {{
    type: 'doughnut',
    data: {{
        labels: ['OK', 'Com Falha'],
        datasets: [{{
            data: [{rep_ok}, {rep_fail}],
            backgroundColor: ['#8BC34A', '#FF7043'],
            borderColor: '#ffffff',
            borderWidth: 2
        }}]
    }},
    options: {{
        plugins: {{
            title: {{
                display: true,
                text: 'Replicação AD',
                font: {{
                    size: 16
                }},
                color: '#333'
            }},
            legend: {{
                position: 'bottom',
                labels: {{
                    font: {{
                        size: 14
                    }},
                    color: '#555'
                }}
            }}
        }}
    }}
}});
</script>

</body>
</html>
"""

# Escreve o conteúdo HTML completo no arquivo do dashboard final
DASHBOARD_FINAL.write_text(dashboard_html, encoding="utf-8")

# === 8. REMOVE ARQUIVOS TEMPORÁRIOS ===
# Limpa arquivos HTML temporários gerados durante o processo
for file in REGIONAL_HTMLS_DIR.glob("*.html"):
    file.unlink() # Remove cada arquivo HTML regional
if GPS_HTML.exists():
    GPS_HTML.unlink() # Remove o arquivo HTML do GPS
if REPLICACAO_HTML.exists():
    REPLICACAO_HTML.unlink() # Remove o arquivo HTML do resumo de replicação
if UNIFI_HTML.exists():
    UNIFI_HTML.unlink() # Remove o arquivo HTML dos dados das APs UniFi

# === 9. ABRE NO NAVEGADOR ===
# Abre o arquivo HTML do dashboard gerado no navegador padrão
print(f"\n✅ Dashboard gerado com sucesso: {DASHBOARD_FINAL}")
webbrowser.open(DASHBOARD_FINAL.resolve().as_uri())
