#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Teste da API WAN Status após limpeza de código duplicado"""

import requests
import json
import time

print("="*80)
print("TESTE: API /api/fortigate/wan/status (após limpeza)")
print("="*80)

# Aguarda servidor ficar pronto
for i in range(5):
    try:
        response = requests.get('http://localhost:5000/', timeout=2)
        if response.status_code == 200:
            print(f"✅ Servidor respondendo ({i+1}ª tentativa)")
            break
    except:
        print(f"⏳ Tentativa {i+1}: Aguardando servidor...")
        time.sleep(1)
else:
    print("❌ Servidor não respondeu")
    exit(1)

# Testa API WAN Status
print("\n🔗 Testando /api/fortigate/wan/status...")
try:
    response = requests.get('http://localhost:5000/api/fortigate/wan/status', timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        print(f"\n✅ Status: {response.status_code}")
        print(f"   Success: {data.get('success')}")
        print(f"   Total WANs: {data.get('total')}")
        print(f"   Online: {data.get('online')}")
        print(f"   Offline: {data.get('offline')}")
        
        print("\n🔗 Detalhes das interfaces WAN:")
        for wan in data.get('wan_interfaces', []):
            print(f"\n  {wan.get('interface')}:")
            print(f"    IP: {wan.get('ip')}")
            print(f"    Status Físico: {wan.get('status_fisico')}")
            print(f"    SLA Status: {wan.get('sla_status')} ⭐")
            print(f"    Status Geral: {wan.get('status_geral')} 🎯")
            print(f"    Saúde: {wan.get('saude')}")
            print(f"    SD-WAN Member ID: {wan.get('sdwan_member_id')}")
    else:
        print(f"❌ Erro HTTP: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Erro na requisição: {str(e)}")
