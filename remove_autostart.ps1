# remove_autostart.ps1
# Remove Terminal Quant do autostart do Windows.
# Execute como Administrador.

Unregister-ScheduledTask -TaskName "TerminalQuant_Scheduler" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "TerminalQuant_Dashboard" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "OK Autostart removido."
