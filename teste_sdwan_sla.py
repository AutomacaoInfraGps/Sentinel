#!/usr/bin/env python3
"""Teste do novo endpoint API WAN com SD-WAN e SLA"""

from gerenciar_fortigate import GerenciadorFortigate
import json

print("=" * 80)
print("TESTE: Novo Endpoint WAN com SD-WAN e SLA")
print("=" * 80)

gf = GerenciadorFortigate()
if gf.autenticar():
    print("\n✅ Autenticação bem-sucedida\n")
    
    # Teste do novo método
    print("🔍 Testando obter_membros_sdwan_com_sla()...")
    sdwan_result = gf.obter_membros_sdwan_com_sla()
    
    print("\n📊 Resultado SD-WAN:")
    print(json.dumps(sdwan_result, indent=2, default=str))
    
    print("\n" + "=" * 80)
    print("Informações Obtidas:")
    print("=" * 80)
    
    if sdwan_result.get("success"):
        membros = sdwan_result.get("membros", [])
        print(f"\n✅ Total de membros encontrados: {len(membros)}")
        
        for membro in membros:
            print(f"\n🔗 {membro.get('interface', 'N/A')}:")
            print(f"   ID: {membro.get('member_id', 'N/A')}")
            print(f"   Prioridade: {membro.get('priority', 'N/A')}")
            print(f"   Status: {membro.get('status', 'N/A')}")
            print(f"   SLA Status: {membro.get('sla_status', 'N/A')}")
            if membro.get('ip'):
                print(f"   IP: {membro.get('ip')}")
            sla_data = membro.get('sla_data', {})
            if sla_data:
                print(f"   SLA Dados: {sla_data}")
    else:
        print(f"\n❌ Erro: {sdwan_result.get('message')}")
else:
    print("❌ Falha na autenticação")
