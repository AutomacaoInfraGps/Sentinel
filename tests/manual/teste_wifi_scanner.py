import requests
import urllib3
from config import UNIFI_CONFIG

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.verify = False

base_url = f"https://{UNIFI_CONFIG['host']}:{UNIFI_CONFIG['port']}"

# LOGIN
login = session.post(
    f"{base_url}/api/login",
    json={
        "username": UNIFI_CONFIG["username"],
        "password": UNIFI_CONFIG["password"]
    }
)

print("Login status:", login.status_code)

# LISTA DE SITES
sites = session.get(f"{base_url}/api/self/sites").json().get("data", [])

for site in sites:
    site_id = site["name"]
    site_desc = site.get("desc", site_id)

    print(f"\n=== TESTANDO SITE: {site_desc} ===")

    url = f"{base_url}/proxy/network/api/s/{site_id}/stat/wifi-scanner"

    resp = session.get(url)

    print("HTTP:", resp.status_code)

    try:
        data = resp.json()
        print("Keys:", data.keys())
        print("Data sample:", data.get("data", [])[:1])
    except Exception:
        print("Resposta bruta:", resp.text[:300])
