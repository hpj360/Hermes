# Sync Hermes project config to CN Desktop client
# Run this script in PowerShell (not as admin needed)

$DesktopData = "$env:LOCALAPPDATA\hermes"
$ProjectRoot = "d:\Hermes\hermes"

Write-Host "=== Syncing Hermes Project -> CN Desktop ===" -ForegroundColor Cyan
Write-Host ""

# 1. Sync Skills
Write-Host "[1/3] Syncing skills..." -ForegroundColor Yellow
$SkillDest = "$DesktopData\skills\hermes-custom"
New-Item -ItemType Directory -Path $SkillDest -Force -ErrorAction SilentlyContinue | Out-Null
Copy-Item -Path "$ProjectRoot\skills\*" -Destination "$SkillDest\" -Recurse -Force
$skillCount = (Get-ChildItem $SkillDest -Directory).Count
Write-Host "  Copied $skillCount skills to skills\hermes-custom\" -ForegroundColor Green

# 2. Sync Knowledge
Write-Host "[2/3] Syncing knowledge documents..." -ForegroundColor Yellow
$KnowledgeDest = "$DesktopData\knowledge"
New-Item -ItemType Directory -Path $KnowledgeDest -Force -ErrorAction SilentlyContinue | Out-Null
Copy-Item -Path "$ProjectRoot\knowledge\*" -Destination "$KnowledgeDest\" -Recurse -Force
$knowledgeCount = (Get-ChildItem $KnowledgeDest -File).Count
Write-Host "  Copied $knowledgeCount knowledge documents to knowledge\" -ForegroundColor Green

# 3. Merge .env
Write-Host "[3/3] Merging .env configuration..." -ForegroundColor Yellow
$DesktopEnv = "$DesktopData\.env"
$ProjectEnv = "$ProjectRoot\.env"
$BackupEnv = "$DesktopData\.env.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Backup existing .env
Copy-Item $DesktopEnv $BackupEnv -Force
Write-Host "  Backed up existing .env to .env.backup-*" -ForegroundColor Gray

# Read project .env keys we want to merge
$projectKeys = @(
    "IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY", "IMA_OPENAPI_BASE_URL",
    "SKILLHUB_API_BASE", "SKILLHUB_COS_BUCKET", "SKILLHUB_COS_REGION",
    "OPENCLAW_GATEWAY_PORT", "OPENCLAW_GATEWAY_TOKEN",
    "OPENCLAW_MODEL_PRIMARY", "OPENCLAW_MODEL_FALLBACK",
    "HERMES_LOG_LEVEL", "HERMES_MAIN_REPO_PATH"
)

# Parse project .env
$projectEnvVars = @{}
Get-Content $ProjectEnv | ForEach-Object {
    $line = $_.Trim()
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)') {
        $key = $matches[1]
        $value = $matches[2]
        if ($key -in $projectKeys -and $value -ne "") {
            $projectEnvVars[$key] = $value
        }
    }
}

# Read desktop .env and update/add keys
$desktopLines = Get-Content $DesktopEnv
$updatedKeys = @{}
$newLines = @()
$appended = $false

foreach ($line in $desktopLines) {
    if ($line -match '^#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') {
        $key = $matches[1]
        if ($projectEnvVars.ContainsKey($key)) {
            $newLines += "$key=$($projectEnvVars[$key])"
            $updatedKeys[$key] = $true
            continue
        }
    }
    $newLines += $line
}

# Append keys not found in desktop .env
$missingKeys = $projectEnvVars.Keys | Where-Object { -not $updatedKeys.ContainsKey($_) }
if ($missingKeys.Count -gt 0) {
    $newLines += ""
    $newLines += "# === Merged from Hermes project ==="
    foreach ($key in $missingKeys) {
        $newLines += "$key=$($projectEnvVars[$key])"
    }
}

$newLines | Set-Content $DesktopEnv -Encoding UTF8
Write-Host "  Merged $($updatedKeys.Count) updated keys, $($missingKeys.Count) new keys" -ForegroundColor Green

Write-Host ""
Write-Host "=== Sync Complete ===" -ForegroundColor Cyan
Write-Host "Skills:    $SkillDest" -ForegroundColor Gray
Write-Host "Knowledge: $KnowledgeDest" -ForegroundColor Gray
Write-Host "Env:       $DesktopEnv" -ForegroundColor Gray
Write-Host "Backup:    $BackupEnv" -ForegroundColor Gray