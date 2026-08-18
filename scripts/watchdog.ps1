# watchdog.ps1 - Lightweight process watchdog for the Hermes workbench (U3).
#
# Probes the health endpoint every 30s; if the server is unreachable it
# restarts it via start-workbench.bat and logs the event. Optionally notifies
# via a webhook (FEISHU_WEBHOOK_URL) best-effort.
#
# Usage (Task Scheduler, repeat every 5 min):
#   powershell -ExecutionPolicy Bypass -File D:\Hermes\hermes\scripts\watchdog.ps1
#
# The script exits 0 after each probe pass so Task Scheduler "restart on
# failure" semantics are not abused; restart happens inside the script.

param(
    [int]$Port = 8000,
    [string]$HealthPath = "/health"
)

$BatPath = Join-Path $PSScriptRoot "start-workbench.bat"
$HealthUrl = "http://127.0.0.1:$Port$HealthPath"
$LogFile = Join-Path (if ($env:HERMES_DATA_DIR) { $env:HERMES_DATA_DIR } else { (Join-Path $PSScriptRoot "..") }) "logs\watchdog.log"
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

function Write-Log([string]$Msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

function Start-Workbench {
    Write-Log "restarting workbench via $BatPath"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$BatPath`"" -WindowStyle Hidden
}

try {
    $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -eq 200) {
        # healthy - optionally log last status line
        exit 0
    }
} catch {
    # unreachable
}

Write-Log "health check FAILED ($HealthUrl)"
Start-Workbench

if ($env:FEISHU_WEBHOOK_URL) {
    try {
        $body = @{ msg_type = "text"; content = @{ text = "[Hermes] workbench watchdog: health check failed, restarting." } } | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Uri $env:FEISHU_WEBHOOK_URL -Method Post -ContentType "application/json" -Body $body -TimeoutSec 5 | Out-Null
    } catch {
        Write-Log "feishu notify failed (best-effort)"
    }
}
exit 0
