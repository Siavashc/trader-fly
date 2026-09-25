# Trader Fly 🪰📈

A standalone Telegram bot: **a real fruit-fly brain (138,639 neurons, FlyWire
connectome) paper-trades BTC** from a tiny apartment desk — and you watch it
live in a lofi-style Trading Desk mini app.

Separate from the Fly Lab bot (`D:\telegram_games\fly-brain-bot`), with its own
bot token, port (:8791), ledger and brain memory — so the game flies and the
trader never mix, and the OOM problem is gone (each brain decision runs in a
fresh subprocess that fully releases Brian2 memory on exit).

## What the fly does

- Every ~2 min, BTC 1m momentum is encoded as a real stimulus
  (bullish = sweet taste, bearish = danger smell) at dose-scaled frequency.
- The real connectome reacts; its behavior decides:
  approach/feeding → **BUY**, escape/avoidance → **SELL**, weak → HOLD.
- Positions: $1,000 notional, stop −0.35%, take-profit +0.7%, or brain-flip exit.
- On close: profit → PAM **dopamine reward**, loss → PPL1 **punishment**,
  applied to the exact Kenyon cells that fired — the fly genuinely learns.
- Paper trading only. Ledger in `data/trader.json`.

## Mini App — the Trading Desk

- The fly on a chair, back to you, typing in front of a live candle monitor.
- Big window behind: city skyline that goes **day / night / dawn / dusk by YOUR
  device clock** — sun & clouds by day, moon, stars and lit windows at night,
  desk lamp + monitor glow after dark.
- Live price, session P/L, open position card (with "take profit now"),
  equity curve on the side monitor, and the fly's mood line.
- **Trade history sortable by time (newest/oldest) and amount (best/worst)**.

## Bot commands

| Command | What |
|---|---|
| `/start` | intro + 🏢 Open Trading Desk + 🔔 trade alerts toggle |
| `/status` | price, total P&L, W/L, recent brain states |
| `/position` | open position with live uPnL |
| `/history` | trade history + inline sort buttons |

🔔 subscribers get a message on every open/close.

## Run

```powershell
powershell -ExecutionPolicy Bypass -File start_trader.ps1
```

Launches a fresh cloudflared quick tunnel, auto-writes `BASE_URL` into `.env`,
then runs bot + engine + web app in one process. URL changes on every restart.

## Files

- `trader.py` — engine: market feed (yfinance + synthetic fallback), brain
  cadence, positions, ledger
- `trader_cycle.py` — one connectome cycle in a fresh subprocess (reuses
  `D:\telegram_games\fly-brain-bot`; trader's own memory at
  `user_states/trader_brain.json`)
- `webapp.py` — FastAPI (:8791): `/api/state`, `/api/history?sort=…`, `/api/close`
- `bot.py` — aiogram3 polling + alerts; runs engine + uvicorn in one process
- `web/index.html` — the Trading Desk scene (pure canvas 2D, no dependencies)
- `start_trader.ps1` — tunnel + auto-BASE_URL + launch