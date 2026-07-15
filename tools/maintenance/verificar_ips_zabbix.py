#!/usr/bin/env python3
"""
Script para verificar os IPs dos switches e compará-los com os IPs reais no Zabbix
"""

from gerenciar_switches import GerenciadorSwitches

def main():
    """Função principal"""
    print("=" * 70)
    print("🔍 Verificando IPs dos switches e comparando com IPs reais no Zabbix")
    print("=" * 70)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Autentica no Zabbix
    if not gerenciador.autenticar():
        print("❌ Falha na autenticação")
        return
    
    # Verifica todos os IPs
    print("\n📋 Comparação de IPs:")
    print("-" * 70)
    print(f"{'#':<3} {'Nome do Switch':<40} {'IP Convertido':<15} {'IP Real no Zabbix':<15} {'Status'}")
    print("-" * 70)
    
    # Conta IPs com problemas
    ips_com_problemas = 0
    ips_verificados = 0
    
    for i, switch in enumerate(gerenciador.switches, 1):
        host_name = switch.get("host", "")
        ip_convertido = switch.get("ip", "")
        
        # Busca o switch no Zabbix
        host_resp = gerenciador._call_api("host.get", {
            "filter": {"name": host_name},
            "output": ["hostid", "name", "status"],
            "selectInterfaces": ["ip"]
        })
        
        # Se encontrou o switch no Zabbix
        if host_resp.get("result"):
            ips_verificados += 1
            host = host_resp["result"][0]
            
            # Obtém o IP real do Zabbix (da primeira interface)
            ip_real = host["interfaces"][0]["ip"] if host["interfaces"] else "N/A"
            
            # Verifica se o IP convertido está correto
            status = "✅ OK" if ip_convertido == ip_real else "❌ DIFERENTE"
            
            if ip_convertido != ip_real:
                ips_com_problemas += 1
            
            print(f"{i:<3} {host_name[:40]:<40} {ip_convertido:<15} {ip_real:<15} {status}")
        else:
            print(f"{i:<3} {host_name[:40]:<40} {ip_convertido:<15} {'Não encontrado':<15} ⚠️ NÃO ENCONTRADO")
    
    print("-" * 70)
    print(f"📊 Total de switches: {len(gerenciador.switches)}")
    print(f"📊 Switches verificados no Zabbix: {ips_verificados}")
    print(f"📊 IPs com problemas: {ips_com_problemas}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()