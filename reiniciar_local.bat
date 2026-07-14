@echo off
cd /d "%~dp0"
echo [Sentinel Local] Parando servidor atual na porta 5000...

:: Mata qualquer processo Python rodando run_web_service.py
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5000" ^| find "LISTENING"') do (
    echo [Sentinel Local] Encerrando PID %%a na porta 5000
    taskkill /F /PID %%a >nul 2>&1
)

:: Aguarda liberar a porta
timeout /t 2 /nobreak >nul

echo [Sentinel Local] Iniciando servidor...
call venv\Scripts\activate.bat
start "Sentinel Local" cmd /k "python run_web_service.py"

:: Aguarda subir
timeout /t 3 /nobreak >nul
echo [Sentinel Local] Servidor reiniciado. Acesse: http://localhost:5000
start http://localhost:5000
