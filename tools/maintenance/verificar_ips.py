#!/usr/bin/env python3
"""
Script para verificar todos os IPs dos switches
"""

from gerenciar_switches import GerenciadorSwitches

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Verificando IPs dos switches")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Verifica todos os IPs
    print("\n📋 IPs dos switches:")
    
    # Conta IPs com problemas
    ips_com_problemas = 0
    
    for i, switch in enumerate(gerenciador.switches, 1):
        ip = switch.get("ip", "")
        ip_numerico = switch.get("ip_numerico", "")
        
        # Verifica se o IP está no formato correto
        if ip and "." not in ip:
            ips_com_problemas += 1
            print(f"❌ {i}. {switch['host']}: {ip} (formato incorreto)")
        else:
            print(f"✅ {i}. {switch['host']}: {ip}")
    
    print(f"\n📊 Total de switches: {len(gerenciador.switches)}")
    print(f"📊 IPs com problemas: {ips_com_problemas}")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()