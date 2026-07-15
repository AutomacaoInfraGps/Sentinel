from cx_Freeze import setup, Executable
import sys
import glob
import os

print("🔧 Configurando compilação com cx_Freeze...")

# Lista de dependências Python
packages = [
    "requests", "urllib3", "pathlib", "json", "subprocess", 
    "webbrowser", "datetime", "re", "os", "sys", "codecs", 
    "locale", "tempfile", "shutil", "threading", "time",
    "flask", "werkzeug", "jinja2", "markupsafe", "itsdangerous",
    "click", "blinker", "flask_login"
]

# Módulos do projeto
project_modules = [
    "config", "credentials", "data_store", "vm_manager",
    "gerenciar_servidores", "gerenciar_switches", "gerenciar_vms",
    "gerenciar_regionais", "gerenciar_fortigate", "auth_ad",
    "dashboard_hierarquico", "web_config", "templates_configuracao"
]

# Adiciona módulos do projeto se existirem
for module in project_modules:
    if os.path.exists(f"{module}.py"):
        packages.append(module)
        print(f"   ✅ Incluindo módulo: {module}")

# Arquivos e pastas para incluir
include_files = []

# Adiciona pastas se existirem
folders_to_include = ["templates", "data", "output", "logs", "web", "core", "scripts"]
for folder in folders_to_include:
    if os.path.exists(folder):
        include_files.append((folder, folder))
        print(f"   📁 Incluindo pasta: {folder}")

# Adiciona arquivos individuais
file_patterns = ["*.ps1", "*.json", "*.txt", "*.xlsx", "*.md"]
for pattern in file_patterns:
    files = glob.glob(pattern)
    for file in files:
        include_files.append((file, file))
        print(f"   📄 Incluindo arquivo: {file}")

# Configurações de build
build_exe_options = {
    "packages": packages,
    "include_files": include_files,
    "excludes": [
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "django",
        "flask", "tornado", "twisted", "asyncio"
    ],
    "optimize": 2,
    "zip_include_packages": ["encodings", "importlib"],
}

# Configuração do executável
executables = [
    Executable(
        "iniciar_web.py",
        base="Console",  # Mantém console para debug
        target_name="SistemaAutomacao.exe",
        copyright="Sistema de Automação de Infraestrutura",
        shortcut_name="Sistema de Automação",
        shortcut_dir="DesktopFolder",
    )
]

print("📋 Configuração concluída!")

# Setup
setup(
    name="Sistema de Automação",
    version="1.0.0",
    description="Sistema de Automação de Infraestrutura",
    author="Desenvolvedor",
    options={"build_exe": build_exe_options},
    executables=executables,
)