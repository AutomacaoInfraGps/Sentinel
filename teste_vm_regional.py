#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste da nova configuração de regionais das VMs
"""

import json
from pathlib import Path

print("🖥️ Teste da Configuração de Regionais das VMs")
print("=" * 50)

# Carrega VMs
vms_file = Path("data/vms.json")
if vms_file.exists():
    with open(vms_file, 'r', encoding='utf-8') as f:
        vms = json.load(f)
    
    print(f"✅ {len(vms)} VM(s) carregada(s):")
    
    for vm in vms:
        print(f"\n📱 VM: {vm['name']}")
        print(f"   IP: {vm['ip']}")
        print(f"   Regional: {vm['regional']}")
        print(f"   Tipo: {vm.get('tipo', 'N/A')}")
        print(f"   Grupo: {vm.get('grupo', 'N/A')}")
        print(f"   Descrição: {vm.get('description', 'N/A')}")
else:
    print("❌ Arquivo de VMs não encontrado")

# Testa o gerenciador
print(f"\n🔧 Testando Gerenciador de VMs:")
try:
    from gerenciar_vms import GerenciadorVMsLocal
    
    gerenciador = GerenciadorVMsLocal()
    print(f"✅ Gerenciador inicializado")
    
    # Lista VMs
    gerenciador.listar_vms()
    
except Exception as e:
    print(f"❌ Erro: {e}")

print("\n" + "=" * 50)
print("✅ Teste concluído!")