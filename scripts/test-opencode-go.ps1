# OpenCode Go API verification (ASCII-safe, no heredoc Chinese)
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8

# Read API key from Hermes desktop .env
$envFile = Join-Path $env:LOCALAPPDATA "hermes\.env"
$key = $null
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^OPENCODE_GO_API_KEY=(.+)$') { $script:key = $Matches[1].Trim() }
    }
}
if (-not $key) {
    Write-Host "ERROR: OPENCODE_GO_API_KEY not found in $envFile" -ForegroundColor Red
    exit 1
}

$base = "https://opencode.ai/zen/go/v1"
$keyPreview = $key.Substring(0, [Math]::Min(12, $key.Length)) + "..."
Write-Host "=== OpenCode Go API verification ===" -ForegroundColor Cyan
Write-Host "Base: $base"
Write-Host "Key:  $keyPreview"
Write-Host ""

# --- [1/3] List models ---
Write-Host "[1/3] GET /models" -ForegroundColor Yellow
try {
    $resp = Invoke-RestMethod -Uri "$base/models" -Headers @{ "Authorization" = "Bearer $key" } -Method GET -TimeoutSec 30
    Write-Host "  OK" -ForegroundColor Green
    if ($resp.data) {
        Write-Host "  Available models ($($resp.data.Count)):"
        $resp.data | ForEach-Object { Write-Host "    - $($_.id)" }
    } else {
        $resp | ConvertTo-Json -Depth 3
    }
} catch {
    $code = $null
    try { $code = $_.Exception.Response.StatusCode.value__ } catch {}
    Write-Host "  FAILED (HTTP $code): $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# --- [2/3] Real chat (non-streaming) ---
Write-Host ""
Write-Host "[2/3] POST /chat/completions (minimax-m3)" -ForegroundColor Yellow
$promptZh = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::UTF8.GetBytes("Ni hao, que ren API yi lian tong. Hui fu yi ju hua."))
$body = @{
    model = "minimax-m3"
    messages = @(
        @{ role = "system"; content = "You are a helpful assistant. Reply concisely in Chinese." }
        @{ role = "user";   content = $promptZh }
    )
    max_tokens = 80
    temperature = 0.7
} | ConvertTo-Json -Depth 5 -Compress

try {
    $resp = Invoke-RestMethod -Uri "$base/chat/completions" -Headers @{
        "Authorization" = "Bearer $key"
        "Content-Type"  = "application/json; charset=utf-8"
    } -Method POST -Body $body -TimeoutSec 60
    Write-Host "  OK" -ForegroundColor Green
    $reply = $resp.choices[0].message.content
    Write-Host "  Reply: $reply" -ForegroundColor Cyan
    if ($resp.usage) {
        Write-Host "  Tokens: prompt=$($resp.usage.prompt_tokens) completion=$($resp.usage.completion_tokens) total=$($resp.usage.total_tokens)"
    }
} catch {
    $code = $null
    try { $code = $_.Exception.Response.StatusCode.value__ } catch {}
    Write-Host "  FAILED (HTTP $code): $($_.Exception.Message)" -ForegroundColor Red
}

# --- [3/3] Streaming test ---
Write-Host ""
Write-Host "[3/3] POST /chat/completions (stream=true, minimax-m3)" -ForegroundColor Yellow
$streamBody = @{
    model = "minimax-m3"
    messages = @(@{ role = "user"; content = "Reply in 5 words: confirm API connection." })
    max_tokens = 30
    stream = $true
} | ConvertTo-Json -Depth 5 -Compress

try {
    $req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, "$base/chat/completions")
    $req.Headers.Add("Authorization", "Bearer $key")
    $req.Content = [System.Net.Http.StringContent]::new($streamBody, [System.Text.Encoding]::UTF8, "application/json")
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds(30)
    $response = $client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).Result
    $stream = $response.Content.ReadAsStreamAsync().Result
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
    $content = ""
    $lineCount = 0
    while (-not $reader.EndOfStream -and $lineCount -lt 50) {
        $line = $reader.ReadLine()
        $lineCount++
        if ($line -match '^data: (.+)$') {
            $chunk = $Matches[1]
            if ($chunk -ne '[DONE]') {
                try {
                    $obj = $chunk | ConvertFrom-Json -ErrorAction SilentlyContinue
                    if ($obj.choices[0].delta.content) {
                        $content += $obj.choices[0].delta.content
                    }
                } catch {}
            }
        }
    }
    $reader.Close(); $response.Dispose(); $client.Dispose()
    if ($content) {
        Write-Host "  OK" -ForegroundColor Green
        Write-Host "  Streamed: $content" -ForegroundColor Cyan
    } else {
        Write-Host "  No content (endpoint may not support streaming for this model)" -ForegroundColor Yellow
    }
} catch {
    $code = $null
    try { $code = $_.Exception.Response.StatusCode.value__ } catch {}
    Write-Host "  FAILED (HTTP $code): $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host "If all 3 are OK, OpenCode Go is ready in Hermes client."
