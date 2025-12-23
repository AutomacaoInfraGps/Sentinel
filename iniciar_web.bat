@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo    SISTEMA DE AUTOMACAO - INSTALACAO AUTOMATICA
echo ========================================
echo.
echo 🚀 Este script ira instalar automaticamente tudo que for necessario
echo.

REM Verificar se Python esta instalado
echo [1/8] Verificando Python...

REM Tentar python primeiro
python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python
    set PIP_CMD=pip
    echo ✅ Python encontrado: python
    goto :python_found
)

REM Tentar py (Python Launcher)
py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=py
    set PIP_CMD=py -m pip
    echo ✅ Python encontrado: py
    goto :python_found
)

REM Tentar python3
python3 --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python3
    set PIP_CMD=pip3
    echo ✅ Python encontrado: python3
    goto :python_found
)

REM Python nao encontrado - instalar automaticamente
echo ⚠️  Python nao encontrado. Instalando automaticamente...
echo.

REM Verificar se winget esta disponivel (Windows 10/11)
winget --version >nul 2>&1
if not errorlevel 1 (
    echo 📦 Instalando Python via winget...
    winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    if not errorlevel 1 (
        echo ✅ Python instalado com sucesso via winget
        echo ⚠️  Reiniciando script para detectar Python...
        timeout /t 3 >nul
        call "%~f0"
        exit /b
    ) else (
        echo ❌ Falha na instalacao via winget
    )
)

REM Se winget falhou, tentar chocolatey
choco --version >nul 2>&1
if not errorlevel 1 (
    echo 📦 Instalando Python via Chocolatey...
    choco install python -y
    if not errorlevel 1 (
        echo ✅ Python instalado com sucesso via Chocolatey
        echo ⚠️  Reiniciando script para detectar Python...
        timeout /t 3 >nul
        call "%~f0"
        exit /b
    ) else (
        echo ❌ Falha na instalacao via Chocolatey
    )
)

REM Ultima tentativa - download manual
echo 📦 Tentando instalacao manual do Python...
echo.
echo ⚠️  INSTALACAO MANUAL NECESSARIA:
echo.
echo 1. O script ira abrir o site do Python
echo 2. Baixe a versao mais recente
echo 3. Durante a instalacao, MARQUE: "Add Python to PATH"
echo 4. Apos instalar, execute este script novamente
echo.
echo Pressione qualquer tecla para abrir o site do Python...
pause >nul
start https://python.org/downloads/
echo.
echo Apos instalar o Python, execute este script novamente.
goto :end

:python_found

REM Verificar se pip esta disponivel
echo [2/8] Verificando pip...
%PIP_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo ⚠️  pip nao encontrado. Instalando...
    %PYTHON_CMD% -m ensurepip --upgrade
    if errorlevel 1 (
        echo ❌ Falha ao instalar pip
        goto :error
    )
    echo ✅ pip instalado com sucesso
) else (
    echo ✅ pip encontrado
)

REM Instalar dependencias automaticamente
echo [3/8] Instalando dependencias Python...

echo 📦 Atualizando pip...
%PIP_CMD% install --upgrade pip >nul 2>&1

echo 📦 Instalando requests...
%PIP_CMD% install requests
if errorlevel 1 (
    echo ❌ Falha ao instalar requests
    goto :error
)
echo ✅ requests instalado

echo 📦 Instalando playwright...
%PIP_CMD% install playwright
if errorlevel 1 (
    echo ❌ Falha ao instalar playwright
    goto :error
)
echo ✅ playwright instalado

echo [4/8] Instalando navegadores do Playwright...
echo 📦 Baixando navegadores (pode demorar alguns minutos)...
%PYTHON_CMD% -m playwright install
if errorlevel 1 (
    echo ❌ Falha ao instalar navegadores do Playwright
    echo ⚠️  Continuando sem navegadores - algumas funcoes podem nao funcionar
) else (
    echo ✅ Navegadores do Playwright instalados
)

echo [5/8] Executando configuracao inicial...
%PYTHON_CMD% setup.py
if errorlevel 1 (
    echo ⚠️  Alguns problemas na configuracao inicial, mas continuando...
) else (
    echo ✅ Configuracao inicial concluida
)

REM Verificar se arquivos essenciais existem
echo [6/8] Verificando arquivos essenciais...
if not exist "iniciar_web.py" (
    echo ❌ ERRO: Arquivo iniciar_web.py nao encontrado
    echo ⚠️  Certifique-se de que este .bat esta na pasta correta do projeto
    goto :error
)
if not exist "config.py" (
    echo ❌ ERRO: Arquivo config.py nao encontrado
    echo ⚠️  Certifique-se de que este .bat esta na pasta correta do projeto
    goto :error
)
echo ✅ Arquivos essenciais encontrados

REM Verificar e criar arquivos de configuracao
echo [7/8] Configurando arquivos de configuracao...
set config_created=0

if not exist "environment.json" (
    echo 📝 Criando environment.json...
    %PYTHON_CMD% -c "from setup import create_environment_template; create_environment_template()"
    set config_created=1
)

if not exist "Conexoes.txt" (
    echo 📝 Criando Conexoes.txt...
    %PYTHON_CMD% -c "from setup import create_connections_template; create_connections_template()"
    set config_created=1
)

if !config_created! == 1 (
    echo.
    echo ⚠️  IMPORTANTE: Arquivos de configuracao foram criados como templates
    echo.
    echo 📋 PROXIMOS PASSOS ANTES DE USAR O SISTEMA:
    echo 1. Edite o arquivo 'environment.json' com suas credenciais
    echo 2. Edite o arquivo 'Conexoes.txt' com suas regionais/servidores
    echo.
    echo ❓ Deseja abrir os arquivos para edicao agora? (S/N)
    set /p open_config=
    if /i "!open_config!"=="S" (
        echo 📝 Abrindo arquivos para edicao...
        if exist "environment.json" start notepad "environment.json"
        if exist "Conexoes.txt" start notepad "Conexoes.txt"
        echo.
        echo ⏳ Edite os arquivos e pressione qualquer tecla para continuar...
        pause >nul
    )
)
echo ✅ Configuracao concluida

REM Iniciar o sistema
echo [8/8] Iniciando interface web...
echo.
echo ========================================
echo    INICIANDO SISTEMA...
echo ========================================
echo.
echo 🌐 A interface web sera aberta em: http://localhost:5000
echo.
echo Para parar o sistema, pressione Ctrl+C
echo.
echo ⏳ Aguarde alguns segundos para o sistema inicializar...
echo.

%PYTHON_CMD% iniciar_web.py

goto :end

:error
echo.
echo ========================================
echo    ERRO NA INICIALIZACAO
echo ========================================
echo.
echo O sistema nao pode ser iniciado devido aos erros acima.
echo Corrija os problemas e tente novamente.
echo.
pause
exit /b 1

:end
echo.
echo ========================================
echo    SISTEMA FINALIZADO
echo ========================================
pause