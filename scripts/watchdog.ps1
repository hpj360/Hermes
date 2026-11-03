# watchdog.ps1 - Lightweight process watchdog for the Hermes workbench (U3).
#
# Probes the health endpoint every 30s AND verifies the product surface at "/"
# is the React SPA (not the legacy stdlib engineering dashboard); if either
# check fails it restarts the service via start-workbench.bat and logs the
# event. Optionally notifies via a webhook (FEISHU_WEBHOOK_URL) best-effort.
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
$RootUrl = "http://127.0.0.1:$Port/"
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

$healthy = $false
$reason = ""

# Probe 1: API health.
try {
    $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -eq 200) {
        $healthy = $true
    } else {
        $reason = "health status $($resp.StatusCode)"
    }
} catch {
    $reason = "health unreachable"
}

# Probe 2: product surface. The gateway serves the React SPA shell
# (<div id="root">) at "/"; the legacy stdlib server serves the engineering
# dashboard there instead. A healthy-but-wrong entrypoint is treated as a
# failure so the watchdog self-heals back to the product UI.
if ($healthy) {
    try {
        $root = Invoke-WebRequest -Uri $RootUrl -UseBasicParsing -TimeoutSec 5
        if ($root.Content -notmatch 'id="root"') {
            $healthy = $false
            $reason = "wrong entrypoint: / is not the SPA (legacy stdlib server?)"
        }
    } catch {
        $healthy = $false
        $reason = "root unreachable"
    }
}

if ($healthy) {
    exit 0
}

Write-Log "health check FAILED ($HealthUrl): $reason"
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
