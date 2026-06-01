$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectDir "venv\Scripts\python.exe"
$Scheduler = Join-Path $ProjectDir "crypto\scheduler.py"
$Dashboard = Join-Path $ProjectDir "dashboard\app.py"

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
    -Description "Terminal Quant Crypto Scheduler" `
    -Force

$ActionDashboard = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m streamlit run `"$Dashboard`" --server.headless true" `
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
    -Description "Terminal Quant Streamlit Dashboard" `
    -Force

Write-Host "Autostart configurado com sucesso."
Write-Host "Scheduler e dashboard iniciarao automaticamente no proximo login."
