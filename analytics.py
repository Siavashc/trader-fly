#!/usr/bin/env python3
"""
analytics.py — lightweight user tracking for the Trader Fly bot.

Every update flows through the dispatcher middleware and bumps a per-user
record: first/last seen, message counts, which commands they used, UI language
guess, and daily active counts. Stored atomically in data/analytics.json and
picked up by gist_sync (so the owner can read it from anywhere).
"""
import datetime
import json
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FILE = BASE_DIR / 'data' / 'analytics.json'
_lock = threading.Lock()
DATA = None


def _load():
    global DATA
    if DATA is None:
        if FILE.exists():
            try:
                DATA = json.loads(FILE.read_text(encoding='utf-8'))
            except Exception:
                DATA = {}
        else:
            DATA = {}
        DATA.setdefault('users', {})
        DATA.setdefault('days', {})
        DATA.setdefault('totals', {'updates': 0, 'users_ever': 0})


def _save():
    tmp = FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(DATA, ensure_ascii=False), encoding='utf-8')
    tmp.replace(FILE)


def _detect_lang(text: str) -> str:
    if not text:
        return 'en'
    persian = sum(1 for ch in text if '؀' <= ch <= 'ۿ')
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return 'fa' if persian > latin else 'en'


def _command_of(text: str) -> str:
    if not text or not text.startswith('/'):
        return ''
    return text.split()[0].split('@')[0].lower()


def record(user, kind: str, text: str = ''):
    """Record one interaction. `kind`: message | callback | command."""
    if not user or user.is_bot:
        return
    _load()
    now = int(datetime.datetime.now().timestamp())
    day = datetime.datetime.now().strftime('%Y-%m-%d')
    uid = str(user.id)
    with _lock:
        u = DATA['users'].get(uid)
        if not u:
            u = {'first': now, 'msgs': 0, 'commands': 0, 'callbacks': 0,
                 'commands_used': {}, 'lang': 'en'}
            DATA['users'][uid] = u
            DATA['totals']['users_ever'] += 1
        u['last'] = now
        u['name'] = user.full_name or ''
        if getattr(user, 'username', None):
            u['username'] = '@' + user.username
        u['msgs' if kind == 'message' else 'callbacks'] += 1
        cmd = _command_of(text)
        if cmd:
            u['commands'] += 1
            u['commands_used'][cmd] = u['commands_used'].get(cmd, 0) + 1
            u['last_cmd'] = cmd
        elif kind == 'message' and text:
            u['lang'] = _detect_lang(text)
        d = DATA['days'].setdefault(day, {'unique': 0, 'updates': 0})
        if str(uid) not in d.get('seen', []):
            d.setdefault('seen', []).append(uid)
            d['unique'] = len(d['seen'])
        d['updates'] += 1
        DATA['totals']['updates'] += 1
        # trim: keep only last 30 days of daily data
        if len(DATA['days']) > 30:
            for k in sorted(DATA['days'])[:-30]:
                del DATA['days'][k]
        _save()


def summary() -> str:
    """One-paragraph analytics summary for the /ownerstats command."""
    _load()
    now = int(datetime.datetime.now().timestamp())
    week = now - 7 * 86400
    users = DATA['users']
    active7 = [u for u in users.values() if u['last'] >= week]
    fa = sum(1 for u in users.values() if u.get('lang') == 'fa')
    cmds = {}
    for u in users.values():
        for c, n in u.get('commands_used', {}).items():
            cmds[c] = cmds.get(c, 0) + n
    top = sorted(cmds.items(), key=lambda x: -x[1])[:5]
    lines = [f'👥 Total users ever: <b>{len(users)}</b> · active last 7d: <b>{len(active7)}</b>',
             f'🌐 Language: {len(users) - fa} EN · {fa} FA',
             '🔥 Top commands: ' + (', '.join(f'{c}×{n}' for c, n in top) or '—')]
    daily = sorted(DATA['days'].items())[-5:]
    lines.append('📅 Last days: ' + ' · '.join(f"{k[5:]}:{v['unique']}" for k, v in daily) if (daily := daily) else '')
    return '\n'.join(lines)


def start_middleware(dp):
    """Wire into aiogram dispatcher — call once at import."""

    class _Recorder:
        async def __call__(self, handler, event, data):
            try:
                if getattr(event, 'message', None):
                    record(event.message.from_user, 'message',
                           event.message.text or '')
                elif getattr(event, 'from_user', None):
                    record(event.from_user, 'callback')
            except Exception:
                pass
            return await handler(event, data)

    dp.message.middleware(_Recorder())
    dp.callback_query.middleware(_Recorder())
    print('analytics: recording user interactions', flush=True)