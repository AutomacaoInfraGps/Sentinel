#!/usr/bin/env python3
"""
Script para diagnosticar problemas com switches em estado desconhecido
"""

from gerenciar_switches import GerenciadorSwitches
import json
import time

def main():
    """Função principal"""
    print("=" * 70)
    print("🔍 Diagnóstico de Switches com Status Desconhecido")
    print("=" * 70)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Autentica no Zabbix
    if not gerenciador.autenticar():
        print("❌ Falha na autenticação no Zabbix")
        return
    
    # Conta switches por status
    total = len(gerenciador.switches)
    online = sum(1 for s in gerenciador.switches if s.get('status') == 'online')
    offline = sum(1 for s in gerenciador.switches if s.get('status') == 'offline')
    warning = sum(1 for s in gerenciador.switches if s.get('status') == 'warning')
    desconhecidos = sum(1 for s in gerenciador.switches if s.get('status') == 'desconhecido')
    
    print(f"\n📊 Estatísticas de Status:")
    print(f"   Total de switches: {total}")
    print(f"   Online: {online}")
    print(f"   Offline: {offline}")
    print(f"   Warning: {warning}")
    print(f"   Desconhecidos: {desconhecidos}")
    
    # Se não houver switches desconhecidos, verifica todos
    if desconhecidos == 0:
        print("\n✅ Não há switches com status desconhecido.")
        print("⚠️ Verificando todos os switches para garantir...")
        
        # Verifica todos os switches
        for i, switch in enumerate(gerenciador.switches, 1):
            print(f"\n🔍 Verificando switch {i}/{total}: {switch['host']}")
            resultado = gerenciador.verificar_switch(switch['host'])
            print(f"   Status: {resultado['status']}")
            
            # Pausa breve para não sobrecarregar o Zabbix
            time.sleep(0.5)
        
        # Conta novamente
        online = sum(1 for s in gerenciador.switches if s.get('status') == 'online')
        offline = sum(1 for s in gerenciador.switches if s.get('status') == 'offline')
        warning = sum(1 for s in gerenciador.switches if s.get('status') == 'warning')
        desconhecidos = sum(1 for s in gerenciador.switches if s.get('status') == 'desconhecido')
        
        print(f"\n📊 Estatísticas Atualizadas:")
        print(f"   Total de switches: {total}")
        print(f"   Online: {online}")
        print(f"   Offline: {offline}")
        print(f"   Warning: {warning}")
        print(f"   Desconhecidos: {desconhecidos}")
        
        return
    
    # Lista switches desconhecidos
    print(f"\n📋 Switches com status desconhecido ({desconhecidos}):")
    
    switches_desconhecidos = [s for s in gerenciador.switches if s.get('status') == 'desconhecido']
    
    for i, switch in enumerate(switches_desconhecidos, 1):
        print(f"\n{i}. {switch['host']}")
        print(f"   IP: {switch['ip']}")
        print(f"   Regional: {switch['regional']}")
        
        # Tenta verificar o switch
        print(f"   🔍 Verificando no Zabbix...")
        
        try:
            # Busca o host no Zabbix pelo nome
            host_resp = gerenciador._call_api("host.get", {
                "filter": {"name": switch["host"]},
                "output": ["hostid", "name", "status"]
            })
            
            if host_resp.get("result"):
                host = host_resp["result"][0]
                host_id = host["hostid"]
                host_status = "ativo" if host["status"] == "0" else "inativo"
                print(f"   ✅ Encontrado no Zabbix pelo nome: ID {host_id}, Status: {host_status}")
            else:
                print(f"   ❌ Não encontrado no Zabbix pelo nome")
                
                # Tenta buscar pelo IP
                print(f"   🔍 Buscando pelo IP: {switch['ip']}...")
                interface_resp = gerenciador._call_api("hostinterface.get", {
                    "filter": {"ip": switch["ip"]},
                    "output": ["hostid", "ip"],
                    "selectHosts": ["hostid", "name", "status"]
                })
                
                if interface_resp.get("result"):
                    host = interface_resp["result"][0]["hosts"][0]
                    host_id = host["hostid"]
                    host_name = host["name"]
                    host_status = "ativo" if host["status"] == "0" else "inativo"
                    print(f"   ✅ Encontrado no Zabbix pelo IP: {host_name} (ID {host_id}, Status: {host_status})")
                    print(f"   ⚠️ Possível problema: Nome diferente no Zabbix")
                    print(f"      Nome no Excel: {switch['host']}")
                    print(f"      Nome no Zabbix: {host_name}")
                else:
                    print(f"   ❌ Não encontrado no Zabbix pelo IP")
                    print(f"   ⚠️ Possível problema: Switch não existe no Zabbix ou IP incorreto")
            
            # Verifica o switch (isso atualiza o status)
            resultado = gerenciador.verificar_switch(switch['host'])
            print(f"   📊 Status após verificação: {resultado['status']}")
            
        except Exception as e:
            print(f"   ❌ Erro ao verificar: {str(e)}")
        
        # Pausa breve para não sobrecarregar o Zabbix
        time.sleep(0.5)
    
    # Conta novamente
    online = sum(1 for s in gerenciador.switches if s.get('status') == 'online')
    offline = sum(1 for s in gerenciador.switches if s.get('status') == 'offline')
    warning = sum(1 for s in gerenciador.switches if s.get('status') == 'warning')
    desconhecidos = sum(1 for s in gerenciador.switches if s.get('status') == 'desconhecido')
    
    print(f"\n📊 Estatísticas Atualizadas:")
    print(f"   Total de switches: {total}")
    print(f"   Online: {online}")
    print(f"   Offline: {offline}")
    print(f"   Warning: {warning}")
    print(f"   Desconhecidos: {desconhecidos}")
    
    if desconhecidos > 0:
        print("\n⚠️ Ainda existem switches com status desconhecido.")
        print("   Possíveis causas:")
        print("   1. Os switches não existem no Zabbix")
        print("   2. Os nomes dos switches no Excel são diferentes dos nomes no Zabbix")
        print("   3. Os IPs dos switches no Excel estão incorretos")
        print("   4. Problemas de conectividade com o Zabbix")
        
        print("\n💡 Recomendações:")
        print("   1. Execute o script corrigir_ips_excel.py para atualizar os IPs")
        print("   2. Verifique se os nomes dos switches no Excel correspondem aos nomes no Zabbix")
        print("   3. Verifique se todos os switches estão cadastrados no Zabbix")
    else:
        print("\n✅ Todos os switches foram verificados com sucesso!")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()