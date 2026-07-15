#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script de teste para verificar Links de Internet (Fortigate)
"""

from datetime import datetime

print("🌐 Teste de Links de Internet (Fortigate)")
print("=" * 50)

try:
    from gerenciar_fortigate import GerenciadorFortigate
    
    gerenciador_fortigate = GerenciadorFortigate()
    print("✅ Gerenciador Fortigate inicializado")
    
    # Testa autenticação
    print("\n🔑 Testando autenticação...")
    auth_result = gerenciador_fortigate.autenticar()
    
    print(f"Resultado da autenticação: {auth_result}")
    print(f"Tipo do resultado: {type(auth_result)}")
    
    # Verifica o tipo de retorno
    auth_success = False
    if isinstance(auth_result, bool):
        auth_success = auth_result
        auth_message = "Autenticação bem-sucedida" if auth_result else "Falha na autenticação"
        print(f"✅ Retorno é boolean: {auth_success}")
    elif isinstance(auth_result, dict):
        auth_success = auth_result.get('success', False)
        auth_message = auth_result.get('message', 'Resultado da autenticação')
        print(f"✅ Retorno é dicionário: success={auth_success}")
    else:
        print(f"⚠️ Tipo de retorno inesperado: {type(auth_result)}")
        auth_message = f"Tipo inesperado: {type(auth_result)}"
    
    if auth_success:
        print(f"✅ {auth_message}")
        
        # Testa obtenção de links
        print("\n🔍 Obtendo informações dos links...")
        links_info = gerenciador_fortigate.obter_links_internet()
        
        print(f"Resultado links: {links_info}")
        print(f"Tipo do resultado: {type(links_info)}")
        
        if isinstance(links_info, dict) and links_info.get('success', False):
            links_list = links_info.get('links', [])
            print(f"✅ {len(links_list)} links encontrados")
            
            for i, link in enumerate(links_list):
                print(f"   Link {i+1}: {link}")
        else:
            print(f"❌ Erro ao obter links: {links_info}")
    else:
        print(f"❌ {auth_message}")

except Exception as e:
    print(f"❌ Erro no teste: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 50)
print("✅ Teste concluído!")