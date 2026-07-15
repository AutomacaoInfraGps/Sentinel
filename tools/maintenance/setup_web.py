from cx_Freeze import setup, Executable
import sys

print("🔧 Compilando Sistema Web...")

# Dependências essenciais
packages = [
    "flask", "werkzeug", "jinja2", "markupsafe", "itsdangerous",
    "click", "blinker", "flask_login", "requests", "urllib3", 
    "pathlib", "json", "subprocess", "webbrowser", "datetime", 
    "threading", "time", "os", "sys", "re"
]

# Arquivos para incluir
include_files = [
    ("templates", "templates"),
    ("web", "web"),
    ("data", "data"),
    ("output", "output"),
    ("logs", "logs"),
    ("core", "core"),
    ("scripts", "scripts"),
    ("environment.json", "environment.json"),
    ("servidores.json", "servidores.json"),
    ("estrutura_regionais.json", "estrutura_regionais.json"),
    ("zabbix_config.json", "zabbix_config.json"),
    ("Conexoes.txt", "Conexoes.txt"),
    ("config.py", "config.py"),
    ("web_config.py", "web_config.py"),
    ("auth_ad.py", "auth_ad.py"),
    ("dashboard_hierarquico.py", "dashboard_hierarquico.py"),
    ("templates_configuracao.py", "templates_configuracao.py"),
    ("gerenciar_regionais.py", "gerenciar_regionais.py"),
    ("gerenciar_fortigate.py", "gerenciar_fortigate.py"),
    ("executar_tudo.py", "executar_tudo.py")
]

# Adiciona scripts PowerShell
import glob
for ps1_file in glob.glob("*.ps1"):
    include_files.append((ps1_file, ps1_file))

# Configurações de build
build_exe_options = {
    "packages": packages,
    "include_files": include_files,
    "excludes": ["tkinter", "matplotlib", "numpy", "pandas"],
    "optimize": 2,
}

# Executável
executables = [
    Executable(
        "iniciar_web.py",
        base="Console",
        target_name="SistemaAutomacao.exe",
    )
]

setup(
    name="Sistema de Automação Web",
    version="1.0.0",
    description="Sistema de Automação com Interface Web",
    options={"build_exe": build_exe_options},
    executables=executables,
)