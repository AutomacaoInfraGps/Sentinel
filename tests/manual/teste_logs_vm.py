#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste da coleta de logs das VMs
"""

import json
from pathlib import Path

print("📋 Teste da Coleta de Logs das VMs")
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
            
            # Testa coleta de relatório com logs
            print(f"\n📊 Coletando relatório com logs...")
            from vm_manager import gerar_relatorio_simples
            
            resultado = gerar_relatorio_simples(
                vm['ip'],
                vm['username'],
                vm['password']
            )
            
            print(f"Resultado: {resultado.get('success', False)}")
            
            if resultado.get('success', False):
                eventos = resultado.get('eventos', [])
                print(f"\n📋 Logs encontrados: {len(eventos)}")
                
                if eventos and not (len(eventos) == 1 and eventos[0].get('error')):
                    print(f"\n📋 Últimos 10 Logs:")
                    print(f"{'Data/Hora':<20} {'Tipo':<12} {'Fonte':<25} {'ID':<8} {'Mensagem':<50}")
                    print("-" * 120)
                    
                    for i, evento in enumerate(eventos[:10]):
                        if not evento.get('error'):
                            data_hora = evento.get('TimeGenerated', 'N/A')[:19]
                            entry_type = evento.get('EntryType', 'N/A')
                            fonte = evento.get('Source', 'N/A')[:23]
                            event_id = str(evento.get('EventID', 'N/A'))[:6]
                            mensagem = evento.get('Message', 'N/A')[:48]
                            
                            print(f"{data_hora:<20} {entry_type:<12} {fonte:<25} {event_id:<8} {mensagem:<50}")
                        
                        if i >= 9:  # Mostra apenas os primeiros 10
                            break
                    
                    # Estatísticas dos logs
                    tipos_eventos = {}
                    for evento in eventos:
                        if not evento.get('error'):
                            tipo = evento.get('EntryType', 'Unknown')
                            tipos_eventos[tipo] = tipos_eventos.get(tipo, 0) + 1
                    
                    print(f"\n📊 Estatísticas dos Logs:")
                    for tipo, count in tipos_eventos.items():
                        icon = '❌' if tipo == 'Error' else '⚠️' if tipo == 'Warning' else 'ℹ️'
                        print(f"   {icon} {tipo}: {count} eventos")
                    
                    # Verifica se os campos estão preenchidos
                    primeiro_evento = eventos[0] if eventos else {}
                    print(f"\n🔍 Verificação do primeiro log:")
                    print(f"   - Data/Hora: {primeiro_evento.get('TimeGenerated', 'VAZIO')}")
                    print(f"   - Tipo: {primeiro_evento.get('EntryType', 'VAZIO')}")
                    print(f"   - Fonte: {primeiro_evento.get('Source', 'VAZIO')}")
                    print(f"   - Event ID: {primeiro_evento.get('EventID', 'VAZIO')}")
                    print(f"   - Mensagem: {primeiro_evento.get('Message', 'VAZIO')[:100]}...")
                    
                else:
                    print(f"❌ Nenhum log válido encontrado")
                    if eventos:
                        print(f"   Primeiro item: {eventos[0]}")
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