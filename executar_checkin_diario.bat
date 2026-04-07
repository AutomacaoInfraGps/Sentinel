@echo off
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG_FILE=%~dp0logs\checkin_diario.log"

echo.>> "%LOG_FILE%"
echo ==================================================>> "%LOG_FILE%"
echo [%date% %time%] Iniciando check-in diario automatico...>> "%LOG_FILE%"

set "AUTOMACAO_NO_BROWSER=1"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0executar_tudo.py" --no-browser >> "%LOG_FILE%" 2>&1
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        py "%~dp0executar_tudo.py" --no-browser >> "%LOG_FILE%" 2>&1
    ) else (
        python "%~dp0executar_tudo.py" --no-browser >> "%LOG_FILE%" 2>&1
    )
)

if errorlevel 1 (
    echo [%date% %time%] Falha na execucao do check-in diario.>> "%LOG_FILE%"
    endlocal
    exit /b 1
)

echo [%date% %time%] Check-in diario finalizado com sucesso.>> "%LOG_FILE%"
endlocal
exit /b 0
