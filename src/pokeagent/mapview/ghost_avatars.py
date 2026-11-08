"""Which avatar picture each visible ghost head gets, grouped so the overlay stamps once per picture.

Pure numpy. Facing and walk phase are computed for every ghost in array form, then the heads are
reduced to the distinct (agent, facing, phase) triples: the avatar source is asked once per
triple, never once per ghost, and not at all while it holds no picture yet.
"""
from __future__ import annotations

import numpy as np


def _facing_phase(frame, tb, walk_frames: bool):
    gi = np.arange(len(tb.ghosts))
    pi = np.clip(frame.idx.astype(np.intp) - 1, 0, None)
    ok_prev = (frame.idx > 0) & (tb.area_idx[gi, pi] == frame.area)
    dx = np.where(ok_prev, frame.xs - tb.xs[gi, pi], 0.0)
    dy = np.where(ok_prev, frame.ys - tb.ys[gi, pi], 0.0)
    moved = (dx != 0) | (dy != 0)
    facs = np.where(dx >= 0, "RIGHT", "LEFT")
    phs = np.zeros(len(gi), np.intp)
    if walk_frames:
        facs = np.where(moved, np.where(np.abs(dx) >= np.abs(dy), facs, np.where(dy >= 0, "DOWN", "UP")), "DOWN")
        phs = np.where(moved, frame.idx // 6 % 2 + 1, 0)
    return facs, phs


def ghost_groups(avatars, frame, tb, sel, hx, hy, colors, w: int, h: int, walk_frames: bool) -> list:
    """[(picture, ghost indices)] for the heads in ``sel`` that lie inside the w x h rectangle."""
    if avatars is None or not len(sel):
        return []
    ready = getattr(avatars, "ready", None)
    if ready is not None and not ready():
        return []                                       # no picture exists yet: skip all work
    ins = sel[(hx[sel] >= 0) & (hx[sel] < w) & (hy[sel] >= 0) & (hy[sel] < h)]
    if not len(ins):
        return []
    facs, phs = _facing_phase(frame, tb, walk_frames)
    names, ai = np.unique(np.asarray(tb.agents)[ins], return_inverse=True)
    fnames, fi = np.unique(facs[ins], return_inverse=True)
    keys = np.stack([ai.ravel(), fi.ravel(), phs[ins]], axis=1)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv, out = inv.ravel(), []
    for u, (a, f, p) in enumerate(uniq):
        ks = ins[inv == u]
        img = avatars.get(str(names[a]), str(fnames[f]), int(p), tuple(int(c) for c in colors[ks[0]]))
        if img is not None:
            out.append((img, ks))
    return out
