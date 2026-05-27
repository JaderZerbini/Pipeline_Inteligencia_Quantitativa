# check_autostart.ps1
# Mostra o status das tarefas agendadas do Terminal Quant.

$tasks = @("TerminalQuant_Scheduler", "TerminalQuant_Dashboard")
foreach ($name in $tasks) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $name
        Write-Host "OK $name"
        Write-Host "   Status: $($task.State)"
        Write-Host "   Ultima execucao: $($info.LastRunTime)"
        Write-Host "   Proxima execucao: $($info.NextRunTime)"
    } else {
        Write-Host "NAO REGISTRADO: $name"
    }
}
