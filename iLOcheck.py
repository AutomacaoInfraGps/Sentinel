import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if len(sys.argv) != 5:
    print("Uso: python ilo_redfish.py <ip> <usuario> <senha> <saida_html>")
    sys.exit(1)

ip = sys.argv[1]
usuario = sys.argv[2]
senha = sys.argv[3]
saida_html = sys.argv[4]

base_url = f"https://{ip}/redfish/v1"
session_url = f"{base_url}/SessionService/Sessions"
system_url = f"{base_url}/Systems/1"

try:
    # 1. Criar sessão Redfish
    headers = {"Content-Type": "application/json"}
    payload = {"UserName": usuario, "Password": senha}
    session_response = requests.post(session_url, json=payload, headers=headers, verify=False)  # TODO: Implementar verificação de certificado adequada

    if session_response.status_code != 201:
        raise Exception(f"Erro ao criar sessão: {session_response.status_code} - {session_response.text}")

    token = session_response.headers.get("X-Auth-Token")
    if not token:
        raise Exception("Token de sessão não retornado.")

    # 2. Acessar o sistema com token
    headers = {"X-Auth-Token": token}
    system_response = requests.get(system_url, headers=headers, verify=False)  # TODO: Implementar verificação de certificado adequada
    system_response.raise_for_status()
    dados = system_response.json()
    status = dados.get("Status", {})

    # 3. Monta HTML
    html = f"""
    <style>
        .server-table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 16px rgba(31, 38, 135, 0.15);
        }}
        .server-table th {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 16px;
            text-align: left;
            font-weight: 600;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .server-table td {{
            padding: 14px 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            transition: background-color 0.3s ease;
        }}
        .server-table tr:hover td {{
            background: rgba(102, 126, 234, 0.05);
        }}
        .server-table tr:last-child td {{
            border-bottom: none;
        }}
        .field-name {{
            font-weight: 600;
            color: #4a5568;
            width: 40%;
        }}
        .field-value {{
            color: #2d3748;
            font-family: 'Monaco', 'Menlo', monospace;
        }}
    </style>
    <table class="server-table">
        <thead>
            <tr><th>Campo</th><th>Valor</th></tr>
        </thead>
        <tbody>
            <tr><td class="field-name">🏷️ Modelo</td><td class="field-value">{dados.get('Model')}</td></tr>
            <tr><td class="field-name">🏭 Fabricante</td><td class="field-value">{dados.get('Manufacturer')}</td></tr>
            <tr><td class="field-name">🔢 Número de Série</td><td class="field-value">{dados.get('SerialNumber')}</td></tr>
            <tr><td class="field-name">⚡ Estado de Energia</td><td class="field-value">{dados.get('PowerState')}</td></tr>
            <tr><td class="field-name">💚 Saúde</td><td class="field-value">{status.get('Health')}</td></tr>
            <tr><td class="field-name">📊 Saúde (Rollup)</td><td class="field-value">{status.get('HealthRollup')}</td></tr>
            <tr><td class="field-name">🔄 Estado Operacional</td><td class="field-value">{status.get('State')}</td></tr>
        </tbody>
    </table>
    """

    with open(saida_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML gerado: {saida_html}")

except Exception as e:
    error_html = f"""
    <style>
        .error-container {{
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 16px rgba(250, 112, 154, 0.3);
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
    </style>
    <div class="error-container">
        <div class="error-icon">[ERRO]</div>
        <div class="error-title">Erro ao conectar ao iLO</div>
        <div class="error-message">IP: {ip}<br>Detalhes: {str(e)}</div>
    </div>
    """
    with open(saida_html, "w", encoding="utf-8") as f:
        f.write(error_html)
    print(f"[ERRO] Erro: {str(e)}")
