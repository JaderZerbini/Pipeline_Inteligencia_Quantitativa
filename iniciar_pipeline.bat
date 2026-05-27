@echo off
echo ================================
echo  Terminal Quant - Iniciar
echo ================================
echo.
echo [1] Pipeline B3
echo [2] Pipeline Cripto - execucao unica
echo [3] Scheduler Cripto - a cada 6h
echo [4] Dashboard
echo [5] Configurar autostart com Windows
echo [6] Remover autostart
echo.
set /p choice=Escolha (1-6):
if "%choice%"=="1" .\venv\Scripts\python.exe main.py
if "%choice%"=="2" .\venv\Scripts\python.exe crypto_main.py
if "%choice%"=="3" .\venv\Scripts\python.exe crypto_scheduler.py
if "%choice%"=="4" .\venv\Scripts\python.exe -m streamlit run app.py
if "%choice%"=="5" powershell -ExecutionPolicy Bypass -File setup_autostart.ps1
if "%choice%"=="6" powershell -ExecutionPolicy Bypass -File remove_autostart.ps1
pause
