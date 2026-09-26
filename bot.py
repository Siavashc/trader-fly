#!/usr/bin/env python3
"""
bot.py — Trader Fly Telegram bot (single process = bot + web app + engine).

- /start        intro + "Open Trading Desk" Mini App button + alerts toggle
- /status       live price, open position, total P&L, W/L
- /position     open position detail with live uPnL
- /history      last trades with inline sort buttons (time / amount)
- Trade alerts  on every open/close, to subscribers (🔔 button)

Run:  D:\\telegram_games\\fly-brain-bot\\.venv\\Scripts\\python.exe bot.py
"""
import asyncio
import datetime
import json
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, WebAppInfo)
from aiogram.enums import ParseMode

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / '.env')

BOT_TOKEN = os.environ['BOT_TOKEN']
BASE_URL = os.environ.get('BASE_URL', '').rstrip('/')
PORT = int(os.environ.get('PORT', '8791'))
HOST = os.environ.get('HOST', '127.0.0.1')   # 0.0.0.0 inside a container

import trader
import gist_sync

SUBS_FILE = BASE_DIR / 'data' / 'subscribers.json'


def load_subs() -> set:
    if SUBS_FILE.exists():
        try:
            return set(json.loads(SUBS_FILE.read_text(encoding='utf-8')))
        except Exception:
            pass
    return set()


def save_subs(subs: set):
    tmp = SUBS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(sorted(subs)), encoding='utf-8')
    tmp.replace(SUBS_FILE)


BOT: Bot = None  # set in main()


# ---------------------------------------------------------------------------
# keyboards & texts
# ---------------------------------------------------------------------------

def main_kb():
    rows = []
    if BASE_URL:
        rows.append([InlineKeyboardButton(
            text='🏢 Open Trading Desk', web_app=WebAppInfo(url=BASE_URL))])
    rows.append([
        InlineKeyboardButton(text='📊 Status', callback_data='show:status'),
        InlineKeyboardButton(text='📜 History', callback_data='show:history')])
    rows.append([InlineKeyboardButton(text='🔔 Trade Alerts', callback_data='alerts')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sort_kb():
    def b(label, s):
        return InlineKeyboardButton(text=label, callback_data=f'hist:{s}')
    return InlineKeyboardMarkup(inline_keyboard=[[
        b('🆕 Newest', 'time_desc'), b('🕰 Oldest', 'time_asc')],
        [b('🏆 Biggest Win', 'pnl_desc'), b('💀 Biggest Loss', 'pnl_asc')]])


def fmt_trade(t: dict) -> str:
    dt = datetime.datetime.fromtimestamp(t['t_close']).strftime('%m-%d %H:%M')
    dur = max(0, t['t_close'] - t.get('t_open', t['t_close']))
    mins = dur // 60
    hold = f'{mins}m' if mins < 60 else f'{mins // 60}h{mins % 60:02d}m'
    emoji = '✅' if t['pnl'] >= 0 else '🔻'
    return (f'{emoji} <b>{t["side"]}</b> {t["entry"]:,.0f}→{t["exit"]:,.0f}  '
            f'<b>${t["pnl"]:+.2f}</b>\n   <i>{dt} · {hold} · {t.get("why", "")[:40]}</i>')


def status_text() -> str:
    snap = trader.snapshot()
    st = snap['state']
    pos = st['position']
    emoji = '📈' if st['pnl_total'] >= 0 else '📉'
    feed = '🟢 live feed' if snap.get('last_fetch_ok') and \
        snap['now'] - snap['last_fetch_ok'] < 600 else '🟡 synthetic feed'
    txt = (f'🪰 <b>Trader Fly</b> — BTC-USD {feed}\n'
           f'💵 Price: <b>${snap["price"]:,.0f}</b>\n'
           f'{emoji} Total P&L: <b>${st["pnl_total"]:+.2f}</b>  '
           f'({st["wins"]}W / {st["losses"]}L)\n'
           f'💼 Equity: <b>${st["equity_start"] + st["pnl_total"]:,.2f}</b>')
    if pos and snap['price'] > 0:
        move = (snap['price'] / pos['entry'] - 1) * 100 * \
            (1 if pos['side'] == 'LONG' else -1)
        upnl = pos['notional'] * move / 100
        txt += (f'\n\n🔓 Open: <b>{pos["side"]}</b> ${pos["notional"]:.0f} '
                f'@ ${pos["entry"]:,.0f}  '
                f'(<b>${upnl:+.2f}</b> {move:+.2f}%)')
    else:
        txt += '\n🔓 No open position — fly is watching the chart.'
    notes = st.get('brain_notes', [])[-3:]
    if notes:
        txt += '\n\n🧠 Recent brain states:'
        for n in notes:
            ts = datetime.datetime.fromtimestamp(n['t']).strftime('%H:%M')
            txt += (f'\n  • {ts} ${n["price"]:,.0f} → {n["stim"]} → '
                    f'<b>{n["action"]}</b> ({n["why"][:36]})')
    return txt


def history_text(sort: str, limit: int = 10) -> str:
    trades = trader.history(sort)[:limit]
    if not trades:
        return '📜 No closed trades yet — the fly is still warming up.'
    total = round(sum(t['pnl'] for t in trader.STATE['trades']), 2)
    head = '📜 <b>Trade history</b> '
    heads = {'time_desc': '(newest first)', 'time_asc': '(oldest first)',
             'pnl_desc': '(biggest wins)', 'pnl_asc': '(biggest losses)'}
    body = '\n'.join(fmt_trade(t) for t in trades)
    return f'{head}{heads[sort]}\n{body}\n\n💼 Total: <b>${total:+.2f}</b>'


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(msg: Message):
    await msg.reply(
        '🪰 <b>Welcome to the Trader Fly</b>\n\n'
        'This is not a trading bot. It is a <b>real fruit-fly brain</b> — all '
        '<b>138,639 neurons</b> of the actual FlyWire connectome, running on a '
        'little laptop, staring at the Bitcoin chart from a tiny apartment desk.\n\n'
        '<b>How the market talks to it:</b>\n'
        '📈 Rally → it <i>tastes something sweet</i>\n'
        '📉 Dump → it <i>smells danger</i>\n'
        '😐 Sideways → it just <i>hears a buzzing sound</i>\n\n'
        'Its brain reacts, and its behavior <i>is</i> the trade:\n'
        'walks toward the food → <b>BUY</b> 🟢\n'
        'bolts the other way → <b>SELL</b> 🔴\n'
        'ignores everything → <b>HOLD</b> 😴\n\n'
        'Every profit = a <b>dopamine reward</b>. Every loss = a zap. '
        'Its brain <b>genuinely learns</b> from trading — check its mood below.\n\n'
        '💼 Paper account: $1,000 · SL −0.35% · TP +0.7%\n'
        '🏢 Tap <b>Open Trading Desk</b> to sit with it live — cozy room, '
        'day/night sky, candle monitor, full ledger.\n\n'
        '<code>/status</code> portfolio · <code>/position</code> open trade · '
        '<code>/history</code> ledger · <code>/close</code> exit now · 🔔 alerts on every trade',
        reply_markup=main_kb())


@dp.message(Command('status'))
async def cmd_status(msg: Message):
    await msg.reply(status_text(), parse_mode=ParseMode.HTML, reply_markup=main_kb())


@dp.message(Command('position'))
async def cmd_position(msg: Message):
    snap = trader.snapshot()
    pos = snap['state']['position']
    if not pos:
        await msg.reply('🔓 No open position. The fly is sipping coffee and watching.')
        return
    move = (snap['price'] / pos['entry'] - 1) * 100 * (1 if pos['side'] == 'LONG' else -1)
    upnl = pos['notional'] * move / 100
    await msg.reply(
        f'🔓 <b>{pos["side"]}</b> ${pos["notional"]:.0f}\n'
        f'Entry ${pos["entry"]:,.0f} → now ${snap["price"]:,.0f}\n'
        f'uPnL <b>${upnl:+.2f}</b> ({move:+.2f}%)\n'
        f'Stop -0.35% · Take-profit +0.7%\n'
        f'Opened {datetime.datetime.fromtimestamp(pos["t_open"]).strftime("%H:%M")}',
        parse_mode=ParseMode.HTML)


@dp.message(Command('close'))
async def cmd_close(msg: Message):
    if not trader.STATE['position']:
        await msg.reply('🔓 No open position — nothing to close.')
        return
    trader.request_close()
    await msg.reply('🪰 Closing the position at the next tick (≤5s)…')


@dp.message(Command('history'))
async def cmd_history(msg: Message):
    await msg.reply(history_text('time_desc'), parse_mode=ParseMode.HTML,
                    reply_markup=sort_kb())


@dp.callback_query(F.data.startswith('hist:'))
async def cb_hist(cq: CallbackQuery):
    await cq.message.edit_text(history_text(cq.data.split(':', 1)[1]),
                               parse_mode=ParseMode.HTML, reply_markup=sort_kb())
    try:
        await cq.answer()
    except Exception:
        pass


@dp.callback_query(F.data.startswith('show:'))
async def cb_show(cq: CallbackQuery):
    what = cq.data.split(':', 1)[1]
    if what == 'status':
        await cq.message.reply(status_text(), parse_mode=ParseMode.HTML,
                               reply_markup=main_kb())
    else:
        await cq.message.reply(history_text('time_desc'), parse_mode=ParseMode.HTML,
                               reply_markup=sort_kb())
    try:
        await cq.answer()
    except Exception:
        pass


@dp.callback_query(F.data == 'alerts')
async def cb_alerts(cq: CallbackQuery):
    subs = load_subs()
    uid = cq.from_user.id
    if uid in subs:
        subs.remove(uid)
        text = '🔕 Alerts OFF — you will not get trade notifications.'
    else:
        subs.add(uid)
        text = '🔔 Alerts ON — the fly will ping you on every open & close!'
    save_subs(subs)
    await cq.message.reply(text, reply_markup=main_kb())
    try:
        await cq.answer()
    except Exception:
        pass


@dp.message(F.text)
async def on_text(msg: Message):
    t = (msg.text or '').strip().lower()
    if not t or t.startswith('/'):
        return
    if any(k in t for k in ('profit', 'loss', 'pnl', 'status', 'وضعیت', 'سود')):
        await cmd_status(msg)
    elif any(k in t for k in ('history', 'trades', 'تاریخچه')):
        await cmd_history(msg)
    else:
        await msg.reply(
            '🪰 The fly is busy staring at candles.\nTry /status, /position, '
            '/history — or open the 🏢 Trading Desk.', reply_markup=main_kb())


# ---------------------------------------------------------------------------
# trade notifications
# ---------------------------------------------------------------------------

async def notify(ev: dict):
    subs = load_subs()
    if not subs:
        return
    if ev['type'] == 'open':
        side = '🟢 LONG' if ev['side'] == 'LONG' else '🔴 SHORT'
        text = (f'🪰 <b>Trade opened!</b> {side} ${trader.NOTIONAL_USD:.0f} '
                f'@ ${ev["entry"]:,.0f}\n<i>{ev["why"]}</i>')
    else:
        t = ev['trade']
        text = (f'🪰 <b>Trade closed:</b> {t["side"]} ${t["pnl"]:+.2f}\n'
                f'{t["entry"]:,.0f} → {t["exit"]:,.0f} · '
                f'{"✅ dopamine reward" if t["pnl"] >= 0 else "🔻 dopamine punishment"}\n'
                f'💼 Total: <b>${trader.STATE["pnl_total"]:+.2f}</b>'
                + (f'\n\n🏢 <a href="{BASE_URL}">Watch the desk</a>' if BASE_URL else ''))
    for uid in subs:
        try:
            await BOT.send_message(uid, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# main: uvicorn in a thread + engine task + polling
# ---------------------------------------------------------------------------

def run_webapp():
    import uvicorn
    from webapp import app
    uvicorn.run(app, host=HOST, port=PORT, log_level='warning')


async def main():
    global BOT
    BOT = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    import threading
    threading.Thread(target=run_webapp, daemon=True).start()
    engine = asyncio.create_task(trader.engine_loop(notify_cb=notify))
    gist_sync.start()
    print(f'🪰 Trader Fly online. Mini app: {BASE_URL or "(no BASE_URL)"} '
          f'http://127.0.0.1:{PORT}', flush=True)
    try:
        await dp.start_polling(BOT)
    finally:
        engine.cancel()


if __name__ == '__main__':
    asyncio.run(main())