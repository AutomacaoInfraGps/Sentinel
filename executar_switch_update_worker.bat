@echo off
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG_FILE=%~dp0logs\switch_update_worker.log"

echo.>> "%LOG_FILE%"
echo ==================================================>> "%LOG_FILE%"
echo [%date% %time%] Iniciando worker de atualizacao de switches...>> "%LOG_FILE%"

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
) else (
    echo [%date% %time%] ERRO: ambiente virtual .venv ou venv nao encontrado.>> "%LOG_FILE%"
    endlocal & exit /b 1
)

"%PYTHON_EXE%" -m services.switch_update_v01.worker --runtime-dir "%~dp0data\switch_updates" >> "%LOG_FILE%" 2>&1

set "WORKER_EXIT=%ERRORLEVEL%"
if not "%WORKER_EXIT%"=="0" (
    echo [%date% %time%] Worker finalizado com erro %WORKER_EXIT%.>> "%LOG_FILE%"
    endlocal & exit /b %WORKER_EXIT%
)

echo [%date% %time%] Worker finalizado com sucesso.>> "%LOG_FILE%"
endlocal
exit /b 0
