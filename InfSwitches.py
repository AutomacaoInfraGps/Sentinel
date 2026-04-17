from pathlib import Path
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas não instalado. Funcionalidades limitadas.")
    PANDAS_AVAILABLE = False
    pd = None
import requests
import datetime
from config import ENV_CONFIG
try:
    from credentials import get_credentials
except ImportError:
    def get_credentials(service, prompt_if_missing=False):
        return {}

# === CONFIGURAÇÕES ===
zabbix_creds = ENV_CONFIG.get("zabbix", {}) or get_credentials("zabbix") or {}
ZABBIX_URL = zabbix_creds.get("url", "https://zabbix.example.local/zabbix/api_jsonrpc.php")
USERNAME = zabbix_creds.get("username", "")
PASSWORD = zabbix_creds.get("password", "")

# Caminho do Excel
arquivo_excel = Path("C:/Users/m.vbatista/Desktop/Projetos Automação/ChekList - Copia/switches_zabbix.xlsx")

# === AUTENTICAÇÃO NA API DO ZABBIX ===
def get_auth_token():
    if not ZABBIX_URL or not USERNAME or not PASSWORD:
        raise RuntimeError("Configure as credenciais do Zabbix no environment.json ou no cofre de credenciais.")
    payload = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {"user": USERNAME, "password": PASSWORD},
        "id": 1
    }
    headers = {"Content-Type": "application/json-rpc"}
    response = requests.post(ZABBIX_URL, headers=headers, json=payload)
    return response.json()["result"]

auth_token = get_auth_token()

# === FUNÇÃO PARA CHAMADAS À API ===
def call_api(method, params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "auth": auth_token,
        "id": 1
    }
    headers = {"Content-Type": "application/json-rpc"}
    response = requests.post(ZABBIX_URL, headers=headers, json=payload)
    return response.json()

# === LÊ A PLANILHA E NORMALIZA COLUNAS ===
df = pd.read_excel(arquivo_excel, sheet_name="Switches", header=2)
df.columns = df.columns.str.strip()

# === ORGANIZA HTML ===
html_sections = {}
for _, row in df.iterrows():
    host_name = str(row["Host"]).strip()
    regional = str(row["Regional"]).strip().upper()

    # Busca host ID
    host_resp = call_api("host.get", {
        "filter": {"name": host_name},
        "output": ["hostid", "name"]
    })
    if not host_resp["result"]:
        continue
    host_id = host_resp["result"][0]["hostid"]

    # Busca itens
    items_resp = call_api("item.get", {
        "hostids": host_id,
        "output": ["name", "lastvalue", "units", "key_"],
        "sortfield": "name"
    })

    # Gera HTML para esse host
    items_html = "".join([
        f"<tr><td>{item['name']}</td><td>{item['lastvalue']} {item['units']}</td></tr>"
        for item in items_resp["result"]
    ])
    table_html = f"""
    <details>
      <summary><strong>{host_name}</strong></summary>
      <table border="1" cellpadding="5" cellspacing="0">
        <thead><tr><th>Item</th><th>Valor</th></tr></thead>
        <tbody>{items_html}</tbody>
      </table>
    </details>
    """

    # Agrupa por regional
    if regional not in html_sections:
        html_sections[regional] = []
    html_sections[regional].append(table_html)

# === MONTA HTML FINAL ===
agora = datetime.datetime.now()
html_content = f"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="UTF-8">
  <title>Status dos Switches - Zabbix</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f9f9f9; }}
    h2 {{ background-color: #003366; color: white; padding: 10px; }}
    summary {{ cursor: pointer; padding: 5px; font-size: 1.1em; background-color: #ddd; margin-top: 5px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 5px; }}
    th, td {{ border: 1px solid #aaa; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
  </style>
</head>
<body>
  <h1>Status dos Switches por Regional</h1>
  <div style="text-align: center; margin-bottom: 20px; padding: 10px; background-color: #f0f0f0; border-radius: 5px;">
    <strong>📅 Última atualização:</strong> {agora.strftime('%d/%m/%Y às %H:%M:%S')}
  </div>
"""

for regional, blocks in html_sections.items():
    html_content += f"<h2>{regional}</h2>\n"
    html_content += "\n".join(blocks)

html_content += """
</body>
</html>
"""

# Salva o HTML
saida_html = Path("C:/Users/m.vbatista/Desktop/Projetos Automação/ChekList - Copia/status_switches_geral.html")
saida_html.write_text(html_content, encoding="utf-8")
print(f"✅ HTML dos switches salvo em: {saida_html}")
saida_html.name
