#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste rápido do dashboard com logs integrados
"""

import json
from pathlib import Path
from datetime import datetime

print("🖥️ Teste do Dashboard com Logs das VMs")
print("=" * 60)

# Simula apenas a seção de VMs com logs
PROJECT_ROOT = Path(__file__).parent

try:
    # Carrega VMs do arquivo de dados
    vms_file = PROJECT_ROOT / "data" / "vms.json"
    if vms_file.exists():
        with open(vms_file, 'r', encoding='utf-8') as f:
            vms_configuradas = json.load(f)
    else:
        vms_configuradas = []
    
    from vm_manager import verificar_vm_online, gerar_relatorio_simples
    
    vm = vms_configuradas[0] if vms_configuradas else None
    if vm:
        print(f"[EXEC] Testando VM {vm['name']} ({vm['ip']})")
        
        if verificar_vm_online(vm['ip']):
            print(f"✅ VM está online - gerando relatório completo...")
            
            relatorio = gerar_relatorio_simples(
                vm['ip'], 
                vm.get('username', ''), 
                vm.get('password', '')
            )
            
            if relatorio.get('success', False):
                # Testa geração de HTML com logs
                print(f"\n📄 Gerando HTML com logs...")
                
                eventos = relatorio.get('eventos', [])
                processos = relatorio.get('processos', [])
                sistema = relatorio.get('sistema', {})
                
                print(f"   - Sistema: {sistema.get('OperatingSystem', 'N/A')}")
                print(f"   - Processos: {len(processos)} encontrados")
                print(f"   - Logs: {len(eventos)} encontrados")
                
                # Gera HTML básico com logs
                html_logs = ""
                if eventos and not (len(eventos) == 1 and eventos[0].get('error')):
                    html_logs = f"""
                    <div class="row mt-3">
                        <div class="col-12">
                            <h6>📋 Últimos {len(eventos)} Logs do Sistema</h6>
                            <div class="table-responsive">
                                <table class="table table-sm table-striped">
                                    <thead>
                                        <tr>
                                            <th>Data/Hora</th>
                                            <th>Tipo</th>
                                            <th>Fonte</th>
                                            <th>ID</th>
                                            <th>Mensagem</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                    """
                    
                    for evento in eventos[:10]:  # Mostra apenas os primeiros 10 no teste
                        if not evento.get('error'):
                            entry_type = evento.get('EntryType', 'Information')
                            
                            # Define a cor baseada no tipo do evento
                            if entry_type == 'Error':
                                tipo_badge = 'danger'
                                tipo_icon = '❌'
                            elif entry_type == 'Warning':
                                tipo_badge = 'warning'
                                tipo_icon = '⚠️'
                            else:
                                tipo_badge = 'info'
                                tipo_icon = 'ℹ️'
                            
                            # Trunca a mensagem se for muito longa
                            mensagem = evento.get('Message', 'N/A')
                            if len(mensagem) > 80:
                                mensagem = mensagem[:80] + "..."
                            
                            html_logs += f"""
                                            <tr>
                                                <td><small>{evento.get('TimeGenerated', 'N/A')}</small></td>
                                                <td><span class="badge badge-{tipo_badge}">{tipo_icon} {entry_type}</span></td>
                                                <td><small>{evento.get('Source', 'N/A')}</small></td>
                                                <td><small>{evento.get('EventID', 'N/A')}</small></td>
                                                <td><small>{mensagem}</small></td>
                                            </tr>
                            """
                    
                    html_logs += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    """
                
                print(f"✅ HTML dos logs gerado: {len(html_logs)} caracteres")
                
                # Salva um exemplo
                output_file = PROJECT_ROOT / "output" / "teste_logs_vm.html"
                output_file.parent.mkdir(exist_ok=True)
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Teste Logs VM</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container mt-4">
        <h1>Teste de Logs da VM {vm['name']}</h1>
        <p>Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h4>🖥️ {vm['name']} - Logs do Sistema</h4>
            </div>
            <div class="card-body">
                {html_logs}
            </div>
        </div>
    </div>
</body>
</html>
                    """)
                
                print(f"📁 Arquivo de teste salvo: {output_file}")
                
            else:
                print(f"❌ Falha no relatório: {relatorio.get('message', 'Erro desconhecido')}")
        else:
            print(f"❌ VM offline")
    else:
        print("❌ Nenhuma VM configurada")

except Exception as e:
    print(f"❌ Erro no teste: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("✅ Teste concluído!")