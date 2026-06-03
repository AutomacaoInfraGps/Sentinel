@echo off
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG_FILE=%~dp0logs\envio_dashboard_consolidado_task.log"

echo.>> "%LOG_FILE%"
echo ==================================================>> "%LOG_FILE%"
echo [%date% %time%] Iniciando envio diario do dashboard consolidado...>> "%LOG_FILE%"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0enviar_dashboard_consolidado_email.py" >> "%LOG_FILE%" 2>&1
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        py "%~dp0enviar_dashboard_consolidado_email.py" >> "%LOG_FILE%" 2>&1
    ) else (
        python "%~dp0enviar_dashboard_consolidado_email.py" >> "%LOG_FILE%" 2>&1
    )
)

if errorlevel 1 (
    echo [%date% %time%] Falha no envio diario do dashboard consolidado.>> "%LOG_FILE%"
    endlocal
    exit /b 1
)

echo [%date% %time%] Envio diario do dashboard consolidado finalizado com sucesso.>> "%LOG_FILE%"
endlocal
exit /b 0
