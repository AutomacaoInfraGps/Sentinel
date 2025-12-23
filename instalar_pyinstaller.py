"""
Script para tentar diferentes métodos de instalação do PyInstaller
"""
import subprocess
import sys
import os
from pathlib import Path

def tentar_instalacao_normal():
    """Tenta instalação normal do PyInstaller"""
    print("🔄 Tentando instalação normal...")
    try:
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "pyinstaller"
        ], check=True, capture_output=True, text=True)
        print("✅ PyInstaller instalado com sucesso!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Falha na instalação normal: {e}")
        return False

def tentar_instalacao_trusted():
    """Tenta instalação com hosts confiáveis"""
    print("🔄 Tentando instalação com hosts confiáveis...")
    try:
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", 
            "--trusted-host", "pypi.org",
            "--trusted-host", "pypi.python.org", 
            "--trusted-host", "files.pythonhosted.org",
            "pyinstaller"
        ], check=True, capture_output=True, text=True)
        print("✅ PyInstaller instalado com sucesso!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Falha na instalação com hosts confiáveis: {e}")
        return False

def tentar_instalacao_user():
    """Tenta instalação no diretório do usuário"""
    print("🔄 Tentando instalação no diretório do usuário...")
    try:
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "--user", "pyinstaller"
        ], check=True, capture_output=True, text=True)
        print("✅ PyInstaller instalado com sucesso!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Falha na instalação do usuário: {e}")
        return False

def tentar_instalacao_upgrade():
    """Tenta atualizar pip primeiro"""
    print("🔄 Tentando atualizar pip primeiro...")
    try:
        # Atualiza pip
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--upgrade", "pip"
        ], check=True, capture_output=True, text=True)
        
        # Tenta instalar PyInstaller
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "pyinstaller"
        ], check=True, capture_output=True, text=True)
        print("✅ PyInstaller instalado com sucesso!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Falha após atualizar pip: {e}")
        return False

def verificar_pyinstaller():
    """Verifica se PyInstaller está instalado"""
    try:
        result = subprocess.run([
            "pyinstaller", "--version"
        ], check=True, capture_output=True, text=True)
        print(f"✅ PyInstaller já instalado: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def baixar_manual():
    """Instruções para download manual"""
    print("📥 DOWNLOAD MANUAL NECESSÁRIO")
    print("=" * 50)
    print("Como o PyInstaller não pode ser instalado automaticamente,")
    print("você precisará baixá-lo manualmente:")
    print()
    print("1. Acesse: https://pypi.org/project/pyinstaller/#files")
    print("2. Baixe: pyinstaller-6.14.2-py3-none-win_amd64.whl")
    print("3. Salve na pasta do projeto")
    print("4. Execute: pip install pyinstaller-6.14.2-py3-none-win_amd64.whl")
    print()
    print("OU use uma das alternativas:")
    print("- Conda: conda install pyinstaller")
    print("- Auto-py-to-exe: pip install auto-py-to-exe")

def compilar_sem_pyinstaller():
    """Cria um script batch como alternativa"""
    print("🔧 Criando alternativa sem PyInstaller...")
    
    batch_content = f'''@echo off
echo ========================================
echo   Sistema de Automacao de Infraestrutura
echo ========================================
echo.

cd /d "{Path.cwd()}"

echo Executando sistema...
python executar_tudo.py

echo.
echo Pressione qualquer tecla para fechar...
pause > nul
'''
    
    batch_file = Path("SistemaAutomacao.bat")
    with open(batch_file, "w", encoding="utf-8") as f:
        f.write(batch_content)
    
    print(f"✅ Arquivo batch criado: {batch_file}")
    print("   Este arquivo pode ser usado como alternativa ao .exe")
    print("   Distribua junto com todo o projeto Python")

def main():
    """Função principal"""
    print("🚀 INSTALAÇÃO DO PYINSTALLER")
    print("=" * 50)
    
    # Verifica se já está instalado
    if verificar_pyinstaller():
        print("🎉 PyInstaller já está disponível!")
        print("Execute: python compile_to_exe.py")
        return True
    
    print("PyInstaller não encontrado. Tentando instalar...")
    
    # Tenta diferentes métodos de instalação
    metodos = [
        tentar_instalacao_normal,
        tentar_instalacao_trusted,
        tentar_instalacao_user,
        tentar_instalacao_upgrade,
    ]
    
    for i, metodo in enumerate(metodos, 1):
        print(f"\n📋 Método {i}/{len(metodos)}:")
        if metodo():
            print("🎉 Instalação bem-sucedida!")
            print("Execute: python compile_to_exe.py")
            return True
    
    print("\n❌ Todos os métodos automáticos falharam")
    baixar_manual()
    compilar_sem_pyinstaller()
    
    return False

if __name__ == "__main__":
    main()