#!/usr/bin/env python3
"""
Script para listar hosts do Zabbix
"""

from gerenciar_switches import GerenciadorSwitches

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Listando hosts do Zabbix")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Autentica no Zabbix
    if not gerenciador.autenticar():
        print("❌ Falha na autenticação")
        return
    
    # Busca hosts
    resp = gerenciador._call_api('host.get', {
        'output': ['hostid', 'name', 'status'],
        'limit': 20
    })
    
    if not resp.get('result'):
        print("❌ Nenhum host encontrado")
        return
    
    # Mostra hosts
    print("\n📋 Hosts no Zabbix:")
    for host in resp.get('result', []):
        status = "ativo" if host['status'] == "0" else "inativo"
        print(f"  {host['hostid']}: {host['name']} ({status})")
    
    # Busca interfaces
    print("\n📋 Interfaces de alguns hosts:")
    for host in resp.get('result', [])[:5]:  # Primeiros 5 hosts
        host_id = host['hostid']
        host_name = host['name']
        
        interfaces = gerenciador._call_api('hostinterface.get', {
            'hostids': host_id,
            'output': ['interfaceid', 'ip', 'dns', 'useip', 'type', 'main']
        })
        
        print(f"\n  Host: {host_name}")
        for interface in interfaces.get('result', []):
            tipo = {
                "1": "Agent",
                "2": "SNMP",
                "3": "IPMI",
                "4": "JMX"
            }.get(interface['type'], "Desconhecido")
            
            usa_ip = "Sim" if interface['useip'] == "1" else "Não"
            principal = "Sim" if interface['main'] == "1" else "Não"
            
            print(f"    Interface {interface['interfaceid']}: {tipo}")
            print(f"      IP: {interface['ip']}")
            print(f"      DNS: {interface['dns']}")
            print(f"      Usa IP: {usa_ip}")
            print(f"      Principal: {principal}")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()