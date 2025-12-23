#!/usr/bin/env python3
"""
Script para testar a verificação de um switch específico
"""

from gerenciar_switches import GerenciadorSwitches
import json

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Testando verificação de switch")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Lista os switches disponíveis
    print("\n📋 Switches disponíveis:")
    for i, switch in enumerate(gerenciador.switches[:10], 1):
        print(f"   {i}. {switch['host']} ({switch['regional']})")
    
    if not gerenciador.switches:
        print("❌ Nenhum switch encontrado!")
        return
    
    # Seleciona o primeiro switch para teste
    switch_teste = gerenciador.switches[0]['host']
    
    print(f"\n🔍 Verificando switch: {switch_teste}")
    resultado = gerenciador.verificar_switch(switch_teste)
    
    print("\n📊 Resultado da verificação:")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()