#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Teste completo: gerenciador_fortigate SLA method"""

from gerenciar_fortigate import GerenciadorFortigate
import json

print("="*80)
print("TESTE: Método obter_membros_sdwan_com_sla() - Debug detalhado")
print("="*80)

gf = GerenciadorFortigate()

print("\n🔐 Autenticando...")
if gf.autenticar():
    print("✅ Autenticação OK\n")
    
    print("🔍 Chamando obter_membros_sdwan_com_sla()...")
    result = gf.obter_membros_sdwan_com_sla()
    
    if result.get('success'):
        print("✅ Método retornou sucesso\n")
        
        membros = result.get('membros', [])
        print(f"📊 Total de membros: {len(membros)}\n")
        
        for membro in membros:
            print(f"  {membro.get('interface')}:")
            print(f"    Member ID: {membro.get('member_id')}")
            print(f"    IP: {membro.get('ip')}")
            print(f"    SLA Status: {membro.get('sla_status')} ⭐⭐⭐")
            print(f"    Link UP: {membro.get('link_up')}")
            print(f"    Status: {membro.get('status')}")
            print(f"    SLA Data: {membro.get('sla_data')}")
            print()
    else:
        print(f"❌ Erro: {result.get('message')}\n")
        print(json.dumps(result, indent=2))
else:
    print("❌ Falha na autenticação")
