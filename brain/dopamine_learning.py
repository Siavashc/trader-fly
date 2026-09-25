#!/usr/bin/env python3
"""
dopamine_learning.py — Dopamine-modulated learning for the fly brain.

Phase 1: Manual weight modulation with persistent memory.
- Tracks which KC were active during each stimulus
- Applies reward/punishment signals to KC→MBON synapses
- Saves modified weights across sessions ("fly memory")

Phase 2 (future): STDP + DAN gating for automatic learning.
"""

import json
import os
import numpy as np
import pandas as pd
from pathlib import Path
from copy import deepcopy

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
MEMORY_FILE = DATA_DIR / 'fly_memory.json'
MB_NEURONS_FILE = DATA_DIR / 'mushroom_body_neurons.json'


class FlyMemory:
    """Persistent memory store for the fly brain's learned associations."""

    def __init__(self):
        self.mb_data = self._load_mb_neurons()
        self.comp = pd.read_csv(DATA_DIR / '2025_Completeness_783.csv', index_col=0)
        self.flyid2i = {fid: i for i, fid in enumerate(self.comp.index)}

        # Build index sets
        self.kc_indices = self._ids_to_indices(self._all_kc_ids())
        self.mbon_indices = self._ids_to_indices(self._all_mbon_ids())
        self.pam_indices = self._ids_to_indices(self._all_pam_ids())
        self.ppl_indices = self._ids_to_indices(self._all_ppl_ids())

        # Load or init memory
        self.memory = self._load_memory()

    def _load_mb_neurons(self):
        with open(MB_NEURONS_FILE) as f:
            return json.load(f)

    def _all_kc_ids(self):
        ids = []
        for group_ids in self.mb_data['kenyon_cells'].values():
            ids.extend(group_ids)
        return ids

    def _all_mbon_ids(self):
        ids = []
        for group_ids in self.mb_data['mbon'].values():
            ids.extend(group_ids)
        return ids

    def _all_pam_ids(self):
        ids = []
        for group_ids in self.mb_data['dan_pam_reward'].values():
            ids.extend(group_ids)
        return ids

    def _all_ppl_ids(self):
        ids = []
        for group_ids in self.mb_data['dan_ppl_punishment'].values():
            ids.extend(group_ids)
        return ids

    def _ids_to_indices(self, ids):
        return set(self.flyid2i[fid] for fid in ids if fid in self.flyid2i)

    def _load_memory(self):
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE) as f:
                return json.load(f)
        return {
            'experiences': [],
            'weight_modifications': {},  # "pre_idx:post_idx" -> multiplier
            'total_experiences': 0,
        }

    def save_memory(self):
        with open(MEMORY_FILE, 'w') as f:
            json.dump(self.memory, f, indent=2, ensure_ascii=False)

    def get_active_kc(self, spk_trn):
        """Extract which KC fired during a simulation."""
        active_kc = []
        for idx, spikes in spk_trn.items():
            if idx in self.kc_indices and len(spikes) > 0:
                active_kc.append(idx)
        return active_kc

    def get_active_mbon(self, spk_trn):
        """Extract MBON activity and classify as approach/avoidance."""
        mbon_activity = {}
        for idx, spikes in spk_trn.items():
            if idx in self.mbon_indices and len(spikes) > 0:
                # Find the FlyWire ID
                i2flyid = {i: fid for fid, i in self.flyid2i.items()}
                fid = i2flyid.get(idx)
                if fid:
                    mbon_activity[idx] = {
                        'flyid': fid,
                        'spikes': len(spikes),
                    }
        return mbon_activity

    def apply_reward(self, active_kc, strength=1.5, label="reward"):
        """
        Simulate PAM dopamine release (reward).
        Strengthens KC→MBON synapses for active KC.
        Effect: fly learns to approach the associated stimulus.
        """
        return self._modulate(active_kc, strength, label, signal_type='reward')

    def apply_punishment(self, active_kc, strength=0.3, label="punishment"):
        """
        Simulate PPL1 dopamine release (punishment).
        Weakens KC→MBON synapses for active KC.
        Effect: fly learns to avoid the associated stimulus.
        """
        return self._modulate(active_kc, strength, label, signal_type='punishment')

    def _modulate(self, active_kc, strength, label, signal_type):
        """Apply weight modulation to KC→MBON synapses."""
        modified_count = 0

        for kc_idx in active_kc:
            for mbon_idx in self.mbon_indices:
                key = f"{kc_idx}:{mbon_idx}"
                current = self.memory['weight_modifications'].get(key, 1.0)

                if signal_type == 'punishment':
                    # Multiply toward 0 (weaken)
                    new_val = current * strength
                else:
                    # Multiply upward (strengthen)
                    new_val = current * strength

                # Clamp to [0.01, 10.0]
                new_val = max(0.01, min(10.0, new_val))
                self.memory['weight_modifications'][key] = round(new_val, 4)
                modified_count += 1

        # Record experience
        self.memory['experiences'].append({
            'label': label,
            'signal_type': signal_type,
            'strength': strength,
            'active_kc_count': len(active_kc),
            'synapses_modified': modified_count,
        })
        self.memory['total_experiences'] = len(self.memory['experiences'])

        self.save_memory()

        return {
            'signal_type': signal_type,
            'label': label,
            'active_kc': len(active_kc),
            'synapses_modified': modified_count,
            'total_experiences': self.memory['total_experiences'],
        }

    def get_weight_multipliers(self):
        """Return weight modifications as a dict of (pre, post) -> multiplier."""
        mods = {}
        for key, mult in self.memory['weight_modifications'].items():
            if mult != 1.0:  # Only return modified ones
                pre, post = key.split(':')
                mods[(int(pre), int(post))] = mult
        return mods

    def get_memory_summary(self):
        """Human-readable summary of fly's memories."""
        n_mods = sum(1 for v in self.memory['weight_modifications'].values() if v != 1.0)
        experiences = self.memory['experiences']

        return {
            'total_experiences': len(experiences),
            'modified_synapses': n_mods,
            'recent_experiences': experiences[-5:] if experiences else [],
        }

    def reset_memory(self):
        """Wipe the fly's memory (amnesia!)."""
        self.memory = {
            'experiences': [],
            'weight_modifications': {},
            'total_experiences': 0,
        }
        self.save_memory()
        return {'status': 'memory_reset', 'message': '果蝇的记忆已清除！（失忆了）'}


def apply_learned_weights(syn, fly_memory):
    """
    Apply learned weight modifications to a Brian2 Synapses object.
    Vectorized (sorted-merge) so hundreds of thousands of learned pairs
    apply in milliseconds instead of hours.

    Args:
        syn: Brian2 Synapses object
        fly_memory: FlyMemory instance
    Returns:
        number of synapses modified
    """
    mods = fly_memory.get_weight_multipliers()
    if not mods:
        return 0

    # Build sorted arrays of learned (pre, post) pairs and their multipliers
    mod_keys = np.array([pre * (1 << 40) + post for (pre, post) in mods],
                        dtype=np.int64)
    mod_vals = np.array(list(mods.values()), dtype=np.float64)
    order = np.argsort(mod_keys)
    mod_keys = mod_keys[order]
    mod_vals = mod_vals[order]

    # Key every existing synapse the same way
    pre_arr = np.asarray(syn.i, dtype=np.int64)
    post_arr = np.asarray(syn.j, dtype=np.int64)
    syn_keys = pre_arr.astype(np.int64) * (1 << 40) + post_arr.astype(np.int64)

    # searchsorted: position of each synapse key in the sorted mod table
    idx = np.searchsorted(mod_keys, syn_keys)
    idx_clipped = np.minimum(idx, len(mod_keys) - 1)
    hit = (mod_keys[idx_clipped] == syn_keys) & (idx < len(mod_keys))

    if hit.any():
        # Brian2's VariableView does not support boolean-mask getitem — do the
        # math on a plain numpy copy and write the full array back (with units).
        from brian2 import volt
        w_new = np.array(syn.w, dtype=np.float64, copy=True)
        w_new[hit] = w_new[hit] * mod_vals[idx_clipped[hit]]
        syn.w[:] = w_new * volt
    return int(hit.sum())
