#!/usr/bin/env python3
"""
Gerenciador de Atualizações em Paralelo
Executa verificações independentes para cada componente do sistema
"""

import sys
import subprocess
import threading
import time
import json
import os
from datetime import datetime
from pathlib import Path

# Importa configurações
from config import PROJECT_ROOT, ensure_directories

# Diretório de saída
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Arquivo de status
STATUS_FILE = OUTPUT_DIR / "status_atualizacao.json"

# Configuração para Windows - força UTF-8
if sys.platform == "win32":
    import codecs
    
    # Tenta configurar UTF-8 para saída
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except Exception as e:
        print(f"Erro em {__file__}: {e}")

def log_message(message):
    """Registra mensagem com timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")
    sys.stdout.flush()

def run_script(script_path, args=None, timeout=300):
    """Executa um script Python"""
    if args is None:
        args = []
    
    try:
        # Configura ambiente para UTF-8
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        # Executa o script
        cmd = [sys.executable, str(script_path)] + args
        log_message(f"Executando: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout
        )
        
        if result.returncode == 0:
            log_message(f"Script {script_path.name} executado com sucesso")
            return True
        else:
            log_message(f"Erro ao executar {script_path.name}: {result.stderr}")
            return False
    
    except subprocess.TimeoutExpired:
        log_message(f"Timeout ao executar {script_path.name}")
        return False
    except Exception as e:
        log_message(f"Exceção ao executar {script_path.name}: {str(e)}")
        return False

def run_powershell_script(script_path, args=None, timeout=300):
    """Executa um script PowerShell"""
    if args is None:
        args = []
    
    try:
        # Executa o script PowerShell
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)] + args
        log_message(f"Executando PowerShell: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout
        )
        
        if result.returncode == 0:
            log_message(f"Script PowerShell {script_path.name} executado com sucesso")
            return True
        else:
            log_message(f"Erro ao executar PowerShell {script_path.name}: {result.stderr}")
            return False
    
    except subprocess.TimeoutExpired:
        log_message(f"Timeout ao executar PowerShell {script_path.name}")
        return False
    except Exception as e:
        log_message(f"Exceção ao executar PowerShell {script_path.name}: {str(e)}")
        return False

def update_status(component, next_update_seconds):
    """Atualiza o status de um componente"""
    try:
        # Lê o status atual
        status = {}
        if STATUS_FILE.exists():
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                status = json.load(f)
        
        # Inicializa se não existir
        if 'timestamp' not in status:
            status['timestamp'] = datetime.now().isoformat()
        if 'status' not in status:
            status['status'] = 'ativo'
        if 'mensagem' not in status:
            status['mensagem'] = 'Serviço de atualização em execução'
        if 'proximas_verificacoes' not in status:
            status['proximas_verificacoes'] = {}
        if 'arquivos' not in status:
            status['arquivos'] = {}
        
        # Atualiza o timestamp
        status['timestamp'] = datetime.now().isoformat()
        
        # Atualiza o componente específico
        status['proximas_verificacoes'][component] = next_update_seconds
        
        # Salva o status
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2)
        
        return True
    except Exception as e:
        log_message(f"Erro ao atualizar status: {str(e)}")
        return False

def check_replication():
    """Verifica replicação AD"""
    interval = 300  # 5 minutos
    
    while True:
        try:
            log_message("Verificando replicação AD...")
            
            # Importa a função executar_repadmin do módulo web_config
            try:
                from web_config import executar_repadmin
                
                # Executa a função
                result = executar_repadmin()
                
                if result["success"]:
                    # Obtém os dados de replicação
                    replicacao_data = result["data"]
                    
                    # Salva os dados em formato JSON
                    import json
                    json_path = PROJECT_ROOT / "data" / "replicacao.json"
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(replicacao_data, f, indent=2, ensure_ascii=False)
                    
                    log_message(f"Dados de replicação AD atualizados: {len(replicacao_data['servidores'])} servidores")
                    success = True
                else:
                    log_message(f"Erro ao executar verificação de replicação: {result['error']}")
                    success = False
            except ImportError:
                log_message("Função executar_repadmin não encontrada, usando script PowerShell")
                
                # Executa o script PowerShell (versão web que não abre o HTML)
                script_path = PROJECT_ROOT / "Replicacao_Servers_Web.ps1"
                success = run_powershell_script(script_path)
            
            # Atualiza o status
            update_status('replicacao_ad', interval)
            
            # Verifica se o arquivo foi gerado
            replicacao_json = PROJECT_ROOT / "data" / "replicacao.json"
            if replicacao_json.exists():
                log_message(f"Arquivo de replicação gerado: {replicacao_json}")
            else:
                log_message("Arquivo de replicação não foi gerado")
        
        except Exception as e:
            log_message(f"Erro ao verificar replicação AD: {str(e)}")
        
        # Aguarda o intervalo
        time.sleep(interval)

def check_unifi():
    """Verifica antenas UniFi"""
    interval = 180  # 3 minutos
    
    while True:
        try:
            log_message("Verificando antenas UniFi...")
            
            # Executa o script Python
            script_path = PROJECT_ROOT / "Unifi.py"
            success = run_script(script_path)
            
            # Atualiza o status
            update_status('antenas_unifi', interval)
            
            # Verifica se o arquivo foi gerado
            unifi_html = PROJECT_ROOT / "output" / "dados_aps_unifi.html"
            if unifi_html.exists():
                log_message(f"Arquivo UniFi gerado: {unifi_html}")
            else:
                log_message("Arquivo UniFi não foi gerado")
        
        except Exception as e:
            log_message(f"Erro ao verificar antenas UniFi: {str(e)}")
        
        # Aguarda o intervalo
        time.sleep(interval)

def check_servers():
    """Verifica servidores"""
    interval = 120  # 2 minutos
    
    while True:
        try:
            log_message("Verificando servidores...")
            
            # Executa o script Python
            script_path = PROJECT_ROOT / "verificar_servidores_v2.py"
            success = run_script(script_path, ["--modo=rapido"])
            
            # Atualiza o status
            update_status('servidores', interval)
            
            # Verifica se os arquivos foram gerados
            dashboard_file = PROJECT_ROOT / "output" / "dashboard_hierarquico.html"
            if dashboard_file.exists():
                log_message(f"Dashboard hierárquico gerado: {dashboard_file}")
            else:
                log_message("Dashboard hierárquico não foi gerado")
        
        except Exception as e:
            log_message(f"Erro ao verificar servidores: {str(e)}")
        
        # Aguarda o intervalo
        time.sleep(interval)

def check_gps():
    """Verifica GPS Amigo"""
    interval = 600  # 10 minutos
    
    while True:
        try:
            log_message("Verificando GPS Amigo...")
            
            # Executa o script Python
            script_path = PROJECT_ROOT / "utilizarSession.py"
            success = run_script(script_path)
            
            # Atualiza o status
            update_status('gps_amigo', interval)
            
            # Verifica se o arquivo foi gerado
            gps_html = PROJECT_ROOT / "output" / "print_temp.html"
            if gps_html.exists():
                log_message(f"Arquivo GPS gerado: {gps_html}")
            else:
                log_message("Arquivo GPS não foi gerado")
        
        except Exception as e:
            log_message(f"Erro ao verificar GPS Amigo: {str(e)}")
        
        # Aguarda o intervalo
        time.sleep(interval)

def start_update_threads():
    """Inicia as threads de atualização"""
    # Garante que os diretórios existem
    ensure_directories()
    
    # Inicializa o arquivo de status
    status = {
        "timestamp": datetime.now().isoformat(),
        "status": "ativo",
        "mensagem": "Serviço de atualização em execução",
        "proximas_verificacoes": {
            "replicacao_ad": 0,
            "antenas_unifi": 0,
            "servidores": 0,
            "gps_amigo": 0
        },
        "arquivos": {}
    }
    
    try:
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        log_message(f"Erro ao inicializar arquivo de status: {str(e)}")
    
    # Inicia as threads
    threads = []
    
    # Thread de replicação AD
    replication_thread = threading.Thread(target=check_replication, daemon=True)
    replication_thread.start()
    threads.append(replication_thread)
    
    # Thread de antenas UniFi
    unifi_thread = threading.Thread(target=check_unifi, daemon=True)
    unifi_thread.start()
    threads.append(unifi_thread)
    
    # Thread de servidores
    servers_thread = threading.Thread(target=check_servers, daemon=True)
    servers_thread.start()
    threads.append(servers_thread)
    
    # Thread de GPS Amigo
    gps_thread = threading.Thread(target=check_gps, daemon=True)
    gps_thread.start()
    threads.append(gps_thread)
    
    return threads

if __name__ == "__main__":
    log_message("Iniciando gerenciador de atualizações em paralelo")
    
    try:
        # Inicia as threads
        threads = start_update_threads()
        
        # Aguarda as threads (nunca termina, pois são daemon)
        for thread in threads:
            thread.join()
    
    except KeyboardInterrupt:
        log_message("Gerenciador de atualizações interrompido pelo usuário")
    except Exception as e:
        log_message(f"Erro no gerenciador de atualizações: {str(e)}")