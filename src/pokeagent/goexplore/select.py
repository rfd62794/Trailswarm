"""Go-Explore cell selection (plan D3): ``w(c) = progress(c) * rarity(c)``, sampled by a seeded rng.

``on_route`` (cids on the route to the current stage goal) is supplied by the caller - there is no
planner here. ``choose`` never mutates the archive and never touches the global ``random`` module:
the caller passes ``random.Random(base_seed)`` and does ``archive.mark_seen`` itself.
"""
from __future__ import annotations

import math
import random

from pokeagent.goexplore.archive import Archive, Entry


def rarity(n_seen: int) -> float:
    """Same shape as novelty/tracker.py: 1 for a never-chosen cell, falling as 1/sqrt(n_seen + 1)."""
    return 1.0 / math.sqrt(n_seen + 1)


def progress(e: Entry, on_route: bool = False) -> float:
    """1 + goals + novelty capped at 5.0 (a flag burst cannot dominate) + 1.0 while on the route."""
    return 1 + e.goals + min(5.0, e.novelty) + (1.0 if on_route else 0.0)


def weight(e: Entry, on_route: bool = False) -> float:
    return progress(e, on_route) * rarity(e.n_seen)


def choose(archive: Archive, rng: random.Random, on_route: frozenset[str] = frozenset()) -> str | None:
    """Weighted draw over the archive, deterministic for a seeded ``rng``; None when empty."""
    if not archive.entries:
        return None
    cids = sorted(archive.entries)
    weights = [weight(archive.entries[c], c in on_route) for c in cids]
    r = rng.random() * sum(weights)
    acc = 0.0
    for cid, w in zip(cids, weights):
        acc += w
        if acc > r:
            return cid
    return cids[-1]           # only float rounding can land here
