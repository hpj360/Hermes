# ============================================================
# Hermes 项目配置 -> 桌面客户端融合脚本
# 将项目的所有配置层面与桌面客户端对齐
# ============================================================

$DesktopData = "$env:LOCALAPPDATA\hermes"
$ProjectRoot = "d:\Hermes\hermes"
$ConfigYaml  = "$DesktopData\config.yaml"
$BackupDir   = "$DesktopData\backups\$(Get-Date -Format 'yyyyMMdd-HHmmss')"

Write-Host "=== Hermes 项目配置融合 ===" -ForegroundColor Cyan
Write-Host "项目路径: $ProjectRoot" -ForegroundColor Gray
Write-Host "桌面路径: $DesktopData" -ForegroundColor Gray
Write-Host ""

# 创建备份目录
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

# ------------------------------------------------------------
# 1. 备份并更新 config.yaml
# ------------------------------------------------------------
Write-Host "[1/5] 更新 config.yaml（模型 + 网关配置）..." -ForegroundColor Yellow

Copy-Item $ConfigYaml "$BackupDir\config.yaml" -Force

# 读取当前 config.yaml
$yaml = Get-Content $ConfigYaml -Raw

# 1a. 统一模型配置（项目用 claude-sonnet-4-5，桌面端用 claude-opus-4.6）
$yaml = $yaml -replace 'default:\s*anthropic/claude-opus-4\.6', 'default: anthropic/claude-sonnet-4-5'

# 1b. 添加 OpenClaw 网关配置（如果不存在）
if ($yaml -notmatch 'openclaw:') {
    $yaml += @"

# === 项目融合配置 ===
openclaw:
  gateway_port: 18789
  model_primary: anthropic/claude-sonnet-4-5
  model_fallback: openai/gpt-4o
"@
}

# 1c. 添加项目路径引用
if ($yaml -notmatch 'project_fusion:') {
    $yaml += @"

project_fusion:
  manifest_path: d:/Hermes/hermes/manifest.json
  agents_md: d:/Hermes/hermes/AGENTS.md
  project_root: d:/Hermes/hermes
"@
}

$yaml | Set-Content $ConfigYaml -Encoding UTF8
Write-Host "  模型 -> anthropic/claude-sonnet-4-5" -ForegroundColor Green
Write-Host "  网关端口 -> 18789" -ForegroundColor Green
Write-Host "  项目路径引用已添加" -ForegroundColor Green

# ------------------------------------------------------------
# 2. 复制 AGENTS.md 到 knowledge 目录
# ------------------------------------------------------------
Write-Host "[2/5] 同步 AGENTS.md 工作约定..." -ForegroundColor Yellow

$agentsDest = "$DesktopData\knowledge\AGENTS.md"
Copy-Item "$ProjectRoot\AGENTS.md" $agentsDest -Force
Write-Host "  AGENTS.md -> knowledge\AGENTS.md" -ForegroundColor Green

# ------------------------------------------------------------
# 3. 复制 manifest.json
# ------------------------------------------------------------
Write-Host "[3/5] 同步 manifest.json 项目元数据..." -ForegroundColor Yellow

$manifestDest = "$DesktopData\manifest.json"
Copy-Item "$ProjectRoot\manifest.json" $manifestDest -Force
Write-Host "  manifest.json -> 桌面端根目录" -ForegroundColor Green

# ------------------------------------------------------------
# 4. 同步 .env.example 作为配置参考
# ------------------------------------------------------------
Write-Host "[4/5] 同步 .env.example 配置模板..." -ForegroundColor Yellow

$envExampleDest = "$DesktopData\.env.project-template"
Copy-Item "$ProjectRoot\.env.example" $envExampleDest -Force
Write-Host "  .env.example -> .env.project-template" -ForegroundColor Green

# ------------------------------------------------------------
# 5. 验证 .env 中的关键配置
# ------------------------------------------------------------
Write-Host "[5/5] 验证 .env 环境变量..." -ForegroundColor Yellow

$envFile = "$DesktopData\.env"
$envContent = Get-Content $envFile -Raw

$checks = @(
    @{ Key = "IMA_OPENAPI_CLIENTID";    Desc = "IMA 知识库" },
    @{ Key = "SKILLHUB_API_BASE";       Desc = "SkillHub" },
    @{ Key = "OPENCLAW_GATEWAY_PORT";   Desc = "OpenClaw 网关" },
    @{ Key = "OPENCLAW_MODEL_PRIMARY";  Desc = "主模型" },
    @{ Key = "HERMES_LOG_LEVEL";        Desc = "日志级别" }
)

foreach ($check in $checks) {
    if ($envContent -match "$($check.Key)=.+") {
        Write-Host "  $($check.Desc) ($($check.Key)) OK" -ForegroundColor Green
    } else {
        Write-Host "  $($check.Desc) ($($check.Key)) MISSING" -ForegroundColor Red
    }
}

# ------------------------------------------------------------
# 总结
# ------------------------------------------------------------
Write-Host ""
Write-Host "=== 融合完成 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "已融合的配置层:" -ForegroundColor White
Write-Host "  1. config.yaml    - 模型对齐为 claude-sonnet-4-5，添加 OpenClaw 网关配置"
Write-Host "  2. AGENTS.md      - 工作约定同步到 knowledge 目录"
Write-Host "  3. manifest.json  - 项目元数据（44 skills, 13 knowledge, UI 设计层）"
Write-Host "  4. .env           - IMA / SkillHub / OpenClaw 等环境变量"
Write-Host "  5. .env.project-template - 完整配置模板参考"
Write-Host ""
Write-Host "备份位置: $BackupDir" -ForegroundColor Gray
Write-Host ""
Write-Host "下一步: 重启 Hermes Agent CN Desktop 客户端使配置生效" -ForegroundColor Yellow
