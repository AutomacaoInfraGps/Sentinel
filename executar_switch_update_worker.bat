@echo off
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG_FILE=%~dp0logs\switch_update_worker.log"

echo.>> "%LOG_FILE%"
echo ==================================================>> "%LOG_FILE%"
echo [%date% %time%] Iniciando worker de atualizacao de switches...>> "%LOG_FILE%"

if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" -m services.switch_update_v01.worker --runtime-dir "%~dp0data\switch_updates" >> "%LOG_FILE%" 2>&1
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -m services.switch_update_v01.worker --runtime-dir "%~dp0data\switch_updates" >> "%LOG_FILE%" 2>&1
    ) else (
        python -m services.switch_update_v01.worker --runtime-dir "%~dp0data\switch_updates" >> "%LOG_FILE%" 2>&1
    )
)

set "WORKER_EXIT=%ERRORLEVEL%"
if not "%WORKER_EXIT%"=="0" (
    echo [%date% %time%] Worker finalizado com erro %WORKER_EXIT%.>> "%LOG_FILE%"
    endlocal & exit /b %WORKER_EXIT%
)

echo [%date% %time%] Worker finalizado com sucesso.>> "%LOG_FILE%"
endlocal
exit /b 0
