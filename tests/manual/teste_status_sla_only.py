#!/usr/bin/env python3
"""Teste da nova lógica: Status baseado APENAS em SLA, sem teste de IP"""

from gerenciar_fortigate import GerenciadorFortigate
import json

print("=" * 80)
print("TESTE: Status Baseado APENAS em SLA (Sem Teste de IP)")
print("=" * 80)

gf = GerenciadorFortigate()
if gf.autenticar():
    print("\n✅ Autenticação bem-sucedida\n")
    
    # Obter membros do SD-WAN com SLA
    print("🔍 Obtendo membros SD-WAN com status SLA...")
    sdwan_result = gf.obter_membros_sdwan_com_sla()
    
    print("\n" + "=" * 80)
    print("RESULTADO:")
    print("=" * 80)
    
    if sdwan_result.get("success"):
        membros = sdwan_result.get("membros", [])
        print(f"\n✅ Total de membros: {len(membros)}\n")
        
        for membro in membros:
            interface = membro.get('interface', 'N/A')
            ip = membro.get('ip', 'N/A')
            sla_status = membro.get('sla_status', 'unknown')
            status = membro.get('status', 'unknown')
            
            # Determinar cor/emoji baseado em SLA
            if sla_status == "active":
                status_icon = "✅ ONLINE"
            elif sla_status == "inactive":
                status_icon = "❌ OFFLINE"
            else:
                status_icon = "❓ UNKNOWN"
            
            print(f"🔗 {interface}:")
            print(f"   IP: {ip}")
            print(f"   SLA Status: {sla_status}")
            print(f"   Status Geral: {status_icon}")
            print(f"   Member ID: {membro.get('member_id', 'N/A')}")
            print(f"   Prioridade: {membro.get('priority', 'N/A')}")
            print()
    else:
        print(f"\n❌ Erro: {sdwan_result.get('message')}")

    print("\n" + "=" * 80)
    print("OBSERVAÇÃO IMPORTANTE:")
    print("=" * 80)
    print("""
✅ Status ONLINE: Apenas quando SLA está ATIVO no SD-WAN
❌ Status OFFLINE: Apenas quando SLA está INATIVO no SD-WAN

⚠️ NÃO está testando IP da operadora (que bloqueia todas)
⚠️ Fonte de verdade: Status SLA do SD-WAN/Interface física UP/DOWN
    """)
else:
    print("❌ Falha na autenticação")
