#!/usr/bin/env python3
"""
Script para verificar se o servidor web está em execução
"""

import sys
import socket
import requests
from time import sleep

def check_port(host, port, timeout=2):
    """Verifica se uma porta está aberta"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    result = sock.connect_ex((host, port))
    sock.close()
    return result == 0

def check_api(url, timeout=5):
    """Verifica se a API está respondendo"""
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False

def main():
    """Função principal"""
    host = "localhost"
    port = 5000
    api_url = "http://localhost:5000/api/test"
    
    print(f"Verificando servidor em {host}:{port}...")
    
    # Verifica se a porta está aberta
    if check_port(host, port):
        print(f"✅ Porta {port} está aberta")
    else:
        print(f"❌ Porta {port} está fechada")
        print("O servidor web não parece estar em execução.")
        print("Execute o servidor com o comando:")
        print("python web_config.py")
        return 1
    
    # Verifica se a API está respondendo
    print(f"Verificando API em {api_url}...")
    if check_api(api_url):
        print("✅ API está respondendo")
    else:
        print("❌ API não está respondendo")
        print("O servidor web está em execução, mas a API não está respondendo.")
        print("Verifique os logs do servidor.")
        return 2
    
    print("✅ Servidor web e API estão funcionando corretamente")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nOperação cancelada pelo usuário")
        sys.exit(130)