#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Teste de debug dos servidores iDRAC
"""

import subprocess
import sys
from pathlib import Path

print("🔍 Teste de Debug dos Servidores iDRAC")
print("=" * 60)

PROJECT_ROOT = Path(__file__).parent

# Lista de servidores para testar
servidores = [
    {"nome": "RG_EXEMPLO_01", "ip": "192.0.2.10", "usuario": "root", "senha": "ALTERE_AQUI", "tipo": "idrac"},
    {"nome": "RG_EXEMPLO_02", "ip": "192.0.2.11", "usuario": "root", "senha": "ALTERE_AQUI", "tipo": "idrac"},
    {"nome": "RG_EXEMPLO_03", "ip": "192.0.2.12", "usuario": "root", "senha": "ALTERE_AQUI", "tipo": "idrac"},
    {"nome": "RG_EXEMPLO_04", "ip": "192.0.2.13", "usuario": "admin", "senha": "ALTERE_AQUI", "tipo": "ilo"}
]

for servidor in servidores:
    nome = servidor["nome"]
    ip = servidor["ip"]
    usuario = servidor["usuario"]
    senha = servidor["senha"]
    tipo = servidor["tipo"]
    
    print(f"\n🔍 Testando {nome} ({ip}) - {tipo.upper()}")
    
    # Define o arquivo de saída
    nome_arquivo = nome.lower().replace(" ", "_").replace("ã", "a").replace("ç", "c")
    html_path = PROJECT_ROOT / "output" / "teste_debug" / f"{nome_arquivo}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        if tipo == "idrac":
            chelist_path = PROJECT_ROOT / "Chelist.py"
            print(f"   📄 Script: {chelist_path}")
            print(f"   📁 Saída: {html_path}")
            
            # Executa exatamente como no executar_tudo.py
            result = subprocess.run(
                ["python", str(chelist_path), ip, usuario, senha, str(html_path)], 
                check=True, 
                cwd=str(PROJECT_ROOT), 
                capture_output=True, 
                text=True,
                timeout=30
            )
            
            print(f"   ✅ Sucesso! Código de saída: {result.returncode}")
            if result.stdout:
                print(f"   📤 Saída: {result.stdout}")
            
        elif tipo == "ilo":
            ilo_path = PROJECT_ROOT / "iLOcheck.py"
            print(f"   📄 Script: {ilo_path}")
            print(f"   📁 Saída: {html_path}")
            
            result = subprocess.run(
                ["python", str(ilo_path), ip, usuario, senha, str(html_path)], 
                check=True, 
                cwd=str(PROJECT_ROOT), 
                capture_output=True, 
                text=True,
                timeout=30
            )
            
            print(f"   ✅ Sucesso! Código de saída: {result.returncode}")
            if result.stdout:
                print(f"   📤 Saída: {result.stdout}")
        
        # Verifica se o arquivo foi criado
        if html_path.exists():
            size = html_path.stat().st_size
            print(f"   📊 Arquivo criado: {size} bytes")
        else:
            print(f"   ❌ Arquivo não foi criado!")
            
    except subprocess.TimeoutExpired:
        print(f"   ⏰ Timeout ao conectar com {ip}")
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Erro no script: Código {e.returncode}")
        if e.stdout:
            print(f"   📤 Saída: {e.stdout}")
        if e.stderr:
            print(f"   📥 Erro: {e.stderr}")
    except Exception as e:
        print(f"   ❌ Erro inesperado: {e}")

print("\n" + "=" * 60)
print("✅ Teste concluído!")