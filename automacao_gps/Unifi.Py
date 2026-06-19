import requests
import urllib3
import os
import json
from datetime import datetime

# Importa as configurações dinâmicas
from config import UNIFI_HTML, UNIFI_CONFIG, ensure_directories
from data_store import save_data

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
        body { font-family: Arial; margin: 20px; }
        h2 { cursor: pointer; background: #0078d4; color: white; padding: 10px; border-radius: 5px; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
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
canal_5ghz_map = {}

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
        html += "<tr><th>Nome</th><th>IP</th><th>MAC</th><th>Modelo</th><th>Firmware</th><th>Status</th><th>Clientes</th><th>Uptime (s)</th></tr>"

        # ========= COLETA 5GHz =========
        for ap in aps:
            radio_5ghz = next(
                (r for r in ap.get("radio_table", []) if r.get("radio") == "na"),
                None
            )

            if radio_5ghz:
                print(f"[DEBUG] AP {ap.get('name')} | radio_5ghz keys: {radio_5ghz.keys()}")

            if not radio_5ghz:
                continue

            canal = radio_5ghz.get("channel")
            signal = radio_5ghz.get("signal") or radio_5ghz.get("rssi")

            if canal is None:
                continue

            if canal not in canal_5ghz_map:
                canal_5ghz_map[canal] = {
                    "aps": [],
                    "signal_vals": []
                }

            canal_5ghz_map[canal]["aps"].append(ap.get("name"))

            if signal is not None:
                canal_5ghz_map[canal]["signal_vals"].append(signal)

            # ===== HTML NORMAL =====
            status = "Online" if ap.get("state") == 1 else "Offline"
            status_class = "ap-online" if status == "Online" else "ap-offline"

            ap_data = {
                "nome": ap.get("name", ""),
                "ip": ap.get("ip", ""),
                "mac": ap.get("mac", ""),
                "modelo": ap.get("model", ""),
                "firmware": ap.get("version", ""),
                "status": status.lower(),
                "clientes": ap.get("num_sta", 0),
                "uptime": ap.get("uptime", 0),
                "site": site_desc
            }
            all_aps.append(ap_data)

            html += f"""
            <tr>
                <td>{ap.get("name", "")}</td>
                <td>{ap.get("ip", "")}</td>
                <td>{ap.get("mac", "")}</td>
                <td>{ap.get("model", "")}</td>
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

# === CONSOLIDAÇÃO DE INTERFERÊNCIA POR CANAL (5GHz) ===
consolidado_canais = []

for canal, dados in canal_5ghz_map.items():
    qtd_aps = len(dados["aps"])
    signals = dados["signal_vals"]

    print(f"[TESTE] Canal {canal} | Signals coletados: {signals}")

    avg_signal_dbm = (
        round(sum(signals) / len(signals), 1)
        if signals else None
    )

    risco = "OK"
    if avg_signal_dbm is not None:
        if avg_signal_dbm > -80:
            risco = "CRITICO"
        elif avg_signal_dbm > -90:
            risco = "ATENCAO"

    if qtd_aps >= 4:
        risco = "CONGESTIONADO"

    consolidado_canais.append({
        "canal": canal,
        "qtd_aps": qtd_aps,
        "avg_signal_dbm": avg_signal_dbm,
        "risco": risco,
        "aps": dados["aps"]
    })

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
    "interferencia_5ghz": consolidado_canais,
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
