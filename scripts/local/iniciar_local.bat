@echo off
cd /d "%~dp0..\.."
call venv\Scripts\activate.bat
if exist ".credentials\sentinel-secrets.transfer.json" (
    echo [Sentinel] Preparando o cofre para o usuario Windows atual...
    python scripts\security\transfer_secret_vault.py import
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel preparar o cofre local.
        pause
        exit /b 1
    )
)
echo [Sentinel] Ambiente virtual ativado. Iniciando servidor...
python run_web_service.py
pause
