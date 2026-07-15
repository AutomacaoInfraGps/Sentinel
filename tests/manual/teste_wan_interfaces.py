from gerenciar_fortigate import GerenciadorFortigate
import json

gf = GerenciadorFortigate()
if gf.autenticar():
    print('🔍 Verificando interfaces WAN do Fortigate...')

    # Obter todas as interfaces
    interfaces_result = gf.obter_interfaces()
    if interfaces_result['success']:
        print(f'Encontradas {len(interfaces_result["interfaces"])} interfaces')

        # Filtrar apenas interfaces WAN
        wan_interfaces = []
        for interface in interfaces_result['interfaces']:
            name = interface.get('name', '').lower()
            if name in ['wan1', 'wan2']:
                wan_interfaces.append(interface)

        print(f'\n🔗 Interfaces WAN encontradas: {len(wan_interfaces)}')

        for wan in wan_interfaces:
            name = wan.get('name', '')
            ip = wan.get('ip', 'N/A')
            status = 'UP' if wan.get('link', False) else 'DOWN'

            print(f'\n📡 Interface {name.upper()}:')
            print(f'   IP: {ip}')
            print(f'   Status físico: {status}')
            print(f'   Speed: {wan.get("speed", "N/A")} Mbps')
            print(f'   Duplex: {wan.get("duplex", "N/A")}')

            # Testa a saúde da interface independentemente do status
            print(f'   Link ativo: {wan.get("link", False)}')
            print(f'   Descrição: {wan.get("description", "N/A")}')
            print(f'   Tipo: {wan.get("type", "N/A")}')
            print(f'   MTU: {wan.get("mtu", "N/A")}')
            print(f'   VDOM: {wan.get("vdom", "N/A")}')

            # Sempre testa a saúde física para diagnóstico completo
            teste_fisico = gf.testar_link_fisico(name)
            if teste_fisico['success']:
                saude = teste_fisico.get('saude', {})
                print(f'   Saúde física: {saude.get("status", "unknown")}')
                if saude.get('message'):
                    print(f'   Detalhes saúde: {saude["message"]}')
                if saude.get('metrics'):
                    metrics = saude['metrics']
                    print(f'   📊 Métricas de tráfego:')
                    print(f'      TX bytes: {metrics.get("tx_bytes", "N/A"):,}')
                    print(f'      RX bytes: {metrics.get("rx_bytes", "N/A"):,}')
                    print(f'      TX packets: {metrics.get("tx_packets", "N/A"):,}')
                    print(f'      RX packets: {metrics.get("rx_packets", "N/A"):,}')
                    print(f'      TX errors: {metrics.get("tx_errors", "N/A"):,}')
                    print(f'      RX errors: {metrics.get("rx_errors", "N/A"):,}')
                    print(f'      TX dropped: {metrics.get("tx_dropped", "N/A"):,}')
                    print(f'      RX dropped: {metrics.get("rx_dropped", "N/A"):,}')
                elif teste_fisico.get('estatisticas'):
                    estatisticas = teste_fisico['estatisticas']
                    print(f'   📊 Estatísticas de tráfego:')
                    print(f'      TX bytes: {estatisticas.get("tx_bytes", "N/A"):,}')
                    print(f'      RX bytes: {estatisticas.get("rx_bytes", "N/A"):,}')
                    print(f'      TX packets: {estatisticas.get("tx_packets", "N/A"):,}')
                    print(f'      RX packets: {estatisticas.get("rx_packets", "N/A"):,}')
                    print(f'      TX errors: {estatisticas.get("tx_errors", "N/A"):,}')
                    print(f'      RX errors: {estatisticas.get("rx_errors", "N/A"):,}')
                    print(f'      Speed: {estatisticas.get("speed", "N/A")} Mbps')
                    print(f'      Duplex: {estatisticas.get("duplex", "N/A")}')
                else:
                    print(f'   📊 Métricas não disponíveis')
            else:
                print(f'   ❌ Erro no teste físico: {teste_fisico.get("message", "Desconhecido")}')