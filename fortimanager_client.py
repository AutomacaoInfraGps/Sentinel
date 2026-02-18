#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import urllib3
from config import ENV_CONFIG

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        self.sessionid = data.get("session")
        return data

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
        return response.json()

    def list_adoms(self):
        return self._request("get", "/dvmdb/adom")

    def list_devices(self, adom="root"):
        return self._request("get", f"/dvmdb/adom/{adom}/device")

    def list_device_interfaces(self, adom, device_name):
        return self._request("get", f"/pm/config/adom/{adom}/device/{device_name}/global/system/interface", {})
