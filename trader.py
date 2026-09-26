#!/usr/bin/env python3
"""
trader.py — Trader Fly engine: market feed + brain decisions + positions + ledger.

One global Trader Fly with a PAPER account:
- Market: real BTC-USD 1m candles from yfinance every 60s; a live synthetic tick
  (mean-reverting jitter) every 5s keeps the chart alive between fetches.
  If Yahoo is unreachable the fly keeps trading on the synthetic market — never dead.
- Brain: every ~2min the real 138K-neuron connectome (fresh subprocess, see
  trader_cycle.py) reacts to momentum-as-stimulus and its behavior = the trade.
- Positions: $1,000 notional, stop -0.35%, take-profit +0.7%, brain-exit too.
- On close: dopamine reward/punishment queued into the fly's own brain memory.
"""
import asyncio
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / 'data' / 'trader.json'
CANDLES_FILE = BASE / 'data' / 'candles.json'
SYMBOL = 'BTC-USD'
CANDLE_SEC = 60          # real 1m candles
TICK_SEC = 5             # live synthetic tick
CYCLE_SEC = 122          # brain decision cadence (2-min, like the honest original)
NOTIONAL_USD = 1000.0
STOP_PCT = -0.35
TAKE_PCT = 0.70
MAX_CANDLES = 600
MAX_TRADES = 500

# interpreter for brain subprocesses: same python we run in (works in a venv
# on Windows AND inside a Docker container); BRAIN_PY overrides for special setups
VENV_PY = Path(os.environ['BRAIN_PY']) if os.environ.get('BRAIN_PY') else Path(sys.executable)


# ---------------------------------------------------------------------------
# state (single dict, persisted atomically; webapp/bot read snapshots)
# ---------------------------------------------------------------------------

def default_state():
    return {
        'position': None,          # {side, entry, notional, stim, t_open, why}
        'pnl_total': 0.0,
        'equity_start': 1000.0,
        'wins': 0, 'losses': 0,
        'trades': [],              # closed trades, newest last
        'brain_notes': [],         # {t, price, stim, action, why}
        'pending_learn': None,     # queued into next brain cycle
        'kc_last': [],
        'trade_seq': 0,
    }


STATE = default_state()
CANDLES = []                   # [{t,o,h,l,c}] 1m
PRICE = 0.0                    # live price (synthetic-ticked, anchored to real)
PRICE_REAL = 0.0
LAST_FETCH_OK = 0.0
NOTIFY = None                  # async callback set by bot.py
_req_close = False             # manual "take profit now" flag from webapp


def snapshot() -> dict:
    return json.loads(json.dumps({
        'state': STATE, 'candles': CANDLES[-90:],
        'price': PRICE, 'price_real': PRICE_REAL,
        'last_fetch_ok': LAST_FETCH_OK, 'now': int(time.time()),
    }))


def _atomic_write(path: Path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def save_state():
    _atomic_write(STATE_FILE, STATE)
    _atomic_write(CANDLES_FILE, {'candles': CANDLES[-MAX_CANDLES:]})


def load_state():
    global STATE, CANDLES, PRICE, PRICE_REAL
    if STATE_FILE.exists():
        try:
            STATE.update(json.loads(STATE_FILE.read_text(encoding='utf-8')))
        except Exception as e:
            print(f'[trader] state load failed: {e}', flush=True)
    if CANDLES_FILE.exists():
        try:
            CANDLES = json.loads(CANDLES_FILE.read_text(encoding='utf-8'))['candles']
            PRICE = PRICE_REAL = CANDLES[-1]['c'] if CANDLES else 0.0
        except Exception:
            CANDLES = []


# ---------------------------------------------------------------------------
# market feed
# ---------------------------------------------------------------------------

async def fetch_market():
    """Real BTC-USD 1m candles via yfinance (blocking lib -> thread)."""
    import yfinance as yf
    def _dl():
        df = yf.download(SYMBOL, period='1d', interval='1m',
                         progress=False, auto_adjust=True)
        return df
    df = await asyncio.to_thread(_dl)
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, __import__('pandas').MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = []
    for idx, row in df.iterrows():
        try:
            t = int(idx.timestamp())
            out.append({'t': t, 'o': float(row['Open']), 'h': float(row['High']),
                        'l': float(row['Low']), 'c': float(row['Close'])})
        except Exception:
            continue
    return out


def _synth_candle(t: int, prev_close: float) -> dict:
    """Synthetic 1m candle (random walk with mild regime drift) — fallback /
    bridge when Yahoo fails."""
    vol = max(12.0, prev_close * 0.0004)
    drift = random.choice([-1, 1]) * vol * random.uniform(0.0, 0.35)
    o = prev_close
    c = max(1.0, o + random.gauss(drift, vol))
    hi = max(o, c) + abs(random.gauss(0, vol * 0.6))
    lo = min(o, c) - abs(random.gauss(0, vol * 0.5))
    return {'t': t, 'o': o, 'h': hi, 'l': lo, 'c': c}


def _merge_real(real: list):
    """Merge fetched 1m candles into CANDLES (dedupe by minute t)."""
    global PRICE_REAL
    if not real:
        return
    have = {c['t']: i for i, c in enumerate(CANDLES)}
    for c in real:
        c['o'], c['h'], c['l'], c['c'] = (round(c['o'], 2), round(c['h'], 2),
                                          round(c['l'], 2), round(c['c'], 2))
        if c['t'] in have:
            CANDLES[have[c['t']]] = c
        else:
            CANDLES.append(c)
    CANDLES.sort(key=lambda x: x['t'])
    del CANDLES[:-MAX_CANDLES]
    PRICE_REAL = CANDLES[-1]['c']


async def market_loop():
    global PRICE, PRICE_REAL, LAST_FETCH_OK
    fails = 0
    while True:
        try:
            real = await fetch_market()
            if real and len(real) >= 5:
                _merge_real(real)
                PRICE = PRICE_REAL
                LAST_FETCH_OK = int(time.time())
                fails = 0
            else:
                fails += 1
        except Exception as e:
            fails += 1
            print(f'[trader] market fetch fail ({fails}): {e}', flush=True)
        # if the feed is stale, grow a synthetic market so the fly never stops
        if not CANDLES:
            base = 65000.0 + random.uniform(-500, 500)
            t0 = int(time.time()) // 60 * 60 - 90 * 60
            c = base
            for i in range(90):
                c2 = _synth_candle(t0 + i * 60, c)
                CANDLES.append(c2)
                c = c2['c']
            PRICE = PRICE_REAL = c
            print('[trader] seeded synthetic market (no feed yet)', flush=True)
        save_state()
        await asyncio.sleep(CANDLE_SEC)


async def tick_loop():
    """Live tick every TICK_SEC: mean-reverting jitter around the real anchor;
    checks stop/take-profit on the open position; applies manual close."""
    global PRICE, _req_close
    while True:
        try:
            if CANDLES and PRICE_REAL > 0:
                anchor = CANDLES[-1]['c']
                # pull toward real anchor + small noise (feels alive, never drifts)
                pull = (PRICE_REAL - PRICE) * 0.35
                noise = random.gauss(0, max(1.0, PRICE_REAL * 0.00006))
                PRICE = max(1.0, PRICE + pull + noise)
                hit = check_position()
                if hit and STATE['position']:
                    await close_position(hit)
            if _req_close:
                _req_close = False
                if STATE['position']:
                    await close_position('manual close')
        except Exception as e:
            print(f'[trader] tick error: {e}', flush=True)
        await asyncio.sleep(TICK_SEC)


# ---------------------------------------------------------------------------
# trading logic
# ---------------------------------------------------------------------------

def _mom3() -> float:
    """Momentum over the last 3 minutes, in %."""
    if len(CANDLES) < 4:
        return 0.0
    return (CANDLES[-1]['c'] / CANDLES[-3]['c'] - 1.0) * 100.0


def encode_stimulus(mom: float):
    """Market -> stimulus + dose. Bullish = sweet taste, bearish = danger smell,
    flat = neutral hearing. (1m BTC moves are typically ~0.02-0.08%.)"""
    if mom > 0.05:
        return 'taste_sweet', min(1.4, 0.5 + abs(mom) * 12)
    if mom < -0.05:
        return 'smell_danger', min(1.4, 0.5 + abs(mom) * 12)
    return 'hearing', 0.35


def decide(result: dict):
    """Brain's predicted behavior -> trading action."""
    behs = result.get('behaviors') or []
    if not behs:
        return 'HOLD', 'no reaction'
    b = behs[0].get('behavior', '')
    score = behs[0].get('score', 0)
    if b in ('feeding', 'forward_walk', 'mating_acceptance'):
        return 'BUY', f'{b} ({behs[0].get("intensity")})'
    if b in ('escape', 'backward_walk', 'mating_rejection'):
        return 'SELL', f'{b} ({behs[0].get("intensity")})'
    if score < 25:
        return 'HOLD', f'{b} too weak ({behs[0].get("intensity")})'
    return 'HOLD', f'{b} ({behs[0].get("intensity")})'


async def brain_cycle():
    """One connectome cycle in a fresh subprocess; manage position; maybe open."""
    mom = _mom3()
    stim, inten = encode_stimulus(mom)
    base_freq = {'taste_sweet': 200, 'smell_danger': 250, 'hearing': 150}[stim]
    freq = max(40, min(420, int(base_freq * (0.45 + 1.1 * inten))))
    payload = json.dumps({'stim': stim, 'freq': freq, 'learn': STATE.pop('pending_learn', None)})
    try:
        proc = await asyncio.create_subprocess_exec(
            str(VENV_PY), '-X', 'utf8', str(BASE / 'trader_cycle.py'), payload,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(BASE))
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=240)
    except Exception as e:
        print(f'[trader] brain cycle failed: {e}', flush=True)
        save_state()
        return None
    result = None
    for line in out.decode('utf-8', 'ignore').strip().splitlines():
        if line.startswith('{'):
            result = json.loads(line)
            break
    if result is None:
        save_state()
        return None

    if result.get('learned'):
        print(f"[trader] dopamine applied: {result['learned']:,} synapses", flush=True)
    STATE['kc_last'] = result.get('kc', [])
    action, why = decide(result)
    price = PRICE or (CANDLES[-1]['c'] if CANDLES else 0.0)
    print(f'[trader] price={price:,.0f} mom3={mom:+.2f}% -> {stim}@{inten:.2f} '
          f'-> {action} ({why})', flush=True)

    # --- manage open position with the fresh verdict ---
    if STATE['position']:
        pos = STATE['position']
        brain_exit = (pos['side'] == 'LONG' and action == 'SELL') or \
                     (pos['side'] == 'SHORT' and action == 'BUY')
        if brain_exit:
            await close_position(f'brain flipped: {why}')
    # --- maybe open ---
    if not STATE['position'] and action in ('BUY', 'SELL') and price > 0:
        STATE['position'] = {'side': 'LONG' if action == 'BUY' else 'SHORT',
                             'entry': price, 'notional': NOTIONAL_USD,
                             'stim': stim, 'why': why, 't_open': int(time.time())}
        await _event({'type': 'open', 'side': STATE['position']['side'],
                      'entry': price, 'why': why})
        print(f"[trader] OPEN {STATE['position']['side']} ${NOTIONAL_USD:.0f} "
              f"@ {price:,.0f} ({why})", flush=True)

    STATE.setdefault('brain_notes', []).append(
        {'t': int(time.time()), 'price': round(price, 1), 'stim': stim,
         'action': action, 'why': why})
    del STATE['brain_notes'][:-60]
    save_state()
    return result


async def close_position(why: str):
    pos = STATE['position']
    if not pos or PRICE <= 0:
        STATE['position'] = None
        return
    move = (PRICE / pos['entry'] - 1) * 100 * (1 if pos['side'] == 'LONG' else -1)
    pnl = pos['notional'] * move / 100
    STATE['pnl_total'] = round(STATE['pnl_total'] + pnl, 2)
    if pnl >= 0:
        STATE['wins'] += 1
        STATE['pending_learn'] = {'action': 'reward', 'kc': STATE.get('kc_last', []),
                                  'strength': 1.5, 'label': f'trade-win {pos["side"]}'}
    else:
        STATE['losses'] += 1
        STATE['pending_learn'] = {'action': 'punish', 'kc': STATE.get('kc_last', []),
                                  'strength': 0.3, 'label': f'trade-loss {pos["side"]}'}
    STATE['trade_seq'] += 1
    trade = {'id': STATE['trade_seq'], 'side': pos['side'],
             'entry': round(pos['entry'], 2), 'exit': round(PRICE, 2),
             'pnl': round(pnl, 2), 'stim': pos.get('stim', ''),
             'why': why, 't_open': pos['t_open'], 't_close': int(time.time())}
    STATE['trades'].append(trade)
    del STATE['trades'][:-MAX_TRADES]
    STATE['position'] = None
    save_state()
    tag = 'REWARD (PAM queued)' if pnl >= 0 else 'PUNISH (PPL1 queued)'
    print(f'[trader] closed {trade["side"]} -> {tag} ${pnl:+.2f} | '
          f'total ${STATE["pnl_total"]:+.2f} '
          f'(W{STATE["wins"]}/L{STATE["losses"]})', flush=True)
    await _event({'type': 'close', 'trade': trade})


def check_position():
    """SL/TP check with the live ticked price (no await needed)."""
    pos = STATE['position']
    if not pos or PRICE <= 0:
        return None
    move = (PRICE / pos['entry'] - 1) * 100 * (1 if pos['side'] == 'LONG' else -1)
    if move <= STOP_PCT:
        return f'stop-loss hit ({move:+.2f}%)'
    if move >= TAKE_PCT:
        return f'take-profit hit ({move:+.2f}%)'
    return None


async def _supervise(check):
    while True:
        await asyncio.sleep(30)
        check()


async def engine_loop(notify_cb=None):
    """Main engine: market feed + ticks + brain cadence + SL/TP enforcement."""
    global NOTIFY, _req_close
    NOTIFY = notify_cb
    load_state()
    tasks = {'market': asyncio.create_task(market_loop()),
             'tick': asyncio.create_task(tick_loop())}

    def _resurrect():
        # supervisor: a dead feed/tick task must never silence the fly
        for name, factory in (('market', market_loop), ('tick', tick_loop)):
            if tasks[name].done():
                err = tasks[name].exception()
                print(f'[trader] {name} task died ({err}); restarting', flush=True)
                tasks[name] = asyncio.create_task(factory())

    supervisor = asyncio.create_task(_supervise(_resurrect))
    # let the market warm up a moment before the first brain cycle
    for _ in range(20):
        if CANDLES and PRICE_REAL > 0:
            break
        await asyncio.sleep(1)
    while True:
        try:
            hit = check_position()
            if hit and STATE['position']:
                await close_position(hit)
            await brain_cycle()
        except Exception as e:
            print(f'[trader] engine error: {e}', flush=True)
            await asyncio.sleep(30)
        await asyncio.sleep(CYCLE_SEC)


async def _event(ev: dict):
    if NOTIFY:
        try:
            await NOTIFY(ev)
        except Exception as e:
            print(f'[trader] notify error: {e}', flush=True)


def request_close():
    global _req_close
    _req_close = True


def history(sort: str = 'time_desc') -> list:
    """Sorted trades: time_desc | time_asc | pnl_desc | pnl_asc."""
    trades = list(STATE['trades'])
    key = {'time_desc': lambda t: t['t_close'],
           'time_asc': lambda t: t['t_close'],
           'pnl_desc': lambda t: t['pnl'],
           'pnl_asc': lambda t: t['pnl']}[sort]
    trades.sort(key=key, reverse=sort.endswith('_desc'))
    return trades


if __name__ == '__main__':
    async def _noop(ev):
        pass
    asyncio.run(engine_loop(_noop))