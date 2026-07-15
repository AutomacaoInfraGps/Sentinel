#!/usr/bin/env python3
"""
Script para testar a verificação de um switch pelo IP
"""

from gerenciar_switches import GerenciadorSwitches
import json

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Testando verificação de switch pelo IP")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Seleciona um switch para teste
    switch_teste = "V001_REG_PARANA - SWTGPSPR-02"
    
    # Encontra o switch na lista
    switch_info = None
    for switch in gerenciador.switches:
        if switch["host"] == switch_teste:
            switch_info = switch
            break
    
    if not switch_info:
        print(f"❌ Switch {switch_teste} não encontrado na lista")
        return
    
    print(f"\n📋 Informações do switch:")
    print(f"   Nome: {switch_info['host']}")
    print(f"   IP (numérico): {switch_info.get('ip_numerico', 'N/A')}")
    print(f"   IP (formatado): {switch_info['ip']}")
    print(f"   Regional: {switch_info['regional']}")
    
    print(f"\n🔍 Verificando switch pelo nome: {switch_teste}")
    resultado = gerenciador.verificar_switch(switch_teste)
    
    print("\n📊 Resultado da verificação:")
    print(f"   Status: {resultado['status']}")
    if resultado['detalhes']:
        print(f"   Host ID: {resultado['detalhes'].get('host_id', 'N/A')}")
        print(f"   Host Status: {resultado['detalhes'].get('host_status', 'N/A')}")
        print(f"   Problemas: {len(resultado['detalhes'].get('problemas', []))}")
        print(f"   Itens: {len(resultado['detalhes'].get('itens', []))}")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()