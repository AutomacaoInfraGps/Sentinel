#!/usr/bin/env python3
"""
Script para organizar a estrutura do projeto
"""

import os
import shutil
import json
from datetime import datetime
from pathlib import Path

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).parent.absolute()

# Estrutura de diretórios desejada
ESTRUTURA = {
    "scripts": [
        "Unifi.py",
        "Replicacao_Servers.ps1",
        "executar_tudo.py",
        "executar_tudo_v2.py",
        "Chelist.py",
        "iLOcheck.py"
    ],
    "web": [
        "iniciar_web.py",
        "web_config.py",
        "web_config_hierarquico.py",
        "auth_ad.py",
        "user_model.py"
    ],
    "core": [
        "config.py",
        "data_store.py",
        "gerenciar_regionais.py",
        "gerenciar_servidores.py",
        "verificar_servidores_v2.py",
        "dashboard_hierarquico.py"
    ],
    "docs": [
        "README.md",
        "CHANGELOG.md",
        "GUIA_CONFIGURACAO.md",
        "PROJECT_INFO.md",
        "PROJETO_ORGANIZADO.md",
        "README_AUTH.md",
        "README_ESTRUTURA_V2.md",
        "ATUALIZACAO_DASHBOARDS.md",
        "CARDS_DADOS_REAIS_IMPLEMENTADO.md",
        "RESUMO_FINAL_ATUALIZACAO.md"
    ]
}

# Cria um backup antes de organizar
def criar_backup():
    backup_dir = PROJECT_ROOT / f"backup_organizacao_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(exist_ok=True)
    
    print(f"Criando backup em: {backup_dir}")
    
    # Copia apenas os arquivos essenciais para o backup
    arquivos_essenciais = []
    for categoria, arquivos in ESTRUTURA.items():
        arquivos_essenciais.extend(arquivos)
    
    for arquivo in arquivos_essenciais:
        if (PROJECT_ROOT / arquivo).exists():
            shutil.copy2(PROJECT_ROOT / arquivo, backup_dir)
    
    # Copia diretório de templates
    if (PROJECT_ROOT / "templates").exists():
        shutil.copytree(PROJECT_ROOT / "templates", backup_dir / "templates")
    
    return backup_dir

# Cria a estrutura de diretórios
def criar_estrutura():
    print("\nCriando estrutura de diretórios...")
    
    # Cria os diretórios se não existirem
    for diretorio in ESTRUTURA.keys():
        dir_path = PROJECT_ROOT / diretorio
        if not dir_path.exists():
            dir_path.mkdir(exist_ok=True)
            print(f"  Criado diretório: {diretorio}")
    
    # Cria links simbólicos para os arquivos principais
    for categoria, arquivos in ESTRUTURA.items():
        for arquivo in arquivos:
            origem = PROJECT_ROOT / arquivo
            destino = PROJECT_ROOT / categoria / arquivo
            
            if origem.exists() and not destino.exists():
                # Cria um link simbólico
                try:
                    # Em sistemas Windows, pode ser necessário copiar em vez de criar links
                    # devido a restrições de permissão
                    shutil.copy2(origem, destino)
                    print(f"  Copiado: {arquivo} -> {categoria}/{arquivo}")
                except Exception as e:
                    print(f"  Erro ao copiar {arquivo}: {e}")

# Cria um arquivo de índice para cada diretório
def criar_indices():
    print("\nCriando arquivos de índice...")
    
    for categoria, arquivos in ESTRUTURA.items():
        index_path = PROJECT_ROOT / categoria / "README.md"
        
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(f"# {categoria.capitalize()}\n\n")
            f.write("Este diretório contém os seguintes arquivos:\n\n")
            
            for arquivo in arquivos:
                if (PROJECT_ROOT / categoria / arquivo).exists():
                    f.write(f"- [{arquivo}]({arquivo})\n")
            
            f.write("\n---\n")
            f.write(f"Gerado automaticamente em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        print(f"  Criado índice: {categoria}/README.md")

# Função principal
def main():
    print("=== Organização da Estrutura do Projeto ===")
    
    # Cria backup antes de organizar
    backup_dir = criar_backup()
    
    # Executa as funções de organização
    criar_estrutura()
    criar_indices()
    
    # Cria relatório de organização
    relatorio = {
        "data": datetime.now().isoformat(),
        "backup_criado": str(backup_dir),
        "estrutura": {k: len(v) for k, v in ESTRUTURA.items()},
        "mensagem": "Organização da estrutura concluída com sucesso."
    }
    
    with open(PROJECT_ROOT / "relatorio_organizacao.json", "w", encoding="utf-8") as f:
        json.dump(relatorio, f, indent=2)
    
    print("\n=== Organização concluída com sucesso! ===")
    print(f"Backup criado em: {backup_dir}")
    print(f"Relatório de organização salvo em: {PROJECT_ROOT / 'relatorio_organizacao.json'}")
    print("\nObservação: Os arquivos originais foram mantidos na raiz do projeto.")
    print("Você pode acessar os arquivos organizados nos diretórios específicos.")

if __name__ == "__main__":
    main()