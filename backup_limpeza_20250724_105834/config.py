"""
Configurações centralizadas do sistema de automação.
Este arquivo define todos os caminhos e configurações de forma dinâmica.
"""

import os
import json
from pathlib import Path

# === DIRETÓRIOS BASE ===
# Diretório raiz do projeto (onde estão os scripts)
PROJECT_ROOT = Path(__file__).parent.absolute()

# Diretório de saída para arquivos gerados
OUTPUT_DIR = PROJECT_ROOT / "output"

# Diretório para HTMLs regionais temporários
REGIONAL_HTMLS_DIR = OUTPUT_DIR / "htmls_regionais"

# Diretório para logs
LOGS_DIR = PROJECT_ROOT / "logs"

# === ARQUIVOS DE ENTRADA ===
# Arquivo com as conexões das regionais (formato legado)
CONEXOES_FILE = PROJECT_ROOT / "Conexoes.txt"

# Arquivo com servidores no novo formato JSON
SERVIDORES_FILE = PROJECT_ROOT / "servidores.json"

# === ARQUIVOS DE SAÍDA ===
# Dashboard final consolidado
DASHBOARD_FINAL = OUTPUT_DIR / "dashboard_final.html"

# Status do servidor NAOS
STATUS_NAOS_HTML = OUTPUT_DIR / "status_Naos.html"

# Arquivos temporários gerados pelos scripts
GPS_HTML = OUTPUT_DIR / "print_temp.html"
REPLICACAO_HTML = OUTPUT_DIR / "replsummary.html"
UNIFI_HTML = OUTPUT_DIR / "dados_aps_unifi.html"

# === CARREGAMENTO DE CONFIGURAÇÕES DO AMBIENTE ===
def load_environment_config():
    """Carrega as configurações do arquivo environment.json"""
    env_file = PROJECT_ROOT / "environment.json"
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"⚠️ Erro ao carregar environment.json: {e}")
            return {}
    else:
        print(f"⚠️ Arquivo environment.json não encontrado em: {env_file}")
        return {}

# Carrega as configurações do ambiente
ENV_CONFIG = load_environment_config()

# === CONFIGURAÇÕES DE SERVIDOR ===
# Configurações do servidor NAOS
NAOS_CONFIG = ENV_CONFIG.get("naos_server", {
    "ip": "192.168.21.27",
    "usuario": "galaxia\\admin.lima",
    "senha": "Akin21@@grupogps",
})

# Configurações do controlador UniFi
UNIFI_CONFIG = ENV_CONFIG.get("unifi_controller", {
    "host": "192.168.21.28",
    "port": 8443,
    "username": "admin.lima",
    "password": "Akin21@@grupogps"
})

# Configurações do GPS Amigo
GPS_CONFIG = ENV_CONFIG.get("gps_amigo", {
    "url": "https://gpsamigo.com.br/login.php"
})

# === CONFIGURAÇÕES DE EXECUÇÃO ===
# Configurações de timeout e execução
TIMEOUTS = ENV_CONFIG.get("timeouts", {
    "connection_timeout": 10,
    "max_retries": 3
})

CONNECTION_TIMEOUT = TIMEOUTS["connection_timeout"]
MAX_RETRIES = TIMEOUTS["max_retries"]

# Configurações de limpeza
CLEANUP_CONFIG = ENV_CONFIG.get("cleanup", {
    "remove_temp_files": True,
    "keep_logs": True
})

# === FUNÇÕES AUXILIARES ===
def ensure_directories():
    """Cria os diretórios necessários se não existirem."""
    directories = [OUTPUT_DIR, REGIONAL_HTMLS_DIR, LOGS_DIR]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

def get_log_file(script_name):
    """Retorna o caminho para o arquivo de log de um script específico."""
    ensure_directories()
    return LOGS_DIR / f"{script_name}_{Path().cwd().name}.log"

def get_regional_html_path(nome_regional):
    """Retorna o caminho para o HTML de uma regional específica."""
    ensure_directories()
    nome_slug = nome_regional.lower().replace(" ", "_").replace("/", "_")
    return REGIONAL_HTMLS_DIR / f"{nome_slug}.html"

def get_relative_path(file_path):
    """Converte um caminho absoluto para relativo ao diretório do projeto."""
    try:
        return Path(file_path).relative_to(PROJECT_ROOT)
    except ValueError:
        return Path(file_path)

# === VALIDAÇÕES ===
def validate_config():
    """Valida se as configurações estão corretas."""
    errors = []
    
    # Verifica se o arquivo de conexões existe
    if not CONEXOES_FILE.exists():
        errors.append(f"Arquivo de conexões não encontrado: {CONEXOES_FILE}")
    
    # Verifica se o diretório do projeto é válido
    if not PROJECT_ROOT.exists():
        errors.append(f"Diretório do projeto não encontrado: {PROJECT_ROOT}")
    
    return errors

# Executa validações na importação
if __name__ == "__main__":
    errors = validate_config()
    if errors:
        print("❌ Erros de configuração encontrados:")
        for error in errors:
            print(f"   - {error}")
    else:
        print("✅ Configurações validadas com sucesso!")
        print(f"📁 Diretório do projeto: {PROJECT_ROOT}")
        print(f"📁 Diretório de saída: {OUTPUT_DIR}")