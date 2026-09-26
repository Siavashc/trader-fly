"""Convert the 96MB connectivity parquet into a compact npz for low-RAM hosts.

Keeps every synapse with weight >= MIN_W (default 1 = every nonzero synapse),
downcasts indices to int32 and weights to float32, stores compressed.
model.py reads this instead of the parquet when it exists.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path(r'D:\telegram_games\trader-fly\brain\data')
SRC = DATA / '2025_Connectivity_783.parquet'
DST = DATA / 'connectome_compact.npz'
MIN_W = 1

df = pd.read_parquet(SRC, columns=['Presynaptic_Index', 'Postsynaptic_Index',
                                   'Excitatory x Connectivity'])
w = df['Excitatory x Connectivity'].to_numpy()
keep = w >= MIN_W
pre = df['Presynaptic_Index'].to_numpy()[keep].astype(np.int32)
post = df['Postsynaptic_Index'].to_numpy()[keep].astype(np.int32)
wt = w[keep].astype(np.float32)
np.savez_compressed(DST, pre=pre, post=post, w=wt)
print(f'kept {len(pre):,}/{len(df):,} synapses '
      f'({DST.stat().st_size / 1e6:.1f} MB compressed)')