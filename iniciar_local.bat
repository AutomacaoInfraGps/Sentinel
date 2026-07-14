@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo [Sentinel] Ambiente virtual ativado. Iniciando servidor...
python run_web_service.py
pause
