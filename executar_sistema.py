#!/usr/bin/env python3
"""
Script para executar os principais componentes do sistema
"""

import os
import sys
import subprocess
import json
import time
from datetime import datetime
from pathlib import Path

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).parent.absolute()

# Configurações
COMPONENTES = {
    "web": {
        "nome": "Interface Web",
        "script": "iniciar_web.py",
        "descricao": "Inicia o servidor web para acesso à interface do sistema"
    },
    "unifi": {
        "nome": "Verificação de Antenas UniFi",
        "script": "Unifi.py",
        "descricao": "Verifica o status das antenas UniFi e gera relatório"
    },
    "replicacao": {
        "nome": "Verificação de Replicação AD",
        "script": "Replicacao_Servers.ps1",
        "descricao": "Verifica a replicação do Active Directory e gera relatório",
        "powershell": True
    },
    "completo": {
        "nome": "Verificação Completa",
        "script": "executar_tudo_v2.py",
        "descricao": "Executa verificação completa de todos os componentes"
    }
}

# Função para executar um script Python
def executar_python(script_path):
    try:
        print(f"Executando: {script_path}")
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"Saída: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Erro ao executar {script_path}: {e}")
        print(f"Saída de erro: {e.stderr}")
        return False

# Função para executar um script PowerShell
def executar_powershell(script_path):
    try:
        print(f"Executando PowerShell: {script_path}")
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"Saída: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Erro ao executar {script_path}: {e}")
        print(f"Saída de erro: {e.stderr}")
        return False

# Função para executar um componente
def executar_componente(componente):
    if componente not in COMPONENTES:
        print(f"Componente '{componente}' não encontrado.")
        return False
    
    info = COMPONENTES[componente]
    print(f"\n=== Executando {info['nome']} ===")
    print(f"Descrição: {info['descricao']}")
    
    script_path = PROJECT_ROOT / info['script']
    
    # Verifica se o script existe
    if not script_path.exists():
        # Tenta encontrar em subdiretórios
        for subdir in ["scripts", "web", "core"]:
            alt_path = PROJECT_ROOT / subdir / info['script']
            if alt_path.exists():
                script_path = alt_path
                break
    
    if not script_path.exists():
        print(f"Erro: Script '{info['script']}' não encontrado.")
        return False
    
    # Executa o script
    if info.get('powershell', False):
        return executar_powershell(script_path)
    else:
        return executar_python(script_path)

# Função para mostrar o menu
def mostrar_menu():
    print("\n=== Sistema de Automação ===")
    print("Escolha um componente para executar:")
    
    for i, (key, info) in enumerate(COMPONENTES.items(), 1):
        print(f"{i}. {info['nome']} - {info['descricao']}")
    
    print("0. Sair")
    
    while True:
        try:
            escolha = int(input("\nDigite o número da opção desejada: "))
            if escolha == 0:
                return None
            elif 1 <= escolha <= len(COMPONENTES):
                return list(COMPONENTES.keys())[escolha - 1]
            else:
                print("Opção inválida. Tente novamente.")
        except ValueError:
            print("Por favor, digite um número válido.")

# Função principal
def main():
    print("=== Sistema de Automação ===")
    
    # Verifica se foi passado um componente como argumento
    if len(sys.argv) > 1:
        componente = sys.argv[1].lower()
        if componente in COMPONENTES:
            executar_componente(componente)
        else:
            print(f"Componente '{componente}' não encontrado.")
            print(f"Componentes disponíveis: {', '.join(COMPONENTES.keys())}")
    else:
        # Mostra o menu interativo
        while True:
            componente = mostrar_menu()
            if componente is None:
                break
            
            executar_componente(componente)
            input("\nPressione Enter para continuar...")

if __name__ == "__main__":
    main()