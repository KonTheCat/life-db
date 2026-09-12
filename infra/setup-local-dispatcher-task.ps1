# Registers a Windows Scheduled Task that runs the notification dispatcher
# every 5 minutes -- the local stand-in for the Container Apps Job's
# Schedule trigger (plan §5), so reminders actually fire while testing
# locally via Claude Desktop instead of only on a manual
# `uv run python dispatcher/run.py`.
#
# Re-run safely; it replaces any existing task of the same name.
$ErrorActionPreference = "Stop"
$taskName = "life-db-notification-dispatcher"
$scriptPath = Join-Path $PSScriptRoot "run-dispatcher-local.ps1"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Scans personal-db's _notifications for due reminders and dispatches them via Telegram (local stand-in for the Container Apps Job)." | Out-Null

Write-Output "Registered '$taskName' -- runs every 5 minutes."
Write-Output "Logs: $(Join-Path (Split-Path $PSScriptRoot -Parent) '.dispatcher.log')"
Write-Output "To remove: Unregister-ScheduledTask -TaskName '$taskName'"
