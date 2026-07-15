from gerenciar_fortigate import GerenciadorFortigate

gf = GerenciadorFortigate()
if gf.autenticar():
    print('🔍 Verificando configurações do Fortigate para o IP 164.163.1.58...')

    # Verificar rotas estáticas
    print('\n📋 Verificando rotas estáticas...')
    try:
        response = gf.session.get(f'{gf.base_url}/api/v2/cmdb/router/static')
        if response.status_code == 200:
            rotas = response.json()
            print(f'Encontradas {len(rotas.get("results", []))} rotas estáticas')

            # Procurar rotas relacionadas ao IP
            for rota in rotas.get('results', []):
                dst = rota.get('dst', '')
                gateway = rota.get('gateway', '')
                if '164.163.1' in dst or '164.163' in dst:
                    print(f'  Rota encontrada: {dst} -> {gateway}')
        else:
            print(f'Erro ao obter rotas: {response.status_code}')
    except Exception as e:
        print(f'Erro ao verificar rotas: {e}')

    # Verificar políticas de firewall
    print('\n🔥 Verificando políticas de firewall...')
    try:
        response = gf.session.get(f'{gf.base_url}/api/v2/cmdb/firewall/policy')
        if response.status_code == 200:
            policies = response.json()
            print(f'Encontradas {len(policies.get("results", []))} políticas')

            # Procurar políticas que possam afetar o IP
            count = 0
            for policy in policies.get('results', []):
                srcaddr = policy.get('srcaddr', [])
                dstaddr = policy.get('dstaddr', [])
                action = policy.get('action', '')

                # Verificar se a política envolve o IP ou rede
                relevante = False
                for addr in srcaddr + dstaddr:
                    if isinstance(addr, dict) and ('164.163.1' in str(addr.get('name', '')) or '164.163' in str(addr.get('subnet', ''))):
                        relevante = True
                        break

                if relevante:
                    count += 1
                    print(f'  Política relevante: {policy.get("name", "Sem nome")} - Ação: {action}')

            if count == 0:
                print('  Nenhuma política específica encontrada para 164.163.1.x')
        else:
            print(f'Erro ao obter políticas: {response.status_code}')
    except Exception as e:
        print(f'Erro ao verificar políticas: {e}')

    # Verificar endereços de firewall
    print('\n📍 Verificando endereços de firewall...')
    try:
        response = gf.session.get(f'{gf.base_url}/api/v2/cmdb/firewall/address')
        if response.status_code == 200:
            addresses = response.json()
            print(f'Encontrados {len(addresses.get("results", []))} endereços')

            # Procurar endereços relacionados
            for addr in addresses.get('results', []):
                name = addr.get('name', '')
                subnet = addr.get('subnet', '')
                if '164.163.1' in name or '164.163.1' in subnet:
                    print(f'  Endereço encontrado: {name} - {subnet}')
        else:
            print(f'Erro ao obter endereços: {response.status_code}')
    except Exception as e:
        print(f'Erro ao verificar endereços: {e}')

else:
    print('❌ Falha na autenticação do Fortigate')