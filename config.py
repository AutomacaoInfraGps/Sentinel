"""
Configurações centralizadas do sistema de automação.
Este arquivo define todos os caminhos e configurações de forma dinâmica.
"""

import os
import json
from pathlib import Path
from datetime import datetime

# === BASE PÚBLICA (para rodar como serviço/Local System) ===
PUBLIC_BASE       = Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Automacao"
DATA_DIR_PUBLIC   = PUBLIC_BASE / "data"
OUTPUT_DIR_PUBLIC = PUBLIC_BASE / "output"

# === DIRETÓRIOS BASE ===
# Diretório raiz do projeto (onde estão os scripts)
def get_project_root():
    """
    Determina o diretório raiz do projeto, considerando se está rodando como executável
    """
    import sys
    
    # Se estiver rodando como executável (cx_Freeze)
    if getattr(sys, 'frozen', False):
        # Quando compilado, sys.executable aponta para o .exe
        return Path(sys.executable).parent.absolute()
    else:
        # Quando rodando como script Python normal
        return Path(__file__).parent.absolute()

PROJECT_ROOT = get_project_root()

# === FUNÇÃO PARA CRIAR ESTRUTURA DE PASTAS PREVENTIVA ===
from datetime import datetime

def get_relatorio_preventiva_path():
    """
    Cria e retorna o caminho para salvar o relatório preventiva
    Estrutura: C:/Users/Public/Automacao/relatorio_preventiva/YYYY/MM/DD/
    """
    now = datetime.now()
    relatorio_base = PUBLIC_BASE / "relatorio_preventiva"
    relatorio_dia  = relatorio_base / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    relatorio_dia.mkdir(parents=True, exist_ok=True)
    return relatorio_dia



# Diretório de saída para arquivos gerados (mantém o original para compatibilidade)
OUTPUT_DIR = PROJECT_ROOT / "output"

# Novo diretório para relatórios preventivos
RELATORIO_PREVENTIVA_DIR = get_relatorio_preventiva_path()

# Diretório para HTMLs regionais temporários
REGIONAL_HTMLS_DIR = OUTPUT_DIR / "htmls_regionais"

# Diretório para logs
LOGS_DIR = PROJECT_ROOT / "logs"

# === ARQUIVOS DE ENTRADA ===
# Arquivo com as conexões das regionais (formato legado)
CONEXOES_FILE = PROJECT_ROOT / "Conexoes.txt"

# Arquivo com servidores no novo formato JSON
SERVIDORES_FILE = PROJECT_ROOT / "servidores.json"

# Arquivo de configuração do ambiente
ENVIRONMENT_FILE = PROJECT_ROOT / "environment.json"

# === ARQUIVOS DE SAÍDA ===
# Função para gerar nome do arquivo com timestamp
def get_dashboard_filename():
    """Gera nome do arquivo dashboard com timestamp"""
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    return f"relatorio_preventiva_{timestamp}.html"

# Dashboard final consolidado - NOVO LOCAL na área de trabalho
DASHBOARD_FINAL = RELATORIO_PREVENTIVA_DIR / get_dashboard_filename()

# Dashboard final consolidado - LOCAL ORIGINAL (para compatibilidade)
DASHBOARD_FINAL_ORIGINAL = OUTPUT_DIR / "dashboard_final.html"

# Status do servidor NAOS
STATUS_NAOS_HTML = OUTPUT_DIR / "status_Naos.html"

# Arquivos temporários gerados pelos scripts
GPS_HTML  = OUTPUT_DIR_PUBLIC / "print_temp.html"          # <-- no Public!
GPS_IMG   = OUTPUT_DIR_PUBLIC / "gps_amigo.png"            # opcional (salva screenshot)
UNIFI_HTML = OUTPUT_DIR / "dados_aps_unifi.html"


# (se você implementou fragmento da replicação, mantenha essa também)
# REPLICACAO_HTML_FRAGMENT = OUTPUT_DIR_PUBLIC / "replsummary_fragment.html"


# Replicação (compat + novo fragmento)
REPLICACAO_HTML = OUTPUT_DIR_PUBLIC / "replsummary.html"                 # legado (o que o executar_tudo.py importa)
REPLICACAO_HTML_FRAGMENT = OUTPUT_DIR_PUBLIC / "replsummary_fragment.html"  # novo (pra embutir no card sem duplicar)
REPLICACAO_JSON = DATA_DIR_PUBLIC / "replicacao.json"


# === CARREGAMENTO DE CONFIGURAÇÕES DO AMBIENTE ===
def load_environment_config():
    """Carrega as configurações do arquivo environment.json"""
    env_file = PROJECT_ROOT / "environment.json"
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"[WARN] Erro ao carregar environment.json: {e}")
            return {}
    else:
        print(f"[WARN] Arquivo environment.json não encontrado em: {env_file}")
        return {}

# Carrega as configurações do ambiente
ENV_CONFIG = load_environment_config()

# === CONFIGURAÇÕES DE SERVIDOR ===
# Importa o módulo de credenciais
try:
    from credentials import get_credentials
except ImportError:
    # Fallback para caso o módulo não esteja disponível
    def get_credentials(service, prompt_if_missing=False):
        return {}

# Configurações do servidor NAOS
naos_creds = get_credentials('naos')
NAOS_CONFIG = ENV_CONFIG.get("naos_server", {
    "ip": naos_creds.get('host', "192.168.21.27"),
    "usuario": naos_creds.get('username', "galaxia\\admin"),
    "senha": naos_creds.get('password', ""),
})

# Configurações do controlador UniFi
unifi_creds = get_credentials('unifi')
UNIFI_CONFIG = ENV_CONFIG.get("unifi_controller", {
    "host": unifi_creds.get('host', "192.168.21.28"),
    "port": unifi_creds.get('port', 8443),
    "username": unifi_creds.get('username', "admin"),
    "password": unifi_creds.get('password', "")
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
    directories = [
        OUTPUT_DIR, REGIONAL_HTMLS_DIR, LOGS_DIR, RELATORIO_PREVENTIVA_DIR,
        DATA_DIR_PUBLIC, OUTPUT_DIR_PUBLIC,  # ← estas duas são essenciais
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    
    # Exibe informações sobre a estrutura criada
    print(f"Diretorios verificados/criados:")
    print(f"   - Output: {OUTPUT_DIR}")
    print(f"   - Regionais: {REGIONAL_HTMLS_DIR}")
    print(f"   - Logs: {LOGS_DIR}")
    print(f"   - Relatorio Preventiva: {RELATORIO_PREVENTIVA_DIR}")

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
        print("[ERROR] Erros de configuração encontrados:")
        for error in errors:
            print(f"   - {error}")
    else:
        print("[OK] Configurações validadas com sucesso!")
        print(f"[DIR] Diretório do projeto: {PROJECT_ROOT}")
        print(f"[DIR] Diretório de saída: {OUTPUT_DIR}")