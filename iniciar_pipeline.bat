@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\activate.bat" (
    echo ERRO: ambiente virtual nao encontrado em venv\
    echo Verifique se o venv esta na pasta do projeto.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
echo Pipeline iniciado. Logs em data\pipeline.log
python main.py >> data\pipeline.log 2>&1
