import requests
import urllib3
import os
import json
from datetime import datetime

# Importa as configurações dinâmicas
from config import UNIFI_HTML, UNIFI_CONFIG, ensure_directories
from data_store import save_data

# Mapeamento de código interno → nome amigável do modelo
UNIFI_MODEL_NAMES = {
    "U6MP":      "U6 Mesh Pro",
    "U7HD":      "U7 HD",
    "U7LR":      "U7 Long-Range",
    "U7LT":      "U7 Lite",
    "U7MP":      "U7 Mesh Pro",
    "U7NHD":     "U7 nanoHD",
    "U7PG2":     "U7 Pro Gen2",
    "U7PRO":     "U7 Pro",
    "U7PROMAX":  "U7 Pro Max",
    "UAL6":      "AP Lite 6",
    "UALR6v2":   "AP Long-Range 6 v2",
    "UAP6MP":    "U6 Mesh Pro",
    "UAPA693":   "AP Pro Gen3",
    "UKPW":      "UniFi Swiss Wall",
    # modelos legados comuns
    "UAP":       "AP Classic",
    "UAPLR":     "AP Long-Range",
    "UAPOUTDOOR":"AP Outdoor",
    "UAPPRO":    "AP Pro",
    "UAPMESH":   "AP Mesh",
    "UAPMESPH":  "AP Mesh Pro",
    "UAP6LR":    "U6 Long-Range",
    "UAP6":      "U6 Lite",
    "U6LR":      "U6 Long-Range",
    "U6LITE":    "U6 Lite",
    "U6EXTD":    "U6 Extender",
    "ULTE":      "LTE",
}

def modelo_amigavel(codigo):
    return UNIFI_MODEL_NAMES.get(codigo, codigo)

# === CONFIGURAÇÕES ===
controller_host = UNIFI_CONFIG["host"]
controller_port = UNIFI_CONFIG["port"]
username = UNIFI_CONFIG["username"]
password = UNIFI_CONFIG["password"]

# Garante que os diretórios necessários existem
ensure_directories()

# === PREPARO ===
base_url = f"https://{controller_host}:{controller_port}"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()
session.verify = False

# === LOGIN ===
login_url = f"{base_url}/api/login"
resp = session.post(login_url, json={"username": username, "password": password})
if resp.status_code != 200 or "error" in resp.text.lower():
    print("Falha no login:", resp.text)
    exit()

print("Login bem-sucedido.")

# === OBTER SITES ===
sites_url = f"{base_url}/api/self/sites"
resp = session.get(sites_url)
sites = resp.json().get("data", [])
if not sites:
    print("Nenhum site encontrado.")
    exit()

print(f"{len(sites)} site(s) encontrados.")

# Variáveis para armazenar dados para JSON
total_aps = 0
aps_online = 0
total_clientes = 0
sites_data = []
all_aps = []

# === CONSTRUÇÃO DO HTML ===
html = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>Status das APs UniFi</title>
    <style>
        body { font-family: Arial; margin: 20px; color: #1f2937; }
        h1 { color: #012E40; margin-bottom: 16px; }
        h2 { cursor: pointer; background: linear-gradient(135deg, #012E40, #0A4A63, #0F6C8C); color: white; padding: 10px 12px; border-radius: 8px; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        th { background-color: #e8f3f8; color: #012E40; }
        .ap-online { color: green; font-weight: bold; }
        .ap-offline { color: red; font-weight: bold; }
    </style>
    <script>
        function toggle(el) {
            var x = el.nextElementSibling;
            x.style.display = (x.style.display === 'none') ? 'block' : 'none';
        }
    </script>
</head>
<body>
    <h1>Status das Antenas UniFi</h1>
"""

# === PERCORRER SITES ===
# Rastreia co-canal por site (interferência real = mesmo canal, mesmo local físico)
canal_5ghz_por_site = {}  # {site_desc: {canal: {aps, signal_vals}}}

for site in sites:
    site_id = site.get("name")
    site_desc = site.get("desc", site_id)
    devices_url = f"{base_url}/api/s/{site_id}/stat/device"

    try:
        resp = session.get(devices_url)
        devices = resp.json().get("data", [])
        aps = [d for d in devices if d.get("type") == "uap"]
        if not aps:
            continue

        # Dados do site para JSON
        site_data = {
            "id": site_id,
            "nome": site_desc,
            "total_aps": len(aps)
        }
        sites_data.append(site_data)

        # Atualiza contadores
        total_aps += len(aps)
        site_aps_online = sum(1 for ap in aps if ap.get("state") == 1)
        aps_online += site_aps_online
        site_clientes = sum(ap.get("num_sta", 0) for ap in aps)
        total_clientes += site_clientes

        html += f"<h2 onclick='toggle(this)'>{site_desc} ({len(aps)} APs)</h2><div style='display:none'><table>"
        html += "<tr><th>Nome</th><th>IP</th><th>MAC</th><th>Modelo</th><th>Firmware</th><th>Status</th><th>Usuários</th><th>Uptime (s)</th></tr>"

        # ========= COLETA 5GHz =========
        for ap in aps:
            # === Adiciona ao all_aps independente de status/rádio ===
            status_ap = "online" if ap.get("state") == 1 else "offline"
            all_aps.append({
                "nome": ap.get("name", ""),
                "ip": ap.get("ip", ""),
                "mac": ap.get("mac", ""),
                "modelo": modelo_amigavel(ap.get("model", "")),
                "firmware": ap.get("version", ""),
                "status": status_ap,
                "clientes": ap.get("num_sta", 0),
                "uptime": ap.get("uptime", 0),
                "site": site_desc
            })

            # Configuração do rádio 5GHz (canal)
            radio_5ghz = next(
                (r for r in ap.get("radio_table", []) if r.get("radio") == "na"),
                None
            )
            # Estatísticas em tempo real do rádio 5GHz
            radio_5ghz_stats = next(
                (r for r in ap.get("radio_table_stats", []) if r.get("radio") == "na"),
                None
            )

            if not radio_5ghz:
                continue

            canal = radio_5ghz.get("channel")

            # Ignora canal 'auto' (seleção dinâmica — não representa canal fixo)
            if canal is None or str(canal).strip().lower() in ("auto", "0", ""):
                continue

            # Channel Utilization: % do airtime sendo usado neste canal
            cu_total    = radio_5ghz_stats.get("cu_total", 0)    if radio_5ghz_stats else 0
            cu_self_tx  = radio_5ghz_stats.get("cu_self_tx", 0)  if radio_5ghz_stats else 0
            cu_self_rx  = radio_5ghz_stats.get("cu_self_rx", 0)  if radio_5ghz_stats else 0
            tx_retry    = radio_5ghz_stats.get("tx_retries_pct", 0) if radio_5ghz_stats else 0

            if site_desc not in canal_5ghz_por_site:
                canal_5ghz_por_site[site_desc] = {}
            if canal not in canal_5ghz_por_site[site_desc]:
                canal_5ghz_por_site[site_desc][canal] = {"aps": [], "cu_vals": [], "retry_vals": []}

            canal_5ghz_por_site[site_desc][canal]["aps"].append({
                "nome": ap.get("name"),
                "cu_total": cu_total,
                "cu_self_tx": cu_self_tx,
                "cu_self_rx": cu_self_rx,
                "tx_retry": round(tx_retry, 1),
                "clientes": ap.get("num_sta", 0),
            })
            canal_5ghz_por_site[site_desc][canal]["cu_vals"].append(cu_total)
            canal_5ghz_por_site[site_desc][canal]["retry_vals"].append(tx_retry)

            # ===== HTML NORMAL =====
            status = "Online" if ap.get("state") == 1 else "Offline"
            status_class = "ap-online" if status == "Online" else "ap-offline"

            html += f"""
            <tr>
                <td>{ap.get("name", "")}</td>
                <td>{ap.get("ip", "")}</td>
                <td>{ap.get("mac", "")}</td>
                <td>{modelo_amigavel(ap.get("model", ""))}</td>
                <td>{ap.get("version", "")}</td>
                <td class="{status_class}">{status}</td>
                <td>{ap.get("num_sta", 0)}</td>
                <td>{ap.get("uptime", 0)}</td>
            </tr>
            """

        html += "</table></div>"
        print(f"Site {site_desc} processado com {len(aps)} APs.")

    except Exception as e:
        print(f"Erro ao processar site {site_desc}: {e}")

# === FECHAR HTML ===
html += "</body></html>"

# === CONSOLIDAÇÃO DE INTERFERÊNCIA POR CANAL (5GHz) — POR SITE ===
# Regra baseada em Channel Utilization (cu_total) real do canal:
#   > 70% → CONGESTIONADO (canal saturado)
#   > 40% → ATENCAO (tráfego moderado-alto)
#   ≤ 40% → OK
# Também registra co-canal (qtd_aps > 1) como contexto adicional
interferencia_por_site = {}

for site_nome in sorted(canal_5ghz_por_site.keys()):
    canais = canal_5ghz_por_site[site_nome]
    site_canais = []
    for canal, dados in canais.items():
        aps_info = dados["aps"]
        cu_vals = dados["cu_vals"]
        retry_vals = dados["retry_vals"]
        qtd_aps = len(aps_info)

        max_cu = max(cu_vals) if cu_vals else 0
        avg_cu = round(sum(cu_vals) / len(cu_vals), 1) if cu_vals else 0
        avg_retry = round(sum(retry_vals) / len(retry_vals), 1) if retry_vals else 0

        def _risco_combinado(cu, retry):
            if cu > 90 or retry >= 20:
                return "CRITICO"
            elif cu >= 80 or retry >= 13:
                return "ATENCAO"
            return "OK"

        # Calcula risco combinado por AP e armazena
        for ap in aps_info:
            ap["risco"] = _risco_combinado(ap["cu_total"], ap["tx_retry"])

        # Risco do canal = pior AP
        ordem = {"CRITICO": 2, "ATENCAO": 1, "OK": 0}
        risco = max((ap["risco"] for ap in aps_info), key=lambda r: ordem.get(r, 0), default="OK")

        site_canais.append({
            "canal": canal,
            "qtd_aps": qtd_aps,
            "max_cu": max_cu,
            "avg_cu": avg_cu,
            "avg_retry": avg_retry,
            "risco": risco,
            "aps": aps_info,
        })
    # Inclui todos os sites que têm dados 5GHz (não filtra por risco)
    if site_canais:
        interferencia_por_site[site_nome] = site_canais

# === SALVAR HTML ===
with open(UNIFI_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nHTML salvo em: {UNIFI_HTML}")

# === SALVAR DADOS EM JSON ===
json_data = {
    "total_aps": total_aps,
    "aps_online": aps_online,
    "aps_offline": total_aps - aps_online,
    "clientes_conectados": total_clientes,
    "interferencia_5ghz_por_site": interferencia_por_site,
    "controller": {
        "ip": controller_host,
        "porta": controller_port,
        "online": True
    },
    "sites": sites_data,
    "aps": all_aps
}

save_data("unifi", json_data)
print("Dados JSON salvos no sistema centralizado")

# === LOGOUT ===
try:
    session.post(f"{base_url}/api/logout")
except Exception as e:
    print(f"Erro em {__file__}: {e}")