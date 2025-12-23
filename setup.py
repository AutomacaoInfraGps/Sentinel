"""
Script de configuração e instalação do sistema de automação.
Este script prepara o ambiente para execução em qualquer máquina.
"""

import json
import sys
from pathlib import Path
from config import (
    PROJECT_ROOT, OUTPUT_DIR, REGIONAL_HTMLS_DIR, LOGS_DIR, 
    ensure_directories, validate_config
)

def create_environment_template():
    """Cria um template do arquivo environment.json se não existir"""
    env_file = PROJECT_ROOT / "environment.json"
    
    if env_file.exists():
        print(f"✅ Arquivo environment.json já existe: {env_file}")
        return True
    
    template = {
        "naos_server": {
            "ip": "192.168.21.27",
            "usuario": "galaxia\\admin.lima",
            "senha": "ALTERE_AQUI"
        },
        "unifi_controller": {
            "host": "192.168.21.28",
            "port": 8443,
            "username": "admin.lima",
            "password": "ALTERE_AQUI"
        },
        "gps_amigo": {
            "url": "https://gpsamigo.com.br/login.php"
        },
        "timeouts": {
            "connection_timeout": 10,
            "max_retries": 3
        },
        "cleanup": {
            "remove_temp_files": True,
            "keep_logs": True
        }
    }
    
    try:
        with open(env_file, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        print(f"✅ Template environment.json criado: {env_file}")
        print("⚠️ IMPORTANTE: Edite o arquivo environment.json com suas credenciais!")
        return True
    except Exception as e:
        print(f"❌ Erro ao criar environment.json: {e}")
        return False

def create_connections_template():
    """Cria um template do arquivo Conexoes.txt se não existir"""
    conexoes_file = PROJECT_ROOT / "Conexoes.txt"
    
    if conexoes_file.exists():
        print(f"✅ Arquivo Conexoes.txt já existe: {conexoes_file}")
        return True
    
    template = """Nome: RG_EXEMPLO
Tipo: idrac
IP: 192.168.1.100
Usuario: root
Senha: calvin

Nome: RG_EXEMPLO_ILO
Tipo: ilo
IP: 192.168.1.101
Usuario: Administrator
Senha: senha123
"""
    
    try:
        with open(conexoes_file, 'w', encoding='utf-8') as f:
            f.write(template)
        print(f"✅ Template Conexoes.txt criado: {conexoes_file}")
        print("⚠️ IMPORTANTE: Edite o arquivo Conexoes.txt com suas regionais!")
        return True
    except Exception as e:
        print(f"❌ Erro ao criar Conexoes.txt: {e}")
        return False

def check_dependencies():
    """Verifica se as dependências estão instaladas"""
    dependencies = [
        ("requests", "pip install requests"),
        ("playwright", "pip install playwright"),
        ("pathlib", "Biblioteca padrão do Python"),
    ]
    
    missing = []
    for dep, install_cmd in dependencies:
        try:
            __import__(dep)
            print(f"✅ {dep} está instalado")
        except ImportError:
            print(f"❌ {dep} não está instalado")
            missing.append((dep, install_cmd))
    
    if missing:
        print("\n📦 Dependências faltando:")
        for dep, cmd in missing:
            print(f"   - {dep}: {cmd}")
        return False
    
    return True

def setup_directories():
    """Configura os diretórios necessários"""
    print("📁 Configurando diretórios...")
    ensure_directories()
    
    directories = [OUTPUT_DIR, REGIONAL_HTMLS_DIR, LOGS_DIR]
    for directory in directories:
        if directory.exists():
            print(f"✅ Diretório existe: {directory}")
        else:
            print(f"❌ Erro ao criar diretório: {directory}")
            return False
    
    return True

def main():
    """Função principal de configuração"""
    print("🚀 Configurando Sistema de Automação")
    print("=" * 50)
    print(f"📁 Diretório do projeto: {PROJECT_ROOT}")
    print()
    
    success = True
    
    # 1. Configurar diretórios
    if not setup_directories():
        success = False
    
    # 2. Criar templates de configuração
    if not create_environment_template():
        success = False
    
    if not create_connections_template():
        success = False
    
    # 3. Verificar dependências
    if not check_dependencies():
        success = False
    
    # 4. Validar configurações
    print("\n🔍 Validando configurações...")
    config_errors = validate_config()
    if config_errors:
        print("❌ Erros de configuração encontrados:")
        for error in config_errors:
            print(f"   - {error}")
        success = False
    else:
        print("✅ Configurações validadas com sucesso!")
    
    print("\n" + "=" * 50)
    if success:
        print("✅ Configuração concluída com sucesso!")
        print("\n📋 Próximos passos:")
        print("1. Edite o arquivo environment.json com suas credenciais")
        print("2. Edite o arquivo Conexoes.txt com suas regionais")
        print("3. Execute: python executar_tudo.py")
    else:
        print("❌ Configuração concluída com erros!")
        print("Corrija os problemas acima antes de continuar.")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)