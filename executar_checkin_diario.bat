@echo off
setlocal
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG_FILE=%~dp0logs\checkin_diario.log"

echo.>> "%LOG_FILE%"
echo ==================================================>> "%LOG_FILE%"
echo [%date% %time%] Iniciando check-in diario automatico...>> "%LOG_FILE%"

set "AUTOMACAO_NO_BROWSER=1"

set "PYTHON_EXE=%~dp0.venv31410\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if exist "%PYTHON_EXE%" (
    echo [%date% %time%] Python selecionado: "%PYTHON_EXE%">> "%LOG_FILE%"
    "%PYTHON_EXE%" "%~dp0executar_tudo.py" --no-browser >> "%LOG_FILE%" 2>&1
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
