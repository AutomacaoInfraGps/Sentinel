#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Arquivo de credenciais para o sistema de automação
IMPORTANTE: Este arquivo NÃO deve ser versionado no controle de versão!
Adicione-o ao .gitignore para evitar que senhas sejam expostas.
"""

import os
from pathlib import Path
import json
import base64
import getpass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Diretório para armazenar credenciais criptografadas
from utils_paths import get_credentials_dir
CREDENTIALS_DIR = get_credentials_dir()

# Garante que o diretório existe
if not CREDENTIALS_DIR.exists():
    CREDENTIALS_DIR.mkdir(exist_ok=True)

# Arquivo de credenciais criptografadas
CREDENTIALS_FILE = CREDENTIALS_DIR / 'encrypted_credentials.json'

# Arquivo de salt para derivação de chave
SALT_FILE = CREDENTIALS_DIR / 'salt.bin'

# Senha mestra para criptografia (pode ser definida como variável de ambiente)
MASTER_PASSWORD = os.environ.get('AUTOMATION_MASTER_PASSWORD', 'default_password_change_me')

def get_encryption_key(password=None):
    """Gera uma chave de criptografia a partir da senha mestra"""
    if not SALT_FILE.exists():
        # Gera um novo salt se não existir
        salt = os.urandom(16)
        with open(SALT_FILE, 'wb') as f:
            f.write(salt)
    else:
        # Carrega o salt existente
        with open(SALT_FILE, 'rb') as f:
            salt = f.read()
    
    # Usa a senha fornecida ou a senha mestra
    pwd = password or MASTER_PASSWORD
    
    # Deriva a chave a partir da senha e do salt
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(pwd.encode()))
    return key

def encrypt_credentials(credentials, password=None):
    """Criptografa as credenciais e salva no arquivo"""
    key = get_encryption_key(password)
    f = Fernet(key)
    
    # Converte para JSON e criptografa
    json_data = json.dumps(credentials).encode()
    encrypted_data = f.encrypt(json_data)
    
    # Salva no arquivo
    with open(CREDENTIALS_FILE, 'wb') as file:
        file.write(encrypted_data)
    
    print(f"✅ Credenciais salvas com segurança em {CREDENTIALS_FILE}")

def decrypt_credentials(password=None):
    """Descriptografa e retorna as credenciais"""
    if not CREDENTIALS_FILE.exists():
        print(f"❌ Arquivo de credenciais não encontrado: {CREDENTIALS_FILE}")
        return {}
    
    try:
        key = get_encryption_key(password)
        f = Fernet(key)
        
        # Lê e descriptografa
        with open(CREDENTIALS_FILE, 'rb') as file:
            encrypted_data = file.read()
        
        json_data = f.decrypt(encrypted_data)
        credentials = json.loads(json_data)
        
        return credentials
    except Exception as e:
        print(f"❌ Erro ao descriptografar credenciais: {str(e)}")
        return {}

def get_credentials(service, prompt_if_missing=False):
    """Obtém credenciais para um serviço específico"""
    credentials = decrypt_credentials()
    
    if service in credentials:
        return credentials[service]
    elif prompt_if_missing:
        # Se as credenciais não existirem, solicita ao usuário
        print(f"\n🔐 Configuração de credenciais para {service}")
        
        if service == 'fortigate':
            host = input("Host (default: 10.254.12.1): ") or "10.254.12.1"
            port = input("Porta (default: 20443): ") or "20443"
            username = input("Usuário (default: admin): ") or "admin"
            password = getpass.getpass("Senha: ")
            
            service_creds = {
                'host': host,
                'port': int(port),
                'username': username,
                'password': password
            }
        elif service == 'zabbix':
            url = input("URL (default: http://10.254.12.1/zabbix): ") or "http://10.254.12.1/zabbix"
            username = input("Usuário (default: Admin): ") or "Admin"
            password = getpass.getpass("Senha: ")
            
            service_creds = {
                'url': url,
                'username': username,
                'password': password
            }
        else:
            username = input("Usuário: ")
            password = getpass.getpass("Senha: ")
            
            service_creds = {
                'username': username,
                'password': password
            }
        
        # Atualiza as credenciais
        credentials[service] = service_creds
        encrypt_credentials(credentials)
        
        return service_creds
    else:
        # Retorna valores vazios se não encontrar
        if service == 'fortigate':
            return {
                'host': '10.254.12.1',
                'port': 20443,
                'username': 'admin',
                'password': ''
            }
        elif service == 'zabbix':
            return {
                'url': 'http://10.254.12.1/zabbix',
                'username': 'Admin',
                'password': ''
            }
        else:
            return {
                'username': '',
                'password': ''
            }

def setup_initial_credentials():
    """Configura as credenciais iniciais para todos os serviços"""
    # Fortigate
    get_credentials('fortigate', prompt_if_missing=True)
    
    # Zabbix
    get_credentials('zabbix', prompt_if_missing=True)
    
    print("\n✅ Configuração de credenciais concluída!")

# Execução direta para configuração inicial
if __name__ == "__main__":
    setup_initial_credentials()