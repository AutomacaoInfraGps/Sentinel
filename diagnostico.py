#!/usr/bin/env python3
"""
Script de diagnóstico para verificar o estado do sistema
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).parent.absolute()

def verificar_diretorios():
    """Verifica se os diretórios necessários existem"""
    diretorios = [
        "data",
        "output",
        "logs",
        "templates"
    ]
    
    resultados = {}
    
    for diretorio in diretorios:
        caminho = PROJECT_ROOT / diretorio
        resultados[diretorio] = {
            "existe": caminho.exists(),
            "caminho": str(caminho)
        }
        
        if caminho.exists():
            resultados[diretorio]["arquivos"] = len(list(caminho.glob("*")))
    
    return resultados

def verificar_arquivos_json():
    """Verifica os arquivos JSON no diretório de dados"""
    data_dir = PROJECT_ROOT / "data"
    
    if not data_dir.exists():
        return {"erro": "Diretório de dados não existe"}
    
    resultados = {}
    
    for arquivo in data_dir.glob("*.json"):
        try:
            with open(arquivo, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            
            tamanho = os.path.getsize(arquivo)
            timestamp = arquivo.stat().st_mtime
            data_mod = datetime.fromtimestamp(timestamp).isoformat()
            
            resultados[arquivo.name] = {
                "tamanho": tamanho,
                "ultima_modificacao": data_mod,
                "valido": True,
                "chaves": list(dados.keys()) if isinstance(dados, dict) else None
            }
        except Exception as e:
            resultados[arquivo.name] = {
                "erro": str(e),
                "valido": False
            }
    
    return resultados

def verificar_modulos():
    """Verifica se os módulos principais existem"""
    modulos = [
        "config.py",
        "data_store.py",
        "web_config.py",
        "Unifi.py",
        "Replicacao_Servers.ps1"
    ]
    
    resultados = {}
    
    for modulo in modulos:
        caminho = PROJECT_ROOT / modulo
        resultados[modulo] = {
            "existe": caminho.exists(),
            "tamanho": os.path.getsize(caminho) if caminho.exists() else 0,
            "ultima_modificacao": datetime.fromtimestamp(caminho.stat().st_mtime).isoformat() if caminho.exists() else None
        }
    
    return resultados

def gerar_relatorio():
    """Gera um relatório completo de diagnóstico"""
    relatorio = {
        "timestamp": datetime.now().isoformat(),
        "sistema": {
            "python_version": sys.version,
            "platform": sys.platform,
            "cwd": os.getcwd(),
            "project_root": str(PROJECT_ROOT)
        },
        "diretorios": verificar_diretorios(),
        "arquivos_json": verificar_arquivos_json(),
        "modulos": verificar_modulos()
    }
    
    return relatorio

def main():
    """Função principal"""
    print("=== Diagnóstico do Sistema ===")
    
    relatorio = gerar_relatorio()
    
    # Salva o relatório
    output_file = PROJECT_ROOT / "diagnostico.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(relatorio, f, indent=2)
    
    print(f"Relatório salvo em: {output_file}")
    
    # Exibe um resumo
    print("\n=== Resumo ===")
    print(f"Diretórios verificados: {len(relatorio['diretorios'])}")
    print(f"Arquivos JSON verificados: {len(relatorio['arquivos_json'])}")
    print(f"Módulos verificados: {len(relatorio['modulos'])}")
    
    # Verifica problemas
    problemas = []
    
    for diretorio, info in relatorio["diretorios"].items():
        if not info["existe"]:
            problemas.append(f"Diretório não encontrado: {diretorio}")
    
    for arquivo, info in relatorio["arquivos_json"].items():
        if not info.get("valido", False):
            problemas.append(f"Arquivo JSON inválido: {arquivo}")
    
    for modulo, info in relatorio["modulos"].items():
        if not info["existe"]:
            problemas.append(f"Módulo não encontrado: {modulo}")
    
    if problemas:
        print("\n=== Problemas Encontrados ===")
        for problema in problemas:
            print(f"- {problema}")
    else:
        print("\nNenhum problema encontrado!")

if __name__ == "__main__":
    main()