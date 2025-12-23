#!/usr/bin/env python3
"""
Script para testar a API diretamente
"""

import json
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.append(str(Path(__file__).parent.absolute()))

# Importa as funções necessárias
from data_store import load_data, is_data_fresh
from datetime import datetime

def test_load_unifi():
    """Testa o carregamento dos dados do UniFi"""
    print("=== Testando carregamento de dados do UniFi ===")
    
    unifi_data = load_data("unifi")
    
    if unifi_data:
        print(f"✅ Dados carregados com sucesso")
        print(f"Total de APs: {unifi_data.get('total_aps', 0)}")
        print(f"APs online: {unifi_data.get('aps_online', 0)}")
        print(f"APs offline: {unifi_data.get('aps_offline', 0)}")
        print(f"Clientes conectados: {unifi_data.get('clientes_conectados', 0)}")
        print(f"Timestamp: {unifi_data.get('timestamp', 'Não disponível')}")
        
        # Verifica se os dados estão atualizados
        fresh = is_data_fresh("unifi")
        print(f"Dados atualizados: {'Sim' if fresh else 'Não'}")
        
        # Simula a resposta da API
        timestamp = datetime.fromisoformat(unifi_data.get('timestamp', datetime.now().isoformat()))
        
        response = {
            'status': 'ok' if unifi_data.get('aps_offline', 0) == 0 else 'aviso',
            'total_aps': unifi_data.get('total_aps', 0),
            'aps_online': unifi_data.get('aps_online', 0),
            'aps_offline': unifi_data.get('aps_offline', 0),
            'clientes_conectados': unifi_data.get('clientes_conectados', 0),
            'ultima_verificacao': timestamp.strftime('%H:%M'),
            'controller_online': unifi_data.get('controller', {}).get('online', False),
            'controller_ip': unifi_data.get('controller', {}).get('ip', 'Não disponível'),
            'controller_porta': unifi_data.get('controller', {}).get('porta', 'Não disponível'),
            'controller_versao': unifi_data.get('controller', {}).get('versao', 'Não disponível'),
            'aps': unifi_data.get('aps', []),
            'sites': unifi_data.get('sites', []),
            'dados_atualizados': is_data_fresh('unifi')
        }
        
        # Salva a resposta simulada para verificação
        with open("api_response_test.json", "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Resposta da API simulada salva em api_response_test.json")
        
        # Verifica se há APs na resposta
        aps = unifi_data.get('aps', [])
        if aps:
            print(f"✅ {len(aps)} APs encontrados nos dados")
            print(f"Primeiro AP: {aps[0]['nome']} - Status: {aps[0]['status']}")
        else:
            print("❌ Nenhum AP encontrado nos dados")
    else:
        print("❌ Falha ao carregar dados do UniFi")

def test_load_replicacao():
    """Testa o carregamento dos dados de replicação"""
    print("\n=== Testando carregamento de dados de replicação ===")
    
    replicacao_data = load_data("replicacao")
    
    if replicacao_data:
        print(f"✅ Dados carregados com sucesso")
        print(f"Status: {replicacao_data.get('status', 'Não disponível')}")
        print(f"Erros operacionais: {replicacao_data.get('erros_operacionais', 0)}")
        print(f"Timestamp: {replicacao_data.get('timestamp', 'Não disponível')}")
        
        # Verifica se os dados estão atualizados
        fresh = is_data_fresh("replicacao")
        print(f"Dados atualizados: {'Sim' if fresh else 'Não'}")
    else:
        print("❌ Falha ao carregar dados de replicação")

if __name__ == "__main__":
    test_load_unifi()
    test_load_replicacao()