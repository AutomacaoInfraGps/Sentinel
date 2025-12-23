#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script de teste para verificar VMs e Switches
"""

import json
from pathlib import Path
from datetime import datetime

# Configuração do projeto
PROJECT_ROOT = Path(__file__).parent

print("🔍 Teste de VMs e Switches")
print("=" * 50)

# === TESTE DAS VMs ===
print("\n📱 TESTANDO VMs:")
try:
    # Carrega VMs do arquivo de dados
    vms_file = PROJECT_ROOT / "data" / "vms.json"
    if vms_file.exists():
        with open(vms_file, 'r', encoding='utf-8') as f:
            vms_configuradas = json.load(f)
        print(f"✅ Arquivo VMs carregado: {len(vms_configuradas)} VMs encontradas")
    else:
        vms_configuradas = []
        print("❌ Arquivo de VMs não encontrado")
    
    # Lista as VMs
    for vm in vms_configuradas:
        print(f"   - VM: {vm['name']} ({vm['ip']}) - Regional: {vm.get('regional', 'N/A')}")
    
    # Testa verificação de VM
    if vms_configuradas:
        from vm_manager import verificar_vm_online
        
        vms_online = 0
        vms_offline = 0
        
        for vm in vms_configuradas:
            print(f"\n🔍 Testando VM: {vm['name']} ({vm['ip']})")
            vm_online = verificar_vm_online(vm['ip'])
            
            if vm_online:
                vms_online += 1
                print(f"   ✅ Status: ONLINE")
            else:
                vms_offline += 1
                print(f"   ❌ Status: OFFLINE")
        
        print(f"\n📊 Resultado VMs:")
        print(f"   - Online: {vms_online}")
        print(f"   - Offline: {vms_offline}")
        print(f"   - Total: {len(vms_configuradas)}")
    
except Exception as e:
    print(f"❌ Erro no teste de VMs: {e}")

# === TESTE DOS SWITCHES ===
print("\n🔌 TESTANDO SWITCHES:")
try:
    from gerenciar_switches import GerenciadorSwitches
    
    gerenciador_switches = GerenciadorSwitches()
    print(f"✅ Gerenciador de switches inicializado")
    print(f"   - Switches carregados: {len(gerenciador_switches.switches)}")
    
    # Lista algumas regionais
    regionais = set()
    for switch in gerenciador_switches.switches[:10]:  # Primeiros 10
        regionais.add(switch.get('regional', 'N/A'))
        print(f"   - Switch: {switch['host']} - IP: {switch.get('ip', 'N/A')} - Regional: {switch.get('regional', 'N/A')}")
    
    print(f"\n📍 Regionais encontradas (amostra): {list(regionais)}")
    
    # Testa verificação de alguns switches (limitado para não demorar)
    print(f"\n🔍 Testando verificação de 3 switches...")
    switches_teste = gerenciador_switches.switches[:3]
    
    switches_online = 0
    switches_offline = 0
    
    for switch in switches_teste:
        host_name = switch['host']
        print(f"\n🔍 Testando switch: {host_name}")
        
        try:
            resultado = gerenciador_switches.verificar_switch(host_name)
            status = resultado.get('status', 'offline')
            
            if status in ['online', 'warning']:
                switches_online += 1
                print(f"   ✅ Status: {status.upper()}")
            else:
                switches_offline += 1
                print(f"   ❌ Status: {status.upper()}")
                
        except Exception as e:
            switches_offline += 1
            print(f"   ❌ Erro: {e}")
    
    print(f"\n📊 Resultado Switches (amostra de 3):")
    print(f"   - Online/Warning: {switches_online}")
    print(f"   - Offline/Erro: {switches_offline}")
    print(f"   - Total testados: {len(switches_teste)}")
    print(f"   - Total disponível: {len(gerenciador_switches.switches)}")
    
except Exception as e:
    print(f"❌ Erro no teste de Switches: {e}")

print("\n" + "=" * 50)
print("✅ Teste concluído!")