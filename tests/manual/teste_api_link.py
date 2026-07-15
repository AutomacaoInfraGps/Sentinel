#!/usr/bin/env python3
import requests
import time
import json

# Espera o servidor iniciar
time.sleep(3)

try:
    print("Testando API de teste de link...")
    response = requests.get('http://localhost:5000/api/regional/RG_GLOBAL_SEGURANCA/link/link_rg_global_seguranca_01/testar')

    print(f'Status HTTP: {response.status_code}')

    if response.status_code == 200:
        result = response.json()
        print('✅ API funcionando! Resposta:')
        print(json.dumps(result, indent=2))
    else:
        print(f'❌ Erro HTTP: {response.status_code}')
        print('Conteúdo:', response.text[:500])

except Exception as e:
    print(f'Erro na requisição: {e}')