#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste das correções nos processos das VMs
"""

import json
from pathlib import Path

print("🔄 Teste das Correções nos Processos das VMs")
print("=" * 60)

# Carrega configuração da VM
vms_file = Path("data/vms.json")
if vms_file.exists():
    with open(vms_file, 'r', encoding='utf-8') as f:
        vms = json.load(f)
    
    if vms:
        vm = vms[0]  # Testa a primeira VM
        print(f"🔍 Testando VM: {vm['name']} ({vm['ip']})")
        
        # Testa conectividade básica
        print(f"\n📡 Testando conectividade...")
        from vm_manager import verificar_vm_online
        
        if verificar_vm_online(vm['ip']):
            print(f"✅ VM está online!")
            
            # Testa coleta de relatório com processos corrigidos
            print(f"\n📊 Coletando relatório com processos corrigidos...")
            from vm_manager import gerar_relatorio_simples
            
            resultado = gerar_relatorio_simples(
                vm['ip'],
                vm['username'],
                vm['password']
            )
            
            print(f"Resultado: {resultado.get('success', False)}")
            
            if resultado.get('success', False):
                processos = resultado.get('processos', [])
                print(f"\n🔄 Processos encontrados: {len(processos)}")
                
                if processos and not (len(processos) == 1 and processos[0].get('error')):
                    print(f"\n📋 Top 10 Processos:")
                    print(f"{'Nome':<20} {'PID':<8} {'CPU':<8} {'Memória (MB)':<12}")
                    print("-" * 50)
                    
                    for i, processo in enumerate(processos[:10]):
                        if not processo.get('error'):
                            nome = processo.get('Name', 'N/A')[:18]
                            pid = processo.get('Id', 'N/A')
                            cpu = processo.get('CPU', 0)
                            memory = processo.get('Memory', 0)
                            
                            print(f"{nome:<20} {pid:<8} {cpu:<8} {memory:<12}")
                        
                        if i >= 9:  # Mostra apenas os primeiros 10
                            break
                    
                    # Verifica se os campos estão preenchidos
                    primeiro_processo = processos[0] if processos else {}
                    print(f"\n🔍 Verificação do primeiro processo:")
                    print(f"   - Nome: {primeiro_processo.get('Name', 'VAZIO')}")
                    print(f"   - PID (Id): {primeiro_processo.get('Id', 'VAZIO')}")
                    print(f"   - CPU: {primeiro_processo.get('CPU', 'VAZIO')}")
                    print(f"   - Memory: {primeiro_processo.get('Memory', 'VAZIO')}")
                    print(f"   - PrivateMemory: {primeiro_processo.get('PrivateMemory', 'VAZIO')}")
                    print(f"   - Handles: {primeiro_processo.get('Handles', 'VAZIO')}")
                    print(f"   - Threads: {primeiro_processo.get('Threads', 'VAZIO')}")
                    
                else:
                    print(f"❌ Nenhum processo válido encontrado")
                    if processos:
                        print(f"   Primeiro item: {processos[0]}")
            else:
                print(f"❌ Falha ao coletar relatório: {resultado.get('message', 'Erro desconhecido')}")
        else:
            print(f"❌ VM não está acessível")
    else:
        print("❌ Nenhuma VM encontrada no arquivo")
else:
    print("❌ Arquivo de VMs não encontrado")

print("\n" + "=" * 60)
print("✅ Teste concluído!")