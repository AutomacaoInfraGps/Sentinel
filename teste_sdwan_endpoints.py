#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inspeciona endpoints de monitoramento SD-WAN/virtual-wan-link"""

from gerenciar_fortigate import GerenciadorFortigate
import json

endpoints = [
    "/monitor/sdwan/health-check",
    "/monitor/sdwan/service",
    "/monitor/sdwan/status",
    "/monitor/virtual-wan-link/health-check",
    "/monitor/virtual-wan-link/service",
    "/monitor/virtual-wan-link/status"
]

gf = GerenciadorFortigate()
if not gf.autenticar():
    print("Falha na autenticacao")
    raise SystemExit(1)

for ep in endpoints:
    url = f"{gf.base_url}{ep}"
    try:
        r = gf.session.get(url, headers={"Accept": "application/json"}, timeout=10)
    except Exception as e:
        print(f"{ep} -> erro: {e}")
        continue

    print(f"\n{ep} -> {r.status_code}")
    if r.status_code != 200:
        continue

    try:
        data = r.json()
    except Exception:
        print("  resposta nao-json")
        continue

    if isinstance(data, dict):
        keys = list(data.keys())
        print(f"  keys: {keys[:10]}")
        results = data.get("results") or data.get("result") or data.get("data") or data.get("entries")
        if isinstance(results, list) and results:
            print("  sample:")
            print(json.dumps(results[0], indent=2, ensure_ascii=False)[:1000])
        elif isinstance(results, dict):
            print("  sample:")
            print(json.dumps(results, indent=2, ensure_ascii=False)[:1000])
        else:
            print("  sample:")
            print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
    elif isinstance(data, list):
        print(f"  list size: {len(data)}")
        if data:
            print("  sample:")
            print(json.dumps(data[0], indent=2, ensure_ascii=False)[:1000])
