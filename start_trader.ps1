# start_trader.ps1 — launch Trader Fly: tunnel + bot (single process)
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:BRIAN2_TARGET = 'numpy'

$py = 'D:\telegram_games\fly-brain-bot\.venv\Scripts\python.exe'
$cloudflared = 'D:\tools\cloudflared.exe'
$port = 8791

# 1) fresh quick tunnel (URL changes every restart); logs merged into one file
$tunnelLog = Join-Path $env:TEMP 'trader-fly-tunnel.txt'
if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
$bat = Join-Path $env:TEMP 'trader-fly-tunnel.cmd'
Set-Content $bat "@echo off`r`n`"$cloudflared`" tunnel --url http://localhost:$port >> `"$tunnelLog`" 2>&1" -Encoding ascii
Start-Process $bat -WindowStyle Hidden

# 2) wait for the trycloudflare URL and write it into .env BASE_URL
$url = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    $txt = ''
    if (Test-Path $tunnelLog) { $txt = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue }
    if ($txt -match 'https://[a-z0-9-]+\.trycloudflare\.com') { $url = $Matches[0]; break }
}
if ($url) {
    $envPath = Join-Path $PSScriptRoot '.env'
    $lines = Get-Content $envPath | Where-Object { $_ -notmatch '^BASE_URL=' }
    $lines += "BASE_URL=$url"
    Set-Content $envPath $lines -Encoding utf8
    Write-Host "Tunnel: $url" -ForegroundColor Green
} else {
    Write-Host "WARNING: tunnel URL not found - Mini App button will be missing (bot still works)" -ForegroundColor Yellow
}

# 3) run bot + engine + web app (Ctrl+C stops everything)
& $py -X utf8 bot.py