#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste do relatório completo das VMs integrado ao dashboard
"""

import json
from pathlib import Path
from datetime import datetime

print("🖥️ Teste do Relatório Completo das VMs")
print("=" * 60)

# Simula a seção de VMs do executar_tudo.py
PROJECT_ROOT = Path(__file__).parent

vms_data = []
vms_online = 0
vms_offline = 0

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
            
            vm_info = {
                'name': vm['name'],
                'ip': vm['ip'],
                'regional': vm.get('regional', 'N/A'),
                'username': vm.get('username', 'N/A'),
                'description': vm.get('description', 'N/A'),
                'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            if vm_online:
                vms_online += 1
                vm_info['status'] = "online"
                
                # Se a VM está online, gera relatório detalhado
                print(f"[EXEC] Gerando relatório detalhado da VM {vm['name']}...")
                from vm_manager import gerar_relatorio_simples
                
                relatorio = gerar_relatorio_simples(
                    vm['ip'], 
                    vm.get('username', ''), 
                    vm.get('password', '')
                )
                
                if relatorio.get('success', False):
                    print(f"✅ Relatório detalhado gerado para VM {vm['name']}")
                    vm_info['relatorio_detalhado'] = relatorio
                    
                    # Mostra resumo do relatório
                    sistema = relatorio.get('sistema', {})
                    if sistema and not sistema.get('error'):
                        print(f"   📋 Sistema: {sistema.get('OperatingSystem', 'N/A')}")
                        print(f"   💾 Memória: {sistema.get('Memory', 'N/A')}")
                        print(f"   🔄 Uptime: {sistema.get('Uptime', 'N/A')}")
                    
                    discos = relatorio.get('discos', [])
                    if discos and not (len(discos) == 1 and discos[0].get('error')):
                        print(f"   💽 Discos: {len(discos)} encontrados")
                    
                    servicos = relatorio.get('servicos', [])
                    if servicos and not (len(servicos) == 1 and servicos[0].get('error')):
                        servicos_rodando = [s for s in servicos if s.get('Status') == 'Running']
                        print(f"   ⚙️ Serviços: {len(servicos_rodando)} rodando")
                else:
                    print(f"⚠️ Falha ao gerar relatório detalhado: {relatorio.get('message', 'Erro desconhecido')}")
                    vm_info['relatorio_erro'] = relatorio.get('message', 'Erro desconhecido')
            else:
                vms_offline += 1
                vm_info['status'] = "offline"
                print(f"❌ VM {vm['name']} está offline")
                
            vms_data.append(vm_info)
            
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

    print(f"\n📊 Resumo:")
    print(f"   - VMs Online: {vms_online}")
    print(f"   - VMs Offline: {vms_offline}")
    print(f"   - Total processado: {len(vms_data)}")
    
    # Testa geração de HTML básico
    print(f"\n📄 Testando geração de HTML...")
    relatorio_vms = "<div class='vms-container'>"
    
    for vm in vms_data:
        status_class = "success" if vm['status'] == 'online' else "danger"
        
        relatorio_vms += f"""
        <div class="vm-item mb-4">
            <div class="card">
                <div class="card-header bg-{status_class} text-white">
                    <h4 class="mb-0">🖥️ {vm['name']}</h4>
                    <small>{vm.get('description', 'N/A')}</small>
                </div>
                <div class="card-body">
                    <p><strong>IP:</strong> {vm['ip']}</p>
                    <p><strong>Regional:</strong> {vm['regional']}</p>
                    <p><strong>Status:</strong> {vm['status'].upper()}</p>
        """
        
        # Se tem relatório detalhado, adiciona informações básicas
        if vm.get('relatorio_detalhado') and vm['relatorio_detalhado'].get('success'):
            relatorio = vm['relatorio_detalhado']
            sistema = relatorio.get('sistema', {})
            if sistema and not sistema.get('error'):
                relatorio_vms += f"""
                    <p><strong>Sistema:</strong> {sistema.get('OperatingSystem', 'N/A')}</p>
                    <p><strong>Memória:</strong> {sistema.get('Memory', 'N/A')}</p>
                """
        
        relatorio_vms += """
                </div>
            </div>
        </div>
        """
    
    relatorio_vms += "</div>"
    
    print(f"✅ HTML gerado com {len(relatorio_vms)} caracteres")
    
    # Salva um exemplo do HTML
    output_file = PROJECT_ROOT / "output" / "teste_vms_detalhado.html"
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Teste VMs Detalhado</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container mt-4">
        <h1>Teste de VMs com Relatório Detalhado</h1>
        <p>Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        {relatorio_vms}
    </div>
</body>
</html>
        """)
    
    print(f"📁 Arquivo de teste salvo: {output_file}")

except Exception as e:
    print(f"❌ Erro no teste: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("✅ Teste concluído!")