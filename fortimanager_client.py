#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import urllib3
from config import ENV_CONFIG

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FortiManagerClientError(RuntimeError):
    pass


class FortiManagerClient:
    def __init__(self, host=None, port=None, username=None, password=None, api_key=None):
        cfg = ENV_CONFIG.get("fortimanager", {}) if isinstance(ENV_CONFIG.get("fortimanager", {}), dict) else {}
        self.host = host or cfg.get("host")
        self.port = port or cfg.get("port", 443)
        self.username = username or cfg.get("username")
        self.password = password or cfg.get("password")
        self.api_key = api_key or cfg.get("api_key") or cfg.get("apikey")
        self.base_url = f"https://{self.host}:{self.port}/jsonrpc"
        self.session = requests.Session()
        self.session.verify = False
        self.sessionid = None
        # Se API key disponível, injeta header — não precisa de login/logout
        if self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    @staticmethod
    def _extract_status(payload):
        result = payload.get("result", []) if isinstance(payload, dict) else []
        if not result:
            return 0, "OK"

        status = result[0].get("status", {}) if isinstance(result[0], dict) else {}
        code = status.get("code", 0)
        message = status.get("message", "OK")
        return code, message

    @classmethod
    def _ensure_success(cls, payload, operation):
        code, message = cls._extract_status(payload)
        if code not in (0, None):
            raise FortiManagerClientError(f"{operation}: {message} (code={code})")
        return payload

    def login(self):
        # API key via Bearer header não requer sessão de login
        if self.api_key:
            return {"session": None}

        payload = {
            "id": 1,
            "method": "exec",
            "params": [
                {
                    "url": "/sys/login/user",
                    "data": {
                        "user": self.username,
                        "passwd": self.password
                    }
                }
            ]
        }
        response = self.session.post(self.base_url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        self._ensure_success(data, "Falha no login do FortiManager")
        self.sessionid = data.get("session")
        return data

    def logout(self):
        # API key não usa sessão
        if self.api_key or not self.sessionid:
            return None

        payload = {
            "id": 1,
            "method": "exec",
            "params": [
                {
                    "url": "/sys/logout"
                }
            ],
            "session": self.sessionid
        }

        try:
            response = self.session.post(self.base_url, json=payload, timeout=15)
            response.raise_for_status()
            return response.json()
        finally:
            self.sessionid = None

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.logout()
        return False

    def _request(self, method, url, data=None):
        payload = {
            "id": 1,
            "method": method,
            "params": [
                {
                    "url": url,
                    "data": data or {}
                }
            ],
            "session": self.sessionid
        }
        response = self.session.post(self.base_url, json=payload, timeout=20)
        response.raise_for_status()
        return self._ensure_success(response.json(), f"Falha ao consultar {url}")

    def list_adoms(self):
        return self._request("get", "/dvmdb/adom")

    def list_devices(self, adom="root"):
        return self._request("get", f"/dvmdb/adom/{adom}/device")

    def list_device_interfaces(self, adom, device_name):
        return self._request("get", f"/pm/config/device/{device_name}/global/system/interface", {})

    def proxy_monitor_interfaces(self, adom: str, device_name: str) -> dict:
        """Consulta /api/v2/monitor/system/interface no dispositivo via proxy do FortiManager.
        Retorna mapa interface_name -> {ip, mask} com IPs runtime (PPPoE/DHCP).
        """
        payload = {
            "id": 1,
            "method": "exec",
            "params": [
                {
                    "url": "/sys/proxy/json",
                    "data": {
                        "target": [f"adom/{adom}/device/{device_name}"],
                        "action": "get",
                        "resource": "/api/v2/monitor/system/interface",
                    },
                }
            ],
            "session": self.sessionid,
        }
        response = self.session.post(self.base_url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        result_list = data.get("result", [])
        if not result_list:
            return {}
        # O proxy encapsula a resposta em data[0].data[0].response
        outer = result_list[0] if isinstance(result_list[0], dict) else {}
        proxy_data_list = outer.get("data", [])
        if not proxy_data_list:
            return {}
        proxy_entry = proxy_data_list[0] if isinstance(proxy_data_list[0], dict) else {}
        response_body = proxy_entry.get("response", proxy_entry)
        ifaces_raw = response_body.get("results", {}) if isinstance(response_body, dict) else {}
        result = {}
        for iface_name, iface_data in (ifaces_raw or {}).items():
            ip_raw = str(iface_data.get("ip") or "").strip()
            mask_raw = str(iface_data.get("mask") or "").strip()
            if ip_raw and ip_raw not in {"0.0.0.0", "N/A", "None", ""}:
                result[iface_name.strip().lower()] = {"ip": ip_raw, "mask": mask_raw}
        return result

    def get_device_sdwan(self, device_name):
        return self._request("get", f"/pm/config/device/{device_name}/global/router/sdwan", {})

    def proxy_monitor_traffic(self, adom: str, device_name: str, interval_s: float = 2.0) -> dict:
        """Retorna download/upload em bps para cada interface, calculado via duas amostras.
        Retorna: {interface_name: {rx_bps, tx_bps, speed_mbps}}
        """
        import time

        def _snapshot():
            payload = {
                "id": 1, "method": "exec",
                "params": [{"url": "/sys/proxy/json", "data": {
                    "target": [f"adom/{adom}/device/{device_name}"],
                    "action": "get",
                    "resource": "/api/v2/monitor/system/interface/select"
                }}]
            }
            r = self.session.post(self.base_url, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            result = data.get("result", [{}])[0]
            if result.get("status", {}).get("code", 0) != 0:
                return None
            proxy_data = result.get("data", [])
            if not proxy_data:
                return {}
            resp = proxy_data[0].get("response", {}) if isinstance(proxy_data[0], dict) else {}
            return resp.get("results", {}) if isinstance(resp, dict) else {}

        s1 = _snapshot()
        t1 = time.time()
        if s1 is None:
            return {}
        time.sleep(interval_s)
        s2 = _snapshot()
        t2 = time.time()
        if s2 is None:
            return {}
        dt = max(t2 - t1, 0.1)

        result = {}
        for iface, data2 in (s2 or {}).items():
            data1 = (s1 or {}).get(iface, {})
            rx_bps = max(0, (data2.get("rx_bytes", 0) - data1.get("rx_bytes", 0)) / dt * 8)
            tx_bps = max(0, (data2.get("tx_bytes", 0) - data1.get("tx_bytes", 0)) / dt * 8)
            speed = data2.get("speed")
            result[iface.strip().lower()] = {
                "rx_bps": rx_bps,
                "tx_bps": tx_bps,
                "speed_mbps": float(speed) if speed else None,
                "rx_bytes": data2.get("rx_bytes", 0),
                "tx_bytes": data2.get("tx_bytes", 0),
            }
        return result

    def proxy_monitor_license(self, adom: str, device_name: str) -> dict:
        """Consulta /api/v2/monitor/license/status no dispositivo via proxy do FortiManager.
        Retorna informações de licenças com status de expiração.
        Em caso de falha de túnel (device offline), retorna {'_erro': 'offline'}.
        """
        payload = {
            "id": 1,
            "method": "exec",
            "params": [
                {
                    "url": "/sys/proxy/json",
                    "data": {
                        "target": [f"adom/{adom}/device/{device_name}"],
                        "action": "get",
                        "resource": "/api/v2/monitor/license/status",
                    },
                }
            ],
            "session": self.sessionid,
        }
        response = self.session.post(self.base_url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        result_list = data.get("result", [])
        if not result_list:
            return {}

        # O proxy encapsula a resposta em result[0].data[0].response
        outer = result_list[0] if isinstance(result_list[0], dict) else {}
        proxy_data_list = outer.get("data", [])
        if not proxy_data_list:
            return {}

        proxy_entry = proxy_data_list[0] if isinstance(proxy_data_list[0], dict) else {}

        # Detectar erro de túnel (device offline/sem conexão com o FortiManager)
        entry_status = proxy_entry.get("status", {})
        if isinstance(entry_status, dict) and entry_status.get("code", 0) != 0:
            msg = entry_status.get("message", "")
            if "No tunnel" in msg or "tunnel" in msg.lower():
                return {"_erro": "offline"}
            return {"_erro": msg or "erro_proxy"}

        response_body = proxy_entry.get("response", proxy_entry)

        # Extrai licenças da resposta
        licenses = response_body.get("results", {}) if isinstance(response_body, dict) else {}
        return licenses if licenses else {}

    def get_device_info(self, adom="root"):
        """Retorna lista de dispositivos com informações básicas (name, hostname, model, serialnumber, status).
        """
        result = self._request("get", f"/dvmdb/adom/{adom}/device")
        if not isinstance(result, dict):
            return {}
        
        devices_list = result.get("result", [])
        if not devices_list:
            return {}
        
        devices_data = devices_list[0] if isinstance(devices_list[0], dict) else {}
        return devices_data

    # ------------------------------------------------------------------
    # Monitoramento de usuários admin
    # ------------------------------------------------------------------
    def get_fortimanager_admins(self) -> list:
        """Retorna lista de userids admin do próprio FortiManager."""
        payload = {
            "id": 1,
            "method": "get",
            "params": [{"url": "/cli/global/system/admin/user",
                        "option": ["get flags", "loadsub", "extra info"]}],
            "session": self.sessionid,
        }
        resp = self.session.post(self.base_url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result0 = data.get("result", [{}])[0] if data.get("result") else {}
        status = result0.get("status", {})
        code = status.get("code", 0)
        if code not in (0, None):
            raise PermissionError(
                f"FortiManager: sem permissão para listar admins "
                f"(code={code}, msg={status.get('message', '')}). "
                f"A API key precisa ter perfil de acesso com leitura em System Settings."
            )
        users = result0.get("data", [])
        if isinstance(users, list):
            return sorted(set(
                u.get("userid", u.get("name", "")).strip()
                for u in users if isinstance(u, dict) and (u.get("userid") or u.get("name"))
            ))
        return []

    def get_fortigate_admins(self, device_name: str, adom: str) -> list | None:
        """
        Retorna lista de nomes de admin de um FortiGate via proxy do FortiManager.
        Retorna None se o dispositivo estiver offline/sem túnel.
        """
        payload = {
            "id": 1,
            "method": "exec",
            "params": [{
                "url": "/sys/proxy/json",
                "data": {
                    "target": [f"adom/{adom}/device/{device_name}"],
                    "action": "get",
                    "resource": "/api/v2/cmdb/system/admin",
                },
            }],
            "session": self.sessionid,
        }
        resp = self.session.post(self.base_url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        result_list = data.get("result", [])
        if not result_list:
            return []

        outer = result_list[0] if isinstance(result_list, list) else {}
        proxy_data = outer.get("data", [])
        if not proxy_data:
            return None  # sem dados → provavelmente offline

        proxy_entry = proxy_data[0] if isinstance(proxy_data, list) else proxy_data
        entry_status = proxy_entry.get("status", {})
        if isinstance(entry_status, dict) and entry_status.get("code", 0) != 0:
            msg = entry_status.get("message", "")
            if "No tunnel" in msg or "tunnel" in msg.lower() or "offline" in msg.lower():
                return None  # offline
            return []

        response_body = proxy_entry.get("response", {})
        admins_raw = response_body.get("results", []) if isinstance(response_body, dict) else []
        return sorted(set(
            a.get("name", "").strip()
            for a in admins_raw if isinstance(a, dict) and a.get("name")
        ))

