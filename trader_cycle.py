#!/usr/bin/env python3
"""
trader_cycle.py — ONE Trader-Fly brain cycle in a fresh process (exits after).

Reuses the REAL 138,639-neuron FlyWire connectome sim from D:\\telegram_games\\fly-brain-bot
(brian2 + chat_with_fly) but keeps the Trader Fly's OWN dopamine memory file, so
it never mixes with the game flies. Exiting releases ALL Brian2 model memory —
this is what keeps the old flytrader OOM away.

Args (JSON on argv[1]):
  {"stim": "taste_sweet", "freq": 300,
   "learn": {"action": "reward", "kc": [1,2,3], "strength": 1.5, "label": "..."}}

Prints one JSON result line to stdout.
"""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
# brain modules + connectome data: vendored in ./brain (cloud), fallback to the
# original fly-brain-bot checkout (local legacy); BRAIN_DIR env wins if set
_brain_env = os.environ.get('BRAIN_DIR')
if _brain_env:
    FLYBOT = Path(_brain_env)
elif (BASE / 'brain' / 'chat_with_fly.py').exists():
    FLYBOT = BASE / 'brain'
else:
    FLYBOT = Path(r'D:\telegram_games\fly-brain-bot')
sys.path.insert(0, str(FLYBOT))
os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('BRIAN2_TARGET', 'numpy')

import brian2
brian2.prefs.codegen.target = 'numpy'
import dopamine_learning
# The Trader Fly owns its brain: point the module at OUR memory file.
dopamine_learning.MEMORY_FILE = BASE / 'user_states' / 'trader_brain.json'

args = json.loads(sys.argv[1])

# 1) apply queued dopamine (reward/punish from the last closed trade)
learned = 0
if args.get('learn'):
    L = args['learn']
    mem = dopamine_learning.FlyMemory()
    if L['action'] == 'reward':
        out = mem.apply_reward(L['kc'], strength=L.get('strength', 1.5),
                               label=L.get('label', 'trade-win'))
    else:
        out = mem.apply_punishment(L['kc'], strength=L.get('strength', 0.3),
                                   label=L.get('label', 'trade-loss'))
    learned = out.get('synapses_modified', 0)

# 2) run the brain
from chat_with_fly import run_simulation
result = run_simulation(stim_keys=[args['stim']], duration_sec=0.1,
                        freq_hz=[args['freq']], use_memory=True)

print(json.dumps({
    'learned': learned,
    'behaviors': result.get('predicted_behaviors', []),
    'kc': (result.get('mushroom_body') or {}).get('active_kc_indices', []),
    'output_neurons': {k: v.get('rate_hz', 0.0)
                       for k, v in result.get('output_neuron_activity', {}).items()},
    'wall': result.get('wall_time_sec', 0),
}))