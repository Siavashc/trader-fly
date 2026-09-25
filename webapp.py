#!/usr/bin/env python3
"""
webapp.py — Trader Fly Mini App backend.

Serves web/ and a small read API over the trading engine's in-memory state:
  GET /api/state                 -> price, candles, position, totals, recent notes
  GET /api/history?sort=...      -> full trade ledger sorted (time/pnl)
  POST /api/close                -> ask the fly to close the open position now
No auth: everything here is read-only paper-trading data (no user writes).
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / '.env')

import trader

app = FastAPI(title='Trader Fly', docs_url=None, redoc_url=None)

SORTS = ('time_desc', 'time_asc', 'pnl_desc', 'pnl_asc')


@app.get('/api/state')
async def api_state():
    s = trader.snapshot()
    st = s['state']
    pos = st['position']
    upnl = 0.0
    if pos and s['price'] > 0:
        move = (s['price'] / pos['entry'] - 1) * 100 * (1 if pos['side'] == 'LONG' else -1)
        upnl = round(pos['notional'] * move / 100, 2)
    return {
        'price': s['price'], 'price_real': s['price_real'],
        'candles': s['candles'], 'now': s['now'],
        'position': pos, 'upnl': upnl,
        'pnl_total': st['pnl_total'], 'equity_start': st['equity_start'],
        'wins': st['wins'], 'losses': st['losses'],
        'trades': st['trades'][-200:], 'brain_notes': st['brain_notes'][-8:],
        'feed_ok': (s['now'] - s['last_fetch_ok']) < 600 if s['last_fetch_ok'] else False,
    }


@app.get('/api/history')
async def api_history(sort: str = 'time_desc'):
    if sort not in SORTS:
        raise HTTPException(400, f'sort must be one of {SORTS}')
    return {'sort': sort, 'trades': trader.history(sort)}


@app.post('/api/close')
async def api_close():
    if not trader.STATE['position']:
        return {'ok': False, 'reason': 'no open position'}
    trader.request_close()
    return {'ok': True, 'reason': 'closing at next tick (<=5s)'}


@app.get('/health')
async def api_health():
    """Liveness endpoint for platform health checks / external watchdogs."""
    s = trader.snapshot()
    return {'ok': True, 'price': s['price'], 'pnl': s['state']['pnl_total'],
            'open': bool(s['state']['position']), 'feed_ok': s['last_fetch_ok'] > 0}


@app.get('/')
async def index():
    return FileResponse(BASE_DIR / 'web' / 'index.html')


app.mount('/', StaticFiles(directory=str(BASE_DIR / 'web')), name='web')