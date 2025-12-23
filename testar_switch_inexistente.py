#!/usr/bin/env python3
"""
Script para testar a verificação de um switch inexistente
"""

from gerenciar_switches import GerenciadorSwitches
import json

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Testando verificação de switch inexistente")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Seleciona um switch para teste (último da lista, provavelmente não está no Zabbix)
    switch_teste = gerenciador.switches[-1]["host"]
    
    print(f"\n📋 Informações do switch:")
    print(f"   Nome: {gerenciador.switches[-1]['host']}")
    print(f"   IP (formatado): {gerenciador.switches[-1]['ip']}")
    print(f"   Regional: {gerenciador.switches[-1]['regional']}")
    
    print(f"\n🔍 Verificando switch: {switch_teste}")
    resultado = gerenciador.verificar_switch(switch_teste)
    
    print("\n📊 Resultado da verificação:")
    print(f"   Status: {resultado['status']}")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()