#!/usr/bin/env python3
"""
Script para limpar arquivos desnecessários do projeto
"""

import os
import shutil
import json
from datetime import datetime
from pathlib import Path

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).parent.absolute()

# Cria um backup antes de limpar
def criar_backup():
    backup_dir = PROJECT_ROOT / f"backup_limpeza_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(exist_ok=True)
    
    print(f"Criando backup em: {backup_dir}")
    
    # Copia apenas os arquivos essenciais para o backup
    arquivos_essenciais = [
        "config.py",
        "web_config.py",
        "iniciar_web.py",
        "Unifi.py",
        "Replicacao_Servers.ps1",
        "data_store.py",
        "servidores.json",
        "environment.json"
    ]
    
    for arquivo in arquivos_essenciais:
        if (PROJECT_ROOT / arquivo).exists():
            shutil.copy2(PROJECT_ROOT / arquivo, backup_dir)
    
    # Copia diretório de templates
    if (PROJECT_ROOT / "templates").exists():
        shutil.copytree(PROJECT_ROOT / "templates", backup_dir / "templates")
    
    return backup_dir

# Arquivos temporários para remover
def limpar_arquivos_temporarios():
    print("\nLimpando arquivos temporários...")
    
    # Extensões de arquivos temporários
    extensoes_temp = [".tmp", ".bak", ".pyc", ".pyo", ".pyd", ".~"]
    
    # Arquivos temporários específicos
    arquivos_temp = [
        "print_temp.html",
        "test.ldif",
        "teste_cards.html"
    ]
    
    count = 0
    
    # Remove arquivos temporários por extensão
    for ext in extensoes_temp:
        for arquivo in PROJECT_ROOT.glob(f"**/*{ext}"):
            if arquivo.is_file():
                arquivo.unlink()
                print(f"  Removido: {arquivo.relative_to(PROJECT_ROOT)}")
                count += 1
    
    # Remove arquivos temporários específicos
    for nome in arquivos_temp:
        for arquivo in PROJECT_ROOT.glob(f"**/{nome}"):
            if arquivo.is_file():
                arquivo.unlink()
                print(f"  Removido: {arquivo.relative_to(PROJECT_ROOT)}")
                count += 1
    
    print(f"Total de arquivos temporários removidos: {count}")

# Limpar diretório de cache
def limpar_cache():
    print("\nLimpando diretórios de cache...")
    
    # Diretórios de cache
    diretorios_cache = [
        "__pycache__"
    ]
    
    count = 0
    
    for nome in diretorios_cache:
        for diretorio in PROJECT_ROOT.glob(f"**/{nome}"):
            if diretorio.is_dir():
                shutil.rmtree(diretorio)
                print(f"  Removido: {diretorio.relative_to(PROJECT_ROOT)}")
                count += 1
    
    print(f"Total de diretórios de cache removidos: {count}")

# Limpar relatórios antigos
def limpar_relatorios_antigos():
    print("\nLimpando relatórios antigos...")
    
    # Diretório de saída
    output_dir = PROJECT_ROOT / "output"
    
    if not output_dir.exists():
        print("Diretório de saída não encontrado.")
        return
    
    # Padrões de arquivos de relatório
    padroes_relatorio = [
        "relatorio_completo_*.txt"
    ]
    
    count = 0
    
    # Mantém apenas o relatório mais recente de cada tipo
    for padrao in padroes_relatorio:
        arquivos = list(output_dir.glob(padrao))
        arquivos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        # Mantém o mais recente, remove os demais
        if arquivos:
            print(f"  Mantendo o relatório mais recente: {arquivos[0].name}")
            for arquivo in arquivos[1:]:
                arquivo.unlink()
                print(f"  Removido: {arquivo.relative_to(PROJECT_ROOT)}")
                count += 1
    
    print(f"Total de relatórios antigos removidos: {count}")

# Limpar backups antigos
def limpar_backups_antigos():
    print("\nLimpando backups antigos...")
    
    # Padrões de diretórios de backup
    padroes_backup = [
        "backup_projeto_*",
        "backup_antes_limpeza_*"
    ]
    
    count = 0
    
    # Para cada padrão, mantém apenas o backup mais recente
    for padrao in padroes_backup:
        diretorios = list(PROJECT_ROOT.glob(padrao))
        diretorios.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        # Mantém o mais recente, remove os demais
        if diretorios:
            print(f"  Mantendo o backup mais recente: {diretorios[0].name}")
            for diretorio in diretorios[1:]:
                shutil.rmtree(diretorio)
                print(f"  Removido: {diretorio.relative_to(PROJECT_ROOT)}")
                count += 1
    
    print(f"Total de backups antigos removidos: {count}")

# Limpar arquivos de teste
def limpar_arquivos_teste():
    print("\nLimpando arquivos de teste...")
    
    # Padrões de arquivos de teste
    padroes_teste = [
        "test_*.py",
        "testar_*.py",
        "debug_*.py"
    ]
    
    count = 0
    
    for padrao in padroes_teste:
        for arquivo in PROJECT_ROOT.glob(padrao):
            if arquivo.is_file():
                arquivo.unlink()
                print(f"  Removido: {arquivo.relative_to(PROJECT_ROOT)}")
                count += 1
    
    print(f"Total de arquivos de teste removidos: {count}")

# Função principal
def main():
    print("=== Limpeza de Arquivos do Projeto ===")
    
    # Cria backup antes de limpar
    backup_dir = criar_backup()
    
    # Executa as funções de limpeza
    limpar_arquivos_temporarios()
    limpar_cache()
    limpar_relatorios_antigos()
    limpar_backups_antigos()
    limpar_arquivos_teste()
    
    # Cria relatório de limpeza
    relatorio = {
        "data": datetime.now().isoformat(),
        "backup_criado": str(backup_dir),
        "mensagem": "Limpeza de arquivos concluída com sucesso."
    }
    
    with open(PROJECT_ROOT / "relatorio_limpeza.json", "w", encoding="utf-8") as f:
        json.dump(relatorio, f, indent=2)
    
    print("\n=== Limpeza concluída com sucesso! ===")
    print(f"Backup criado em: {backup_dir}")
    print(f"Relatório de limpeza salvo em: {PROJECT_ROOT / 'relatorio_limpeza.json'}")

if __name__ == "__main__":
    main()