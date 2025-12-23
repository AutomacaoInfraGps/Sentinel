"""
Script para organizar e limpar o projeto, mantendo apenas arquivos essenciais.
Remove arquivos antigos, temporários e desnecessários.
"""

import os
import shutil
from pathlib import Path
from config import PROJECT_ROOT, OUTPUT_DIR

def cleanup_project():
    """Remove arquivos desnecessários e organiza o projeto"""
    
    print("🧹 Organizando projeto...")
    print(f"📁 Diretório: {PROJECT_ROOT}")
    print()
    
    # Arquivos essenciais do projeto (não devem ser removidos)
    essential_files = {
        # Scripts principais
        "executar_tudo.py",
        "config.py",
        "setup.py",
        "validate_system.py",
        "cleanup_project.py",  # Incluindo este script
        
        # Scripts de coleta de dados
        "Chelist.py",
        "iLOcheck.py", 
        "Unifi.Py",
        "utilizarSession.py",
        "gerar_status_html.py",
        "Replicacao_Servers.ps1",
        "get_replicacao_path.py",
        
        # Arquivos de configuração
        "environment.json",
        "Conexoes.txt",
        
        # Documentação
        "README.md",
        "CHANGELOG.md",
        "PROJECT_INFO.md",
        ".gitignore",
        
        # Arquivos de sessão necessários
        "auth_state.json"
    }
    
    # Diretórios essenciais (não devem ser removidos)
    essential_dirs = {
        "output",
        "__pycache__",  # Será limpo, mas não removido
        ".vscode"       # Configurações do IDE
    }
    
    # Arquivos a serem removidos
    files_to_remove = []
    dirs_to_remove = []
    
    # Verifica todos os arquivos no diretório raiz
    for item in PROJECT_ROOT.iterdir():
        if item.is_file():
            if item.name not in essential_files:
                files_to_remove.append(item)
        elif item.is_dir():
            if item.name not in essential_dirs:
                dirs_to_remove.append(item)
    
    # Remove arquivos desnecessários
    if files_to_remove:
        print("🗑️ Removendo arquivos desnecessários:")
        for file_path in files_to_remove:
            try:
                file_path.unlink()
                print(f"   ✅ Removido: {file_path.name}")
            except Exception as e:
                print(f"   ❌ Erro ao remover {file_path.name}: {e}")
    else:
        print("✅ Nenhum arquivo desnecessário encontrado")
    
    # Remove diretórios desnecessários
    if dirs_to_remove:
        print("\n🗑️ Removendo diretórios desnecessários:")
        for dir_path in dirs_to_remove:
            try:
                shutil.rmtree(dir_path)
                print(f"   ✅ Removido: {dir_path.name}/")
            except Exception as e:
                print(f"   ❌ Erro ao remover {dir_path.name}/: {e}")
    else:
        print("\n✅ Nenhum diretório desnecessário encontrado")
    
    # Limpa cache do Python
    pycache_dir = PROJECT_ROOT / "__pycache__"
    if pycache_dir.exists():
        print(f"\n🧹 Limpando cache Python:")
        try:
            shutil.rmtree(pycache_dir)
            print(f"   ✅ Cache limpo")
        except Exception as e:
            print(f"   ❌ Erro ao limpar cache: {e}")
    
    # Remove HTMLs antigos da raiz (mantém apenas os do output/)
    html_files = list(PROJECT_ROOT.glob("*.html"))
    if html_files:
        print(f"\n🧹 Removendo HTMLs antigos da raiz:")
        for html_file in html_files:
            try:
                html_file.unlink()
                print(f"   ✅ Removido: {html_file.name}")
            except Exception as e:
                print(f"   ❌ Erro ao remover {html_file.name}: {e}")
    
    # Remove screenshots antigos da raiz
    image_files = list(PROJECT_ROOT.glob("*.png")) + list(PROJECT_ROOT.glob("*.jpg"))
    if image_files:
        print(f"\n🧹 Removendo screenshots antigos da raiz:")
        for img_file in image_files:
            try:
                img_file.unlink()
                print(f"   ✅ Removido: {img_file.name}")
            except Exception as e:
                print(f"   ❌ Erro ao remover {img_file.name}: {e}")
    
    print(f"\n📊 Estrutura final do projeto:")
    show_project_structure()

def show_project_structure():
    """Mostra a estrutura final do projeto"""
    
    def print_tree(directory, prefix="", max_depth=3, current_depth=0):
        if current_depth >= max_depth:
            return
            
        items = sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            current_prefix = "└── " if is_last else "├── "
            print(f"{prefix}{current_prefix}{item.name}")
            
            if item.is_dir() and not item.name.startswith('.') and current_depth < max_depth - 1:
                extension = "    " if is_last else "│   "
                print_tree(item, prefix + extension, max_depth, current_depth + 1)
    
    print(f"📁 {PROJECT_ROOT.name}/")
    print_tree(PROJECT_ROOT)

def main():
    """Função principal"""
    print("🧹 Organizador de Projeto - Sistema de Automação")
    print("=" * 60)
    
    # Executa limpeza
    cleanup_project()
    
    print("\n" + "=" * 60)
    print("✅ Projeto organizado com sucesso!")
    print("\n📋 Arquivos mantidos:")
    print("• Scripts essenciais do sistema")
    print("• Arquivos de configuração")
    print("• Documentação")
    print("• Diretório output/ com HTMLs gerados")

if __name__ == "__main__":
    main()