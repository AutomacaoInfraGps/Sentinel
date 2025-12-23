import subprocess
import datetime
from pathlib import Path
import json
import webbrowser
import sys

# --- GPS Amigo: garantir arquivo no Public ---
from pathlib import Path
from config import OUTPUT_DIR, OUTPUT_DIR_PUBLIC, GPS_HTML, GPS_CONFIG

def ensure_gps_print():
    """
    Garante que C:/Users/Public/Automacao/output/print_temp.html exista.
    1) Se já existir no Public, mantém.
    2) Se existir no output do projeto, copia para o Public.
    3) Se não existir em lugar nenhum, cria um placeholder simples.
    """
    GPS_HTML.parent.mkdir(parents=True, exist_ok=True)

    # 1) Já existe no Public?
    if GPS_HTML.exists():
        return

    # 2) Existe no output do projeto? (compat com rotinas antigas)
    legacy = OUTPUT_DIR / "print_temp.html"
    if legacy.exists():
        GPS_HTML.write_text(legacy.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        return

    # 3) Placeholder (não quebra o card)
    placeholder = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><title>GPS Amigo</title>
<style>body{{font-family:Segoe UI,Arial;margin:16px}}.note{{color:#666}}</style></head>
<body>
  <h2>GPS Amigo</h2>
  <div class="note">Prévia indisponível no momento.</div>
  <p><a href="{GPS_CONFIG.get('url','https://gpsamigo.com.br/login.php')}" target="_blank">Abrir GPS Amigo</a></p>
</body></html>"""
    GPS_HTML.write_text(placeholder, encoding="utf-8")

def debug_log_gps():
    print(f"[GPS] Procurando: {GPS_HTML}")
    print(f"[GPS] Existe? {GPS_HTML.exists()}")
    if not GPS_HTML.exists():
        print(f"[GPS] Pasta pública: {OUTPUT_DIR_PUBLIC} (existe? {OUTPUT_DIR_PUBLIC.exists()})")
        print(f"[GPS] Pasta projeto: {OUTPUT_DIR} (existe? {OUTPUT_DIR.exists()})")


# Importa as configurações dinâmicas
from config import NAOS_CONFIG, STATUS_NAOS_HTML, ensure_directories

# === CONFIGURAÇÃO DO SERVIDOR ===
ip = NAOS_CONFIG["ip"]
usuario = NAOS_CONFIG["usuario"]
senha = NAOS_CONFIG["senha"]
hostname = ip

# Garante que os diretórios necessários existem
ensure_directories()

# Caminho fixo do PowerShell 5.1
pwsh_path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

def run_ps_remote(scriptblock):
    ps = f"""
    $secpasswd = ConvertTo-SecureString '{senha}' -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential ('{usuario}', $secpasswd)
    Invoke-Command -ComputerName {ip} -Credential $cred -ScriptBlock {{ {scriptblock} }}
    """
    result = subprocess.run([pwsh_path, "-Command", ps], capture_output=True, text=True)
    if result.stderr.strip():
        print("⚠️ ERRO:", result.stderr.strip())
    return result.stdout.strip()

def run_ps_json(scriptblock):
    output = run_ps_remote(f"{scriptblock} | ConvertTo-Json -Depth 3")
    try:
        data = json.loads(output)
        return data if isinstance(data, list) else [data]
    except:
        return []

# === COLETA DE DADOS ===
features = run_ps_remote("(Get-WindowsFeature | Where {{$_.InstallState -eq 'Installed'}}).DisplayName").splitlines()
services = run_ps_remote("(Get-Service | Where {{$_.Status -eq 'Running'}}).DisplayName").splitlines()
logs = run_ps_json("Get-EventLog -LogName System -EntryType Error, Warning -Newest 10 | Select TimeGenerated, EntryType, Source, Message")
bpa = run_ps_json("Get-BpaResult -ModelId * -ErrorAction SilentlyContinue | Where {{ $_.Severity -eq 'Error' -or $_.Severity -eq 'Warning' }} | Select ModelId, Severity, Title, Compliance")

# === GERA HTML ===
html_path = STATUS_NAOS_HTML
html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Status do Servidor {hostname}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        :root {{
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            --warning-gradient: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
            --error-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
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
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            backdrop-filter: blur(10px);
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 20px;
            padding: 40px;
            box-shadow: var(--shadow-soft);
        }}
        
        .page-title {{
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-size: 2.5rem;
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
            font-size: 1.2rem;
            font-weight: 600;
            color: #2d3748;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
            position: relative;
            display: flex;
            align-items: center;
            gap: 12px;
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
        
        .details-content ul {{
            list-style: none;
            padding: 0;
        }}
        
        .details-content li {{
            background: rgba(255, 255, 255, 0.8);
            margin-bottom: 8px;
            padding: 12px 16px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            transition: all 0.3s ease;
        }}
        
        .details-content li:hover {{
            background: rgba(255, 255, 255, 0.95);
            transform: translateX(5px);
        }}
        
        .error {{
            border-left-color: #e53e3e !important;
            background: rgba(229, 62, 62, 0.1) !important;
            color: #c53030;
        }}
        
        .warning {{
            border-left-color: #ed8936 !important;
            background: rgba(237, 137, 54, 0.1) !important;
            color: #c05621;
        }}
        
        .icon {{
            width: 24px;
            height: 24px;
            margin-right: 8px;
        }}
        
        @media (max-width: 768px) {{
            .container {{
                padding: 20px;
                margin: 10px;
            }}
            
            .page-title {{
                font-size: 2rem;
            }}
            
            .details-section summary {{
                padding: 15px 20px;
                font-size: 1.1rem;
            }}
            
            .details-content {{
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1 class="page-title">🖥️ Status do Servidor: {hostname}</h1>
        <p class="page-subtitle"><strong>Gerado em:</strong> {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>

        <details open class="details-section">
            <summary>
                <i class="fas fa-check-circle icon" style="color: #4facfe;"></i>
                Funções Instaladas
            </summary>
            <div class="details-content">
                <ul>
                    {''.join(f"<li>{f.strip()}</li>" for f in features if f.strip())}
                </ul>
            </div>
        </details>

        <details class="details-section">
            <summary>
                <i class="fas fa-cogs icon" style="color: #43e97b;"></i>
                Serviços em Execução
            </summary>
            <div class="details-content">
                <ul>
                    {''.join(f"<li>{s.strip()}</li>" for s in services if s.strip())}
                </ul>
            </div>
        </details>

        <details class="details-section">
            <summary>
                <i class="fas fa-exclamation-triangle icon" style="color: #fa709a;"></i>
                Últimos Eventos (Erro/Aviso)
            </summary>
            <div class="details-content">
                <ul>
                    {''.join(
                        f"<li class='{str(log.get('EntryType', '')).lower()}'><strong>[{log.get('TimeGenerated', '')}]</strong> {log.get('Source', '')}: {log.get('Message', '')}</li>"
                        for log in logs
                    )}
                </ul>
            </div>
        </details>

        <details class="details-section">
            <summary>
                <i class="fas fa-clipboard-check icon" style="color: #667eea;"></i>
                Análise de Melhores Práticas (BPA)
            </summary>
            <div class="details-content">
                <ul>
                    {''.join(
                        f"<li><strong>{b.get('ModelId', '')}</strong> [{b.get('Severity', '')}] - {b.get('Title', '')} ({b.get('Compliance', '')})</li>"
                        for b in bpa
                    )}
                </ul>
            </div>
        </details>
    </div>
</body>
</html>
"""

html_path.write_text(html, encoding="utf-8")
print(f"\n✅ HTML gerado com sucesso: {html_path}")
webbrowser.open(html_path.as_uri())
