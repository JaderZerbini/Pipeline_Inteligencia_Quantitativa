# setup_autostart.ps1
# Registra Terminal Quant para iniciar automaticamente com o Windows.
# Execute UMA VEZ como Administrador:
#   Clique direito no PowerShell -> Executar como Administrador
#   cd C:\Projetos\Pipeline_Inteligência_Quantitativa
#   .\setup_autostart.ps1

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir "venv\Scripts\python.exe"
$Scheduler = Join-Path $ProjectDir "crypto_scheduler.py"
$Dashboard = Join-Path $ProjectDir "app.py"
$StreamlitModule = "streamlit"

# Task 1 — Crypto Scheduler (roda no login, fica em execução)
$ActionScheduler = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $Scheduler `
    -WorkingDirectory $ProjectDir

$TriggerScheduler = New-ScheduledTaskTrigger -AtLogOn

$SettingsScheduler = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "TerminalQuant_Scheduler" `
    -Action $ActionScheduler `
    -Trigger $TriggerScheduler `
    -Settings $SettingsScheduler `
    -Description "Terminal Quant — Crypto Scheduler (roda a cada 6h)" `
    -Force

Write-Host "OK Scheduler registrado — iniciara automaticamente no proximo login"

# Task 2 — Streamlit Dashboard (roda no login, fica em execução)
$DashboardArg = "-m $StreamlitModule run `"$Dashboard`" --server.headless true"

$ActionDashboard = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $DashboardArg `
    -WorkingDirectory $ProjectDir

$TriggerDashboard = New-ScheduledTaskTrigger -AtLogOn

$SettingsDashboard = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "TerminalQuant_Dashboard" `
    -Action $ActionDashboard `
    -Trigger $TriggerDashboard `
    -Settings $SettingsDashboard `
    -Description "Terminal Quant — Streamlit Dashboard (http://localhost:8501)" `
    -Force

Write-Host "OK Dashboard registrado — acessivel em http://localhost:8501 apos login"
Write-Host ""
Write-Host "Para remover o autostart: .\remove_autostart.ps1"
