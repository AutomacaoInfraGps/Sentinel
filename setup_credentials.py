#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script para configurar as credenciais iniciais do sistema de automação.
Este script deve ser executado uma vez para configurar as credenciais
de todos os serviços utilizados pelo sistema.
"""

import os
import sys
import getpass
from pathlib import Path

# Verifica se o módulo de credenciais está disponível
try:
    from credentials import encrypt_credentials, decrypt_credentials, get_credentials
    from credentials import setup_initial_credentials as setup_creds
except ImportError:
    print("❌ Módulo de credenciais não encontrado!")
    print("   Verifique se o arquivo credentials.py está no diretório do projeto.")
    sys.exit(1)

def clear_screen():
    """Limpa a tela do terminal"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    """Imprime o cabeçalho do programa"""
    clear_screen()
    print("=" * 80)
    print("                CONFIGURAÇÃO DE CREDENCIAIS - SISTEMA DE AUTOMAÇÃO")
    print("=" * 80)
    print("\nEste assistente irá ajudá-lo a configurar as credenciais para os serviços utilizados")
    print("pelo sistema de automação. As credenciais serão armazenadas de forma segura e")
    print("criptografada no sistema.\n")
    print("=" * 80)
    print()

def setup_fortigate():
    """Configura as credenciais do Fortigate"""
    print("\n--- CONFIGURAÇÃO DO FORTIGATE ---\n")
    
    host = input("Host do Fortigate [10.254.12.1]: ") or "10.254.12.1"
    port = input("Porta da API do Fortigate [20443]: ") or "20443"
    username = input("Usuário do Fortigate [admin]: ") or "admin"
    password = getpass.getpass("Senha do Fortigate: ")
    
    # Obtém as credenciais atuais
    credentials = decrypt_credentials()
    
    # Atualiza as credenciais do Fortigate
    credentials['fortigate'] = {
        'host': host,
        'port': int(port),
        'username': username,
        'password': password
    }
    
    # Salva as credenciais
    encrypt_credentials(credentials)
    
    print("\n✅ Credenciais do Fortigate configuradas com sucesso!")

def setup_zabbix():
    """Configura as credenciais do Zabbix"""
    print("\n--- CONFIGURAÇÃO DO ZABBIX ---\n")
    
    url = input("URL da API do Zabbix [http://10.254.12.15/zabbix/api_jsonrpc.php]: ") or "http://10.254.12.15/zabbix/api_jsonrpc.php"
    username = input("Usuário do Zabbix [admin]: ") or "admin"
    password = getpass.getpass("Senha do Zabbix: ")
    
    # Obtém as credenciais atuais
    credentials = decrypt_credentials()
    
    # Atualiza as credenciais do Zabbix
    credentials['zabbix'] = {
        'url': url,
        'username': username,
        'password': password
    }
    
    # Salva as credenciais
    encrypt_credentials(credentials)
    
    print("\n✅ Credenciais do Zabbix configuradas com sucesso!")

def setup_unifi():
    """Configura as credenciais do UniFi Controller"""
    print("\n--- CONFIGURAÇÃO DO UNIFI CONTROLLER ---\n")
    
    host = input("Host do UniFi Controller [192.168.21.28]: ") or "192.168.21.28"
    port = input("Porta do UniFi Controller [8443]: ") or "8443"
    username = input("Usuário do UniFi Controller [admin]: ") or "admin"
    password = getpass.getpass("Senha do UniFi Controller: ")
    
    # Obtém as credenciais atuais
    credentials = decrypt_credentials()
    
    # Atualiza as credenciais do UniFi
    credentials['unifi'] = {
        'host': host,
        'port': int(port),
        'username': username,
        'password': password
    }
    
    # Salva as credenciais
    encrypt_credentials(credentials)
    
    print("\n✅ Credenciais do UniFi Controller configuradas com sucesso!")

def setup_naos():
    """Configura as credenciais do servidor NAOS"""
    print("\n--- CONFIGURAÇÃO DO SERVIDOR NAOS ---\n")
    
    host = input("IP do servidor NAOS [192.168.21.27]: ") or "192.168.21.27"
    username = input("Usuário do servidor NAOS [galaxia\\admin]: ") or "galaxia\\admin"
    password = getpass.getpass("Senha do servidor NAOS: ")
    
    # Obtém as credenciais atuais
    credentials = decrypt_credentials()
    
    # Atualiza as credenciais do NAOS
    credentials['naos'] = {
        'host': host,
        'username': username,
        'password': password
    }
    
    # Salva as credenciais
    encrypt_credentials(credentials)
    
    print("\n✅ Credenciais do servidor NAOS configuradas com sucesso!")

def setup_master_password():
    """Configura a senha mestra para criptografia"""
    print("\n--- CONFIGURAÇÃO DA SENHA MESTRA ---\n")
    print("A senha mestra é usada para criptografar todas as outras senhas.")
    print("Se você esquecer esta senha, não será possível recuperar as credenciais.")
    print("Recomendamos que você anote esta senha em um local seguro.\n")
    
    while True:
        password = getpass.getpass("Nova senha mestra: ")
        confirm = getpass.getpass("Confirme a senha mestra: ")
        
        if password == confirm:
            # Obtém as credenciais atuais
            credentials = decrypt_credentials()
            
            # Criptografa com a nova senha
            encrypt_credentials(credentials, password)
            
            # Define a variável de ambiente
            os.environ['AUTOMATION_MASTER_PASSWORD'] = password
            
            print("\n✅ Senha mestra configurada com sucesso!")
            print("   Para usar esta senha em execuções futuras, defina a variável de ambiente:")
            print(f"   AUTOMATION_MASTER_PASSWORD='{password}'")
            break
        else:
            print("\n❌ As senhas não coincidem. Tente novamente.\n")

def main_menu():
    """Exibe o menu principal"""
    while True:
        print_header()
        print("MENU PRINCIPAL:\n")
        print("1. Configurar todas as credenciais")
        print("2. Configurar apenas Fortigate")
        print("3. Configurar apenas Zabbix")
        print("4. Configurar apenas UniFi Controller")
        print("5. Configurar apenas servidor NAOS")
        print("6. Configurar senha mestra")
        print("0. Sair")
        
        choice = input("\nEscolha uma opção: ")
        
        if choice == '1':
            setup_master_password()
            setup_fortigate()
            setup_zabbix()
            setup_unifi()
            setup_naos()
            input("\nPressione ENTER para continuar...")
        elif choice == '2':
            setup_fortigate()
            input("\nPressione ENTER para continuar...")
        elif choice == '3':
            setup_zabbix()
            input("\nPressione ENTER para continuar...")
        elif choice == '4':
            setup_unifi()
            input("\nPressione ENTER para continuar...")
        elif choice == '5':
            setup_naos()
            input("\nPressione ENTER para continuar...")
        elif choice == '6':
            setup_master_password()
            input("\nPressione ENTER para continuar...")
        elif choice == '0':
            print("\nSaindo do programa...")
            break
        else:
            print("\n❌ Opção inválida. Tente novamente.")
            input("\nPressione ENTER para continuar...")

if __name__ == "__main__":
    main_menu()