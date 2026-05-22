@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\activate.bat" (
    echo ERRO: ambiente virtual nao encontrado em venv\
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
echo Dashboard iniciado em http://localhost:8501
streamlit run app.py
