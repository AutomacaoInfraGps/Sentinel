import subprocess
import platform
import socket

def testar_conectividade(ip, porta=80, timeout=5):
    print(f'🔍 Testando conectividade para {ip}...')

    # Teste 1: Ping
    print('📡 Teste de ping...')
    try:
        if platform.system().lower() == 'windows':
            result = subprocess.run(['ping', '-n', '3', '-w', '2000', ip],
                                  capture_output=True, text=True, timeout=10)
        else:
            result = subprocess.run(['ping', '-c', '3', '-W', '2', ip],
                                  capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            print('✅ Ping bem-sucedido')
            ping_ok = True
        else:
            print('❌ Ping falhou')
            print('Saída:', result.stdout[-200:])  # Últimos 200 chars
            ping_ok = False
    except Exception as e:
        print(f'❌ Erro no ping: {e}')
        ping_ok = False

    # Teste 2: Conexão TCP
    print('🔌 Teste de conexão TCP...')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, porta))
        sock.close()

        if result == 0:
            print(f'✅ Conexão TCP na porta {porta} bem-sucedida')
            tcp_ok = True
        else:
            print(f'❌ Conexão TCP na porta {porta} falhou')
            tcp_ok = False
    except Exception as e:
        print(f'❌ Erro na conexão TCP: {e}')
        tcp_ok = False

    # Teste 3: Traceroute (se disponível)
    print('🗺️ Teste de traceroute...')
    try:
        if platform.system().lower() == 'windows':
            result = subprocess.run(['tracert', '-d', '-h', '10', ip],
                                  capture_output=True, text=True, timeout=30)
        else:
            result = subprocess.run(['traceroute', '-n', '-m', '10', ip],
                                  capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            print('✅ Traceroute concluído')
            # Mostra as primeiras linhas do traceroute
            lines = result.stdout.split('\n')[:5]
            for line in lines:
                if line.strip():
                    print(f'   {line}')
        else:
            print('❌ Traceroute falhou')
    except Exception as e:
        print(f'❌ Erro no traceroute: {e}')

    return {'ping': ping_ok, 'tcp': tcp_ok}

# Testar o IP específico
ip_teste = '164.163.1.58'
print(f'🧪 Teste completo de conectividade para {ip_teste}')
print('=' * 50)

resultado = testar_conectividade(ip_teste)

print('\n📊 Resumo:')
print(f'Ping: {"✅ OK" if resultado["ping"] else "❌ Falha"}')
print(f'TCP: {"✅ OK" if resultado["tcp"] else "❌ Falha"}')

if not resultado['ping'] and not resultado['tcp']:
    print('\n🔍 Possíveis causas:')
    print('• Firewall bloqueando o tráfego')
    print('• Roteamento incorreto')
    print('• IP não existe ou não está ativo')
    print('• Rede local bloqueando saída')
    print('• Problema de DNS/resolução')
elif resultado['ping'] and not resultado['tcp']:
    print('\n🔍 Possíveis causas:')
    print('• Firewall bloqueando portas específicas')
    print('• Serviço não está rodando na porta testada')