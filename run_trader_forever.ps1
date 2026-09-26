# run_trader_forever.ps1 — Trader Fly supervisor: respawns bot.py forever.
# The mini app lives on GitHub Pages (siavashc.github.io/trader-fly) and reads
# state from the fly's secret Gist — no tunnel needed. Bot + brain stay local.
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:BRIAN2_TARGET = 'numpy'

$py      = 'D:\telegram_games\fly-brain-bot\.venv\Scripts\python.exe'
$dataDir = Join-Path $PSScriptRoot 'data'
$botLog  = Join-Path $dataDir 'bot.log'
$supLog  = Join-Path $dataDir 'supervisor.log'
$hbFile  = Join-Path $dataDir 'last_heartbeat.txt'
$botCmd  = Join-Path $env:TEMP 'trader-fly-bot.cmd'
$envPath = Join-Path $PSScriptRoot '.env'

function Log($msg) {
    if ((Test-Path $supLog) -and ((Get-Item $supLog).Length -gt 2MB)) {
        Move-Item $supLog ($supLog + '.old') -Force
    }
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Add-Content $supLog -Encoding utf8
}

function Get-BotPids {
    # exactly the trader-fly bot: only processes whose command line names
    # trader-fly\bot.py (the launcher always passes the absolute path)
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'trader-fly\\bot\.py' } |
        Select-Object -ExpandProperty ProcessId
}

function Send-Tg($text) {
    # best-effort message to alert subscribers, straight over the Telegram API
    try {
        $token = (Get-Content $envPath | Where-Object { $_ -match '^BOT_TOKEN=' }) -replace '^BOT_TOKEN=', ''
        $subsPath = Join-Path $dataDir 'subscribers.json'
        if ($token -and (Test-Path $subsPath)) {
            $subs = Get-Content $subsPath -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
            foreach ($u in $subs) {
                try {
                    Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
                        -Method Post -Body @{ chat_id = $u; text = $text; parse_mode = 'HTML' } `
                        -TimeoutSec 10 | Out-Null
                } catch {}
            }
        }
    } catch {}
}

# ---------------------------------------------------------------------------
# single-supervisor guard: if another copy of this script is already running,
# exit (this makes the logon task + manual runs safe to double-fire)
$other = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match 'run_trader_forever' -and $_.ProcessId -ne $PID }
if ($other) { exit 0 }

Log '=== supervisor starting ==='

# single-instance guard: kill any leftover trader-fly bot before we begin
Get-BotPids | ForEach-Object { Log "killing stale bot pid $_"; Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
$crashes = 0
$lastStart = Get-Date

while ($true) {
    if ($botLog.Length -gt 5MB) { Move-Item $botLog ($botLog + '.old') -Force }

    # --- launch bot via .cmd wrapper so output APPENDS to bot.log ---------
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Set-Content $botCmd "@echo off`r`ncd /d `"$PSScriptRoot`"`r`necho ===== $stamp bot start ===== >> `"$botLog`"`r`n`"$py`" -X utf8 `"$PSScriptRoot\bot.py`" >> `"$botLog`" 2>&1`r`necho ===== $stamp bot exit %ERRORLEVEL% ===== >> `"$botLog`"" `
        -Encoding ascii
    $bot = Start-Process cmd -ArgumentList '/c', $botCmd -WindowStyle Hidden -PassThru
    $lastStart = Get-Date
    Log "bot started (pid $($bot.Id))"

    # daily heartbeat (once per day, to alert subscribers)
    $today = (Get-Date).ToString('yyyy-MM-dd')
    $lastHb = ''
    if (Test-Path $hbFile) { $lastHb = (Get-Content $hbFile -Raw -ErrorAction SilentlyContinue) }
    if ($lastHb -ne $today) {
        Send-Tg '🪰 Trader Fly heartbeat — online. Desk: https://siavashc.github.io/trader-fly'
        Set-Content $hbFile $today -Encoding utf8
    }

    # --- watch --------------------------------------------------------------
    while (-not $bot.HasExited) { Start-Sleep -Seconds 20 }

    # --- post-mortem + backoff ---------------------------------------------
    $ran = ((Get-Date) - $lastStart).TotalSeconds
    if ($ran -lt 60) {
        Log "bot lived only $([math]::Round($ran))s - backing off 30s"
        Start-Sleep -Seconds 30
    }
    $crashes++
    Log "bot cycle ended (lived $([math]::Round($ran))s, restart #$crashes)"
    Send-Tg "🪰 Trader Fly was restarted automatically (lived $([math]::Round($ran))s, restart #$crashes). Back online."
    Start-Sleep -Seconds 10
}