# Local stand-in for the Container Apps Job's Schedule trigger (plan §5/§13
# phase 8). Registered as a Windows Scheduled Task by infra/setup-local-dispatcher-task.ps1.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$uv = "C:\Users\Konstantin\AppData\Roaming\Python\Python314\Scripts\uv.exe"
$logFile = Join-Path $repoRoot ".dispatcher.log"

Set-Location $repoRoot
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
try {
    $output = & $uv run python dispatcher/run.py 2>&1
    Add-Content -Path $logFile -Value "[$timestamp] $output"
} catch {
    Add-Content -Path $logFile -Value "[$timestamp] ERROR: $_"
}
