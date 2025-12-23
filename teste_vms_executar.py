#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste da seção de VMs do executar_tudo.py
"""

import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent

print("🖥️ Teste da Seção de VMs")
print("=" * 50)

# === TESTE DAS VMs (mesmo código do executar_tudo.py) ===
vms_data = []
vms_online = 0
vms_offline = 0
relatorio_vms = ""

try:
    # Carrega VMs do arquivo de dados
    vms_file = PROJECT_ROOT / "data" / "vms.json"
    if vms_file.exists():
        with open(vms_file, 'r', encoding='utf-8') as f:
            vms_configuradas = json.load(f)
    else:
        vms_configuradas = []
    
    from vm_manager import verificar_vm_online
    
    for vm in vms_configuradas:
        try:
            print(f"[EXEC] Verificando VM {vm['name']} ({vm['ip']})")
            
            # Verifica se a VM está online
            vm_online = verificar_vm_online(vm['ip'])
            
            if vm_online:
                vms_online += 1
                status = "online"
            else:
                vms_offline += 1
                status = "offline"
                
            vms_data.append({
                'name': vm['name'],
                'ip': vm['ip'],
                'regional': vm.get('regional', 'N/A'),
                'status': status,
                'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        except Exception as e:
            print(f"[ERRO] Erro ao verificar VM {vm['name']}: {e}")
            vms_offline += 1
            vms_data.append({
                'name': vm['name'],
                'ip': vm['ip'],
                'regional': vm.get('regional', 'N/A'),
                'status': 'error',
                'error': str(e),
                'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
    
    # Gera HTML das VMs
    relatorio_vms = "<div class='vms-container'>"
    for vm in vms_data:
        status_class = "success" if vm['status'] == 'online' else "danger"
        relatorio_vms += f"""
        <div class="vm-item mb-3">
            <div class="card">
                <div class="card-header bg-{status_class} text-white">
                    <h5 class="mb-0">{vm['name']}</h5>
                </div>
                <div class="card-body">
                    <p><strong>IP:</strong> {vm['ip']}</p>
                    <p><strong>Regional:</strong> {vm['regional']}</p>
                    <p><strong>Status:</strong> {vm['status']}</p>
                    <p><strong>Última verificação:</strong> {vm['last_check']}</p>
                    {f"<p><strong>Erro:</strong> {vm['error']}</p>" if vm.get('error') else ""}
                </div>
            </div>
        </div>
        """
    relatorio_vms += "</div>"
    
except Exception as e:
    print(f"[ERRO] Erro no módulo de VMs: {e}")

# Debug das VMs após processamento
print(f"\n🔍 Debug VMs (após processamento):")
print(f"   - VMs configuradas encontradas: {len(vms_configuradas) if 'vms_configuradas' in locals() else 0}")
print(f"   - VMs processadas: {len(vms_data)}")
print(f"   - VMs Online: {vms_online}")
print(f"   - VMs Offline: {vms_offline}")
if vms_data:
    for vm in vms_data:
        print(f"   - VM: {vm['name']} - Regional: {vm['regional']} - Status: {vm['status']}")

print(f"\n📄 HTML gerado:")
print(relatorio_vms[:500] + "..." if len(relatorio_vms) > 500 else relatorio_vms)

print("\n" + "=" * 50)
print("✅ Teste concluído!")