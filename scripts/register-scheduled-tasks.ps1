# register-scheduled-tasks.ps1 - One-time Task Scheduler registration (U3).
#
# Registers three scheduled tasks for the Hermes personal workbench:
#   1. HermesWorkbench   - start the gateway at logon
#   2. HermesBackup      - daily backup (03:00)
#   3. HermesWatchdog    - health probe every 5 min, auto-restart on failure
#
# Run once as the current user (normal privileges). For "run whether user is
# logged on or not" (/rl highest) you must run as admin and the task will
# prompt for credentials.
#
#   powershell -ExecutionPolicy Bypass -File D:\Hermes\hermes\scripts\register-scheduled-tasks.ps1

param(
    [string]$BackupDestination = "",
    [switch]$Unregister
)

$HermesRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$StartBat = Join-Path $PSScriptRoot "start-workbench.bat"
$BackupPs = Join-Path $PSScriptRoot "backup.ps1"
$WatchdogPs = Join-Path $PSScriptRoot "watchdog.ps1"

if ($Unregister) {
    foreach ($tn in @("HermesWorkbench", "HermesBackup", "HermesWatchdog")) {
        Unregister-ScheduledTask -TaskName $tn -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "[unreg] $tn"
    }
    exit 0
}

# --- 1. Workbench startup (at logon) -------------------------------------
if (Get-ScheduledTask -TaskName "HermesWorkbench" -ErrorAction SilentlyContinue) {
    Write-Host "[skip] HermesWorkbench already registered"
} else {
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$StartBat`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    Register-ScheduledTask -TaskName "HermesWorkbench" -Action $action -Trigger $trigger -Description "Hermes personal workbench gateway" -Force | Out-Null
    Write-Host "[ok] HermesWorkbench registered (at logon)"
}

# --- 2. Daily backup (03:00) ---------------------------------------------
if (Get-ScheduledTask -TaskName "HermesBackup" -ErrorAction SilentlyContinue) {
    Write-Host "[skip] HermesBackup already registered"
} else {
    $dest = if ($BackupDestination) { $BackupDestination } else { "D:\Backup\hermes" }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BackupPs`" -Destination `"$dest`""
    $trigger = New-ScheduledTaskTrigger -Daily -At 3:00am
    Register-ScheduledTask -TaskName "HermesBackup" -Action $action -Trigger $trigger -Description "Hermes daily backup to $dest" -Force | Out-Null
    Write-Host "[ok] HermesBackup registered (daily 03:00 -> $dest)"
}

# --- 3. Watchdog (every 5 min) -------------------------------------------
if (Get-ScheduledTask -TaskName "HermesWatchdog" -ErrorAction SilentlyContinue) {
    Write-Host "[skip] HermesWatchdog already registered"
} else {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$WatchdogPs`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName "HermesWatchdog" -Action $action -Trigger $trigger -Description "Hermes health watchdog (auto-restart + notify)" -Force | Out-Null
    Write-Host "[ok] HermesWatchdog registered (every 5 min)"
}

Write-Host "Done. Unregister all with: -Unregister"
