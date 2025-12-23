#!/usr/bin/env python3
"""
Script para testar a conversão de IP
"""

from gerenciar_switches import GerenciadorSwitches
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas não instalado. Funcionalidades limitadas.")
    PANDAS_AVAILABLE = False
    pd = None

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Testando conversão de IP")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Testa alguns IPs
    ips_teste = [
        102541220,  # 10.254.12.20
        192168416,  # 192.168.4.16
        1921684129, # 192.168.41.29
        3232235876, # 192.168.1.100
        167772161,  # 10.0.0.1
    ]
    
    print("\n📋 Resultados da conversão:")
    for ip in ips_teste:
        ip_formatado = gerenciador._converter_ip_numerico(ip)
        print(f"   {ip} -> {ip_formatado}")
    
    # Carrega alguns IPs do Excel para teste
    try:
        df = pd.read_excel('switches_zabbix.xlsx', sheet_name='Switches', header=2)
        print("\n📋 IPs do Excel:")
        for i, row in df.head(5).iterrows():
            host = row["Host"]
            ip = row["IP"]
            ip_formatado = gerenciador._converter_ip_numerico(ip)
            print(f"   {host}: {ip} -> {ip_formatado}")
    except Exception as e:
        print(f"Erro ao carregar Excel: {e}")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()