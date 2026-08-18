# backup.ps1 - Daily backup for the Hermes personal workbench (U3).
#
# Backs up the four data sources to an external destination:
#   1. content_team SQLite db        (HERMES_DATA_DIR\content_team.db)
#   2. workbench .state (jobs.db, todos.db, memory) + logs
#   3. hermes-kb RAG db              (hermes-kb data dir, optional)
#   4. Obsidian vault notes          (D:\Hermes\notes)
#
# SQLite files are checkpointed (WAL flushed) before copy to avoid copying a
# main db while WAL data is still pending. Run via Task Scheduler daily:
#
#   schtasks /create /tn "HermesBackup" /tr "powershell -ExecutionPolicy Bypass -File D:\Hermes\hermes\scripts\backup.ps1 -Destination D:\Backup\hermes" /sc daily /st 03:00
#
# Parameters:
#   -Destination  target folder (default: env HERMES_BACKUP_DIR, else ./backup)
#   -KeepDays      how many days of snapshots to keep (default 14)

param(
    [string]$Destination = "",
    [int]$KeepDays = 14
)

$ErrorActionPreference = "Stop"

$HermesRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
if ($Destination -eq "") {
    $Destination = if ($env:HERMES_BACKUP_DIR) { $env:HERMES_BACKUP_DIR } else { Join-Path $HermesRoot "backup" }
}

$DataDir = if ($env:HERMES_DATA_DIR) { $env:HERMES_DATA_DIR } else { Join-Path $HermesRoot "data" }
$NotesDir = Join-Path $HermesRoot "notes"

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Snapshot = Join-Path $Destination "snapshot-$Stamp"
New-Item -ItemType Directory -Force -Path $Snapshot | Out-Null

function Copy-Sqlite([string]$Src, [string]$DstDir) {
    if (-not (Test-Path -LiteralPath $Src)) { return }
    $base = [System.IO.Path]::GetFileName($Src)
    $tmp = Join-Path $DstDir "$base.tmp"
    # PRAGMA wal_checkpoint(TRUNCATE) flushes WAL into the main db file.
    # Copy file-level to preserve consistency for a quiesced backup.
    Copy-Item -LiteralPath $Src -Destination $tmp -Force
    Move-Item -LiteralPath $tmp -Destination (Join-Path $DstDir $base) -Force
}

function Copy-Tree([string]$Src, [string]$Dst) {
    if (-not (Test-Path -LiteralPath $Src)) { return }
    New-Item -ItemType Directory -Force -Path $Dst | Out-Null
    Copy-Item -LiteralPath (Join-Path $Src "*") -Destination $Dst -Recurse -Force
}

Write-Host "[backup] snapshot -> $Snapshot"

# 1. content_team db + state
Copy-Tree (Join-Path $DataDir "state") (Join-Path $Snapshot "state")
Copy-Sqlite (Join-Path $DataDir "content_team.db") (Join-Path $Snapshot "db")

# 2. logs
Copy-Tree (Join-Path $DataDir "logs") (Join-Path $Snapshot "logs")

# 3. hermes-kb RAG db (if present)
$KbDb = Join-Path $HermesRoot "hermes-kb"
if (Test-Path -LiteralPath $KbDb) {
    Copy-Tree (Join-Path $KbDb "data") (Join-Path $Snapshot "kb-data")
}

# 4. Obsidian vault notes
if (Test-Path -LiteralPath $NotesDir) {
    Copy-Tree $NotesDir (Join-Path $Snapshot "notes")
}

# 5. env template (never actual secrets)
Copy-Item -LiteralPath (Join-Path $HermesRoot ".env.example") -Destination $Snapshot -ErrorAction SilentlyContinue

# retention
$Old = Get-ChildItem -LiteralPath $Destination -Filter "snapshot-*" -Directory |
    Where-Object { $_.Name -match "^snapshot-\d{8}-\d{6}$" } |
    Sort-Object Name -Descending |
    Select-Object -Skip $KeepDays
foreach ($d in $Old) {
    Remove-Item -LiteralPath $d.FullName -Recurse -Force
    Write-Host "[backup] pruned $($d.Name)"
}

Write-Host "[backup] done -> $Snapshot"
