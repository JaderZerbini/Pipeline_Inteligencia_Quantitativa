@echo off
echo ================================
echo  Terminal Quant — Iniciar
echo ================================
echo.
echo [1] Pipeline B3 (main.py)
echo [2] Pipeline Cripto — execucao unica
echo [3] Scheduler Cripto — execucao automatica a cada 6h
echo [4] Dashboard (app.py)
echo.
set /p choice="Escolha uma opcao (1-4): "

if "%choice%"=="1" (
    echo Iniciando pipeline B3...
    .\venv\Scripts\python.exe main.py
)
if "%choice%"=="2" (
    echo Iniciando pipeline cripto...
    .\venv\Scripts\python.exe crypto_main.py
)
if "%choice%"=="3" (
    echo Iniciando scheduler cripto (Ctrl+C para parar)...
    .\venv\Scripts\python.exe crypto_scheduler.py
)
if "%choice%"=="4" (
    echo Iniciando dashboard...
    .\venv\Scripts\python.exe -m streamlit run app.py
)
pause
