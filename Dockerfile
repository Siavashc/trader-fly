# Trader Fly — one container = Telegram bot (long polling) + FastAPI mini app
# + engine loop. Brain (brian2 connectome) is vendored in ./brain.
FROM python:3.11-slim

ENV PYTHONUTF8=1 \
    BRIAN2_TARGET=numpy \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY trader.py trader_cycle.py bot.py webapp.py ./
COPY web ./web
COPY brain ./brain

# seed the fly's current state (paper ledger + brain memory) so a fresh
# volume boots with its history; entrypoint copies it in only if empty
COPY seed /app/seed

CMD ["sh", "-c", "mkdir -p data user_states && \
     { [ -f data/trader.json ] || cp seed/data/* data/ 2>/dev/null; } && \
     { [ -f user_states/trader_brain.json ] || cp seed/user_states/* user_states/ 2>/dev/null; } && \
     exec python -X utf8 bot.py"]