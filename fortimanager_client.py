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
        Retorna mapa interface_name -> dados runtime da interface.
        """
        ifaces_raw = {}
        last_error = None

        for resource in (
            "/api/v2/monitor/system/interface",
            "/api/v2/monitor/system/interface/select",
        ):
            payload = {
                "id": 1,
                "method": "exec",
                "params": [
                    {
                        "url": "/sys/proxy/json",
                        "data": {
                            "target": [f"adom/{adom}/device/{device_name}"],
                            "action": "get",
                            "resource": resource,
                        },
                    }
                ],
                "session": self.sessionid,
            }
            response = self.session.post(self.base_url, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            result_list = data.get("result", [])
            if result_list:
                status = result_list[0].get("status", {}) if isinstance(result_list[0], dict) else {}
                if status.get("code") not in (0, None):
                    last_error = f"{resource}: {status.get('message', 'erro')} (code={status.get('code')})"
                    continue

            # O proxy encapsula a resposta em data[0].data[0].response
            outer = result_list[0] if result_list and isinstance(result_list[0], dict) else {}
            proxy_data_list = outer.get("data", [])
            proxy_entry = proxy_data_list[0] if proxy_data_list and isinstance(proxy_data_list[0], dict) else {}
            response_body = proxy_entry.get("response", proxy_entry)
            ifaces_raw = response_body.get("results", {}) if isinstance(response_body, dict) else {}
            if ifaces_raw:
                break

        if not ifaces_raw and last_error:
            raise FortiManagerClientError(last_error)

        result = {}
        for iface_name, iface_data in (ifaces_raw or {}).items():
            if not isinstance(iface_data, dict):
                continue
            ip_raw = str(iface_data.get("ip") or "").strip()
            mask_raw = str(iface_data.get("mask") or "").strip()
            status_raw = iface_data.get("status") or iface_data.get("link") or iface_data.get("state")
            item = dict(iface_data)
            item.setdefault("name", iface_name)
            item.setdefault("interface", iface_name)
            if mask_raw and ip_raw and "/" not in ip_raw and " " not in ip_raw:
                item["ip"] = f"{ip_raw} {mask_raw}"
            if ip_raw and ip_raw not in {"0.0.0.0", "N/A", "None", ""}:
                item["ip_publico_status"] = ""
            if status_raw is not None:
                item["status"] = status_raw
            result[iface_name.strip().lower()] = item
        return result

    def get_device_sdwan(self, device_name):
        for path in (
            f"/pm/config/device/{device_name}/global/router/sdwan",
            f"/pm/config/device/{device_name}/global/system/sdwan",
        ):
            try:
                return self._request("get", path, {})
            except FortiManagerClientError:
                continue
        return {}

    @staticmethod
    def _normalize_sdwan_status(value):
        if value is None:
            return "unknown"
        text = str(value).strip().lower()
        if text in {"up", "alive", "active", "ok", "good", "excellent", "pass", "reachable", "healthy", "health", "1", "true"}:
            return "active"
        if text in {"down", "dead", "inactive", "fail", "failed", "timeout", "unreachable", "poor", "bad", "0", "false"}:
            return "inactive"
        return "unknown"

    @staticmethod
    def _walk_dicts(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from FortiManagerClient._walk_dicts(child)
        elif isinstance(value, list):
            for item in value:
                yield from FortiManagerClient._walk_dicts(item)

    @staticmethod
    def _proxy_response_body(payload):
        result_list = payload.get("result", []) if isinstance(payload, dict) else []
        if not result_list:
            return {}
        outer = result_list[0] if isinstance(result_list[0], dict) else {}
        proxy_data_list = outer.get("data", [])
        proxy_entry = proxy_data_list[0] if proxy_data_list and isinstance(proxy_data_list[0], dict) else {}
        entry_status = proxy_entry.get("status", {})
        if isinstance(entry_status, dict) and entry_status.get("code", 0) not in (0, None):
            raise FortiManagerClientError(entry_status.get("message") or "erro_proxy")
        return proxy_entry.get("response", proxy_entry)

    def proxy_monitor_sdwan(self, adom: str, device_name: str) -> dict:
        """Consulta status SD-WAN/SLA no FortiGate usando o proxy do FortiManager."""
        endpoints = (
            "/api/v2/monitor/virtual-wan/health-check",
            "/api/v2/monitor/sdwan/health-check",
            "/api/v2/monitor/sdwan/service",
            "/api/v2/monitor/sdwan/status",
            "/api/v2/monitor/virtual-wan-link/health-check",
            "/api/v2/monitor/virtual-wan-link/service",
            "/api/v2/monitor/virtual-wan-link/status",
        )

        mapping = {}
        data_map = {}
        last_error = None

        for resource in endpoints:
            payload = {
                "id": 1,
                "method": "exec",
                "params": [{
                    "url": "/sys/proxy/json",
                    "data": {
                        "target": [f"adom/{adom}/device/{device_name}"],
                        "action": "get",
                        "resource": resource,
                    },
                }],
                "session": self.sessionid,
            }
            try:
                response = self.session.post(self.base_url, json=payload, timeout=20)
                response.raise_for_status()
                body = self._proxy_response_body(response.json())
            except Exception as exc:
                last_error = str(exc)
                continue

            results = body.get("results") if isinstance(body, dict) else body
            if isinstance(results, dict):
                aggregated = {}
                aggregated_data = {}
                for health_name, iface_map in results.items():
                    if not isinstance(iface_map, dict):
                        continue
                    for iface_name, iface_data in iface_map.items():
                        if not isinstance(iface_data, dict):
                            continue
                        status = self._normalize_sdwan_status(
                            iface_data.get("status")
                            or iface_data.get("state")
                            or iface_data.get("health")
                        )
                        if status == "unknown":
                            continue
                        iface_key = str(iface_name).strip().upper()
                        if not iface_key:
                            continue
                        aggregated.setdefault(iface_key, []).append(status)
                        aggregated_data.setdefault(iface_key, {})[str(health_name)] = iface_data

                for iface_key, statuses in aggregated.items():
                    if any(status == "active" for status in statuses):
                        mapping[iface_key] = "active"
                    elif statuses and all(status == "inactive" for status in statuses):
                        mapping[iface_key] = "inactive"
                    data_map[iface_key] = aggregated_data.get(iface_key, {})

            for item in self._walk_dicts(results):
                iface = (
                    item.get("interface")
                    or item.get("ifname")
                    or item.get("member")
                    or item.get("member_name")
                    or item.get("name")
                    or item.get("link")
                    or item.get("link_name")
                )
                if not iface:
                    continue
                status_value = (
                    item.get("sla_status")
                    or item.get("health_status")
                    or item.get("health-check-status")
                    or item.get("status")
                    or item.get("state")
                    or item.get("health")
                    or item.get("link")
                )
                status = self._normalize_sdwan_status(status_value)
                iface_key = str(iface).strip().upper()
                if iface_key and status != "unknown":
                    mapping[iface_key] = status
                    data_map[iface_key] = item

            if mapping:
                return {"success": True, "mapping": mapping, "data": data_map, "source": resource}

        return {"success": False, "mapping": {}, "data": {}, "source": None, "message": last_error}

    def proxy_sdwan_members_with_sla(self, adom: str, device_name: str) -> dict:
        """Monta membros SD-WAN com status SLA usando apenas FortiManager/proxy."""
        sdwan_monitor = self.proxy_monitor_sdwan(adom, device_name)
        sla_by_interface = sdwan_monitor.get("mapping", {})
        sla_data_by_interface = sdwan_monitor.get("data", {})

        members = []
        try:
            config = self.get_device_sdwan(device_name)
        except Exception:
            config = {}

        for item in self._walk_dicts(config):
            raw_members = item.get("members")
            if not isinstance(raw_members, list):
                continue
            for member in raw_members:
                if not isinstance(member, dict):
                    continue
                iface = member.get("interface") or member.get("name")
                if isinstance(iface, dict):
                    iface = iface.get("name") or iface.get("interface") or iface.get("q_origin_key")
                iface_text = str(iface or "").strip()
                if not iface_text:
                    continue
                iface_key = iface_text.upper()
                members.append({
                    "member_id": member.get("_id", member.get("id", member.get("seq-num", "unknown"))),
                    "interface": iface_text,
                    "priority": member.get("priority", 0),
                    "sla_status": sla_by_interface.get(iface_key, "unknown"),
                    "status": sla_by_interface.get(iface_key, "unknown"),
                    "sla_data": sla_data_by_interface.get(iface_key, {}),
                    "source": sdwan_monitor.get("source"),
                })
            if members:
                break

        if not members and sla_by_interface:
            for iface_key, sla_status in sla_by_interface.items():
                members.append({
                    "member_id": "unknown",
                    "interface": iface_key,
                    "priority": 0,
                    "sla_status": sla_status,
                    "status": sla_status,
                    "sla_data": sla_data_by_interface.get(iface_key, {}),
                    "source": sdwan_monitor.get("source"),
                })

        return {
            "success": bool(members),
            "membros": members,
            "source": sdwan_monitor.get("source"),
            "message": sdwan_monitor.get("message"),
        }

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
        try:
            response = self.session.post(self.base_url, json=payload, timeout=20)
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            return {"_erro": "timeout", "_detalhe": str(exc)}
        except requests.exceptions.RequestException as exc:
            return {"_erro": "erro_consulta", "_detalhe": str(exc)}
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
                return {"_erro": "offline", "_detalhe": msg or "FortiManager sem tunel com o firewall"}
            return {"_erro": "erro_proxy", "_detalhe": msg or "Erro no proxy do FortiManager"}

        response_body = proxy_entry.get("response", proxy_entry)

        # Extrai licenças da resposta
        licenses = response_body.get("results", {}) if isinstance(response_body, dict) else {}
        return licenses if licenses else {}

    def request_raw(self, method: str, url: str, data=None) -> dict:
        """Executa uma chamada JSON-RPC bruta para diagnosticos pontuais."""
        payload = {
            "id": 1,
            "method": method,
            "params": [
                {
                    "url": url,
                    "data": data or {},
                }
            ],
            "session": self.sessionid,
        }
        response = self.session.post(self.base_url, json=payload, timeout=20)
        response.raise_for_status()
        return response.json()

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

