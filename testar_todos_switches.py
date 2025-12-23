#!/usr/bin/env python3
"""
Script para testar a verificação de todos os switches
"""

from gerenciar_switches import GerenciadorSwitches
import json
from datetime import datetime

def main():
    """Função principal"""
    print("=" * 50)
    print("🔍 Testando verificação de todos os switches")
    print("=" * 50)
    
    # Cria o gerenciador de switches
    gerenciador = GerenciadorSwitches()
    
    # Lista os switches disponíveis
    print(f"\n📋 Total de switches: {len(gerenciador.switches)}")
    print(f"📋 Total de regionais: {len(gerenciador.regionais)}")
    
    # Verifica apenas os primeiros 3 switches para teste
    print("\n🔍 Verificando os primeiros 3 switches...")
    
    for i, switch in enumerate(gerenciador.switches[:3], 1):
        host_name = switch["host"]
        print(f"\n📡 {i}. Verificando switch: {host_name}")
        
        inicio = datetime.now()
        resultado = gerenciador.verificar_switch(host_name)
        fim = datetime.now()
        
        tempo = (fim - inicio).total_seconds()
        
        print(f"⏱️ Tempo de verificação: {tempo:.2f} segundos")
        print(f"📊 Status: {resultado['status']}")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()