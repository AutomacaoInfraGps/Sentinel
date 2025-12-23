#!/usr/bin/env python3
"""
Script para atualização automática dos dados em segundo plano
Executa verificações periódicas e gera os arquivos necessários para os cards
"""

import time
import subprocess
import os
import sys
from pathlib import Path
from datetime import datetime
import json

# Configuração para Windows - força UTF-8
if sys.platform == "win32":
    import codecs
    
    # Tenta configurar UTF-8 para saída
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer)
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer)
    except:
        # Se falhar, não usa emojis
        pass

# Importa configurações
from config import (
    PROJECT_ROOT, OUTPUT_DIR, REPLICACAO_HTML, UNIFI_HTML,
    ensure_directories
)

def log(mensagem):
    """Registra mensagem de log com timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Substitui emojis por texto no Windows
    if sys.platform == "win32":
        mensagem = mensagem.replace('🔄', '[ATUALIZANDO]')
        mensagem = mensagem.replace('✅', '[OK]')
        mensagem = mensagem.replace('❌', '[ERRO]')
        mensagem = mensagem.replace('⏱️', '[TIMEOUT]')
        mensagem = mensagem.replace('🛑', '[PARADO]')
    
    print(f"[{timestamp}] {mensagem}")
    sys.stdout.flush()  # Força a saída imediata

def executar_comando(comando, descricao):
    """Executa um comando e retorna se foi bem-sucedido"""
    log(f"Executando {descricao}...")
    try:
        # Configura ambiente para forçar UTF-8 no Windows
        env = os.environ.copy()
        if sys.platform == "win32":
            env["PYTHONIOENCODING"] = "utf-8"
        
        # Executa o comando como um módulo Python
        modulo = comando.split()[0]
        args = comando.split()[1:] if len(comando.split()) > 1 else []
        
        resultado = subprocess.run(
            [sys.executable, modulo] + args,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300  # 5 minutos de timeout
        )
        
        if resultado.returncode == 0:
            log(f"[OK] {descricao} concluído com sucesso")
            return True
        else:
            erro = resultado.stderr.replace('\u2705', '[OK]').replace('\u274c', '[ERRO]')
            log(f"[ERRO] Falha ao executar {descricao}: {erro}")
            return False
    except subprocess.TimeoutExpired:
        log(f"[TIMEOUT] Timeout ao executar {descricao}")
        return False
    except Exception as e:
        log(f"[ERRO] Exceção ao executar {descricao}: {str(e)}")
        return False

def verificar_replicacao_ad():
    """Verifica replicação do Active Directory"""
    return executar_comando(
        str(PROJECT_ROOT / 'get_replicacao_path.py'),
        "verificação de replicação AD"
    )

def verificar_antenas_unifi():
    """Verifica status das antenas UniFi"""
    # Cria um script temporário sem emojis
    script_unifi_safe = PROJECT_ROOT / 'unifi_safe.py'
    try:
        with open(PROJECT_ROOT / 'Unifi.py', 'r', encoding='utf-8') as original:
            conteudo = original.read()
        
        # Substitui emojis por texto
        conteudo = conteudo.replace('\u2705', '[OK]').replace('\u274c', '[ERRO]')
        
        with open(script_unifi_safe, 'w', encoding='utf-8') as temp:
            temp.write(conteudo)
        
        return executar_comando(
            str(script_unifi_safe),
            "verificação de antenas UniFi"
        )
    except Exception as e:
        log(f"[ERRO] Falha ao preparar script UniFi: {str(e)}")
        return False
    finally:
        # Limpa o arquivo temporário
        if script_unifi_safe.exists():
            try:
                script_unifi_safe.unlink()
            except Exception as e:
                print(f"Erro em {__file__}: {e}")

def verificar_servidores():
    """Verifica status dos servidores"""
    # Cria um script temporário sem emojis
    script_servidores_safe = PROJECT_ROOT / 'verificar_servidores_safe.py'
    try:
        with open(PROJECT_ROOT / 'verificar_servidores_v2.py', 'r', encoding='utf-8') as original:
            conteudo = original.read()
        
        # Substitui emojis por texto
        conteudo = conteudo.replace('\U0001f5a5\ufe0f', '[PC]').replace('\u2705', '[OK]').replace('\u274c', '[ERRO]')
        
        with open(script_servidores_safe, 'w', encoding='utf-8') as temp:
            temp.write(conteudo)
        
        return executar_comando(
            f"{script_servidores_safe} --modo=rapido",
            "verificação de servidores"
        )
    except Exception as e:
        log(f"[ERRO] Falha ao preparar script de servidores: {str(e)}")
        return False
    finally:
        # Limpa o arquivo temporário
        if script_servidores_safe.exists():
            try:
                script_servidores_safe.unlink()
            except Exception as e:
                print(f"Erro em {__file__}: {e}")

def salvar_status_atualizacao(status):
    """Salva o status da última atualização"""
    status_file = OUTPUT_DIR / "status_atualizacao.json"
    
    try:
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        log(f"❌ Erro ao salvar status: {str(e)}")

def main():
    """Função principal"""
    log("🔄 Iniciando serviço de atualização automática de dados")
    
    # Garante que os diretórios existem
    ensure_directories()
    
    # Cria o arquivo de status inicial
    status_inicial = {
        "timestamp": datetime.now().isoformat(),
        "status": "iniciando",
        "mensagem": "Serviço de atualização iniciado",
        "proximas_verificacoes": {
            "replicacao_ad": 0,
            "antenas_unifi": 0,
            "servidores": 0
        }
    }
    salvar_status_atualizacao(status_inicial)
    
    # Intervalo entre verificações (em segundos)
    intervalo_replicacao = 300  # 5 minutos
    intervalo_unifi = 180       # 3 minutos
    intervalo_servidores = 120  # 2 minutos
    
    # Contadores para controle de tempo
    contador_replicacao = intervalo_replicacao
    contador_unifi = intervalo_unifi
    contador_servidores = intervalo_servidores
    
    # Executa verificação inicial
    log("Executando verificação inicial...")
    verificar_replicacao_ad()
    verificar_antenas_unifi()
    verificar_servidores()
    
    try:
        while True:
            # Incrementa contadores
            contador_replicacao += 10
            contador_unifi += 10
            contador_servidores += 10
            
            # Verifica se é hora de executar cada verificação
            if contador_replicacao >= intervalo_replicacao:
                verificar_replicacao_ad()
                contador_replicacao = 0
            
            if contador_unifi >= intervalo_unifi:
                verificar_antenas_unifi()
                contador_unifi = 0
            
            if contador_servidores >= intervalo_servidores:
                verificar_servidores()
                contador_servidores = 0
            
            # Salva status da última atualização
            status = {
                "timestamp": datetime.now().isoformat(),
                "status": "ativo",
                "mensagem": "Serviço de atualização em execução",
                "proximas_verificacoes": {
                    "replicacao_ad": intervalo_replicacao - contador_replicacao,
                    "antenas_unifi": intervalo_unifi - contador_unifi,
                    "servidores": intervalo_servidores - contador_servidores
                },
                "arquivos": {
                    "replicacao_html": os.path.exists(REPLICACAO_HTML),
                    "unifi_html": os.path.exists(UNIFI_HTML)
                }
            }
            salvar_status_atualizacao(status)
            
            # Aguarda 10 segundos antes da próxima iteração
            time.sleep(10)
            
    except KeyboardInterrupt:
        log("🛑 Serviço de atualização interrompido pelo usuário")
        # Salva status final
        status_final = {
            "timestamp": datetime.now().isoformat(),
            "status": "parado",
            "mensagem": "Serviço de atualização interrompido pelo usuário"
        }
        salvar_status_atualizacao(status_final)
    except Exception as e:
        erro_msg = str(e)
        log(f"❌ Erro no serviço de atualização: {erro_msg}")
        # Salva status de erro
        status_erro = {
            "timestamp": datetime.now().isoformat(),
            "status": "erro",
            "mensagem": f"Erro no serviço: {erro_msg}"
        }
        salvar_status_atualizacao(status_erro)

if __name__ == "__main__":
    main()