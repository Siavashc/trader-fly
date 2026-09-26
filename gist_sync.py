#!/usr/bin/env python3
"""
gist_sync.py — publishes the fly's state to a secret GitHub Gist so the
GitHub-Pages mini app can read it (no tunnel needed).

  - start(): restore local state from the gist at boot + background resync
  - upload(): data/trader.json, data/candles.json, user_states/trader_brain.json
              + state.json (same shape the old /api/state served)
  - poll_close(): honors a close command left in the gist by the mini app

Env: GH_TOKEN (gist scope), GH_GIST_ID.
"""
import json
import os
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
API = 'https://api.github.com/gists/{}'
EVERY_SEC = float(os.environ.get('SYNC_EVERY_SEC', '60'))
_lock = threading.Lock()

STATE_FILE = BASE_DIR / 'data' / 'trader.json'
CANDLES_FILE = BASE_DIR / 'data' / 'candles.json'
BRAIN_FILE = BASE_DIR / 'user_states' / 'trader_brain.json'


def _headers():
    return {'Authorization': f"Bearer {os.environ['GH_TOKEN']}",
            'Accept': 'application/vnd.github+json'}


def _gist_url():
    return API.format(os.environ['GH_GIST_ID'])


def restore():
    """Pull the latest state files from the gist (boot only, best-effort)."""
    try:
        import requests
        g = requests.get(_gist_url(), headers=_headers(), timeout=15).json()
        n = 0
        for p in (STATE_FILE, CANDLES_FILE, BRAIN_FILE):
            content = (g.get('files', {}).get(p.name) or {}).get('content')
            if content:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding='utf-8')
                n += 1
        print(f'gist_sync: restored {n} state files from gist', flush=True)
    except Exception as e:
        print(f'gist_sync: restore skipped ({e})', flush=True)


def _snapshot_files():
    files = {}
    for p in (STATE_FILE, CANDLES_FILE, BRAIN_FILE):
        if p.exists():
            files[p.name] = {'content': p.read_text(encoding='utf-8')}
    # state.json = same shape the old /api/state served (mini app API)
    try:
        import trader
        s = trader.snapshot()
        st = s['state']
        pos = st['position']
        upnl = 0.0
        if pos and s['price'] > 0:
            move = (s['price'] / pos['entry'] - 1) * 100 * \
                (1 if pos['side'] == 'LONG' else -1)
            upnl = round(pos['notional'] * move / 100, 2)
        files['state.json'] = {'content': json.dumps({
            'price': s['price'], 'price_real': s['price_real'],
            'candles': s['candles'], 'now': s['now'],
            'position': pos, 'upnl': upnl,
            'pnl_total': st['pnl_total'], 'equity_start': st['equity_start'],
            'wins': st['wins'], 'losses': st['losses'],
            'trades': st['trades'][-200:], 'brain_notes': st['brain_notes'][-8:],
            'feed_ok': (s['now'] - s['last_fetch_ok']) < 600 if s['last_fetch_ok'] else False,
        })}
    except Exception as e:
        print(f'gist_sync: state.json build failed: {e}', flush=True)
    return files


def upload():
    """Push current state into the gist. Returns True if content changed."""
    with _lock:
        files = _snapshot_files()
    if not files:
        return False
    try:
        import requests
        g = requests.get(_gist_url(), headers=_headers(), timeout=15).json()
        changed = any((g.get('files', {}).get(name) or {}).get('content') != f['content']
                      for name, f in files.items())
        if not changed:
            return False
        r = requests.patch(_gist_url(), headers=_headers(),
                           json={'files': files}, timeout=30)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f'gist_sync: upload failed (will retry): {e}', flush=True)
        return False


def poll_close():
    """If the mini app queued a close request in the gist, honor + clear it."""
    try:
        import requests
        g = requests.get(_gist_url(), headers=_headers(), timeout=15).json()
        if 'close_cmd.json' not in g.get('files', {}):
            return False
        r = requests.patch(_gist_url(), headers=_headers(),
                           json={'files': {'close_cmd.json': None}}, timeout=30)
        r.raise_for_status()
        print('gist_sync: close command received from mini app', flush=True)
        return True
    except Exception:
        return False


def _loop():
    while True:
        time.sleep(EVERY_SEC)
        try:
            if upload():
                print('gist_sync: state published to gist', flush=True)
            if poll_close():
                import trader
                trader.request_close()
        except Exception as e:
            print(f'gist_sync: sync error: {e}', flush=True)


def start():
    """Restore at boot, then publish + poll every ~60s. No-ops unconfigured."""
    if not (os.environ.get('GH_TOKEN') and os.environ.get('GH_GIST_ID')):
        print('gist_sync: not configured (mini app state will not sync)', flush=True)
        return
    restore()
    threading.Thread(target=_loop, daemon=True, name='trader-fly-gist').start()
    print(f'gist_sync: publishing every {EVERY_SEC:.0f}s', flush=True)