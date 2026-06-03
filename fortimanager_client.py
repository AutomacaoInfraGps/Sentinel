#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import urllib3
from config import ENV_CONFIG

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FortiManagerClientError(RuntimeError):
    pass


class FortiManagerClient:
    def __init__(self, host=None, port=None, username=None, password=None):
        cfg = ENV_CONFIG.get("fortimanager", {}) if isinstance(ENV_CONFIG.get("fortimanager", {}), dict) else {}
        self.host = host or cfg.get("host")
        self.port = port or cfg.get("port", 443)
        self.username = username or cfg.get("username")
        self.password = password or cfg.get("password")
        self.base_url = f"https://{self.host}:{self.port}/jsonrpc"
        self.session = requests.Session()
        self.session.verify = False
        self.sessionid = None

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
        if not self.sessionid:
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

    def get_device_sdwan(self, device_name):
        return self._request("get", f"/pm/config/device/{device_name}/global/router/sdwan", {})
