"""Seeded synthetic NPC tracks for the movement pipeline and the blocked-corridor fixture."""
from __future__ import annotations

import random

from pokeagent.vision_motion.tracks import make_track

STAY, WALK = 0xFF, 0xFE


def rng(seed: int, salt: int = 0) -> random.Random:
    return random.Random(f"{seed}:{salt}")


def stationary(n: int, at=(5, 5)) -> list:
    """A track that never leaves its tile; move byte 0xFF on every row."""
    return make_track([tuple(at)] * n, move=STAY)


def wandering(n: int, seed: int = 0, at=(5, 5), step_dwell: int = 2) -> list:
    """A random walk stepping one tile every ``step_dwell`` samples; move byte 0xFE."""
    r = rng(seed, 11)
    pos = []
    x, y = at
    while len(pos) < n:
        dx, dy = r.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        x, y = x + dx, y + dy
        pos += [(x, y)] * step_dwell
    return make_track(pos[:n], move=WALK)


def patrol(n: int, length: int, axis: str = "x", seed: int = 0, pause: int = 0,
           at=(3, 3), step_dwell: int = 2) -> list:
    """Ping-pong along ``length`` tiles on ``axis`` (``"x"`` or ``"y"``), one tile per
    ``step_dwell`` samples, ``pause`` extra samples parked at each corridor end."""
    r = rng(seed, 22)
    d = r.choice((1, -1))
    i = 0 if d == 1 else length - 1
    pos = []
    while len(pos) < n:
        p = (at[0] + i, at[1]) if axis == "x" else (at[0], at[1] + i)
        pos += [p] * (step_dwell + (pause if i in (0, length - 1) else 0))
        i += d
        if i < 0 or i >= length:
            d = -d
            i += 2 * d
    return make_track(pos[:n], move=WALK)


def patrol_blocked(n: int, length: int, axis: str = "x", block_at: int = 30,
                   seed: int = 0) -> list:
    """A patrol that, from sample ``block_at``, stops permanently at the tile it already
    occupied - the corridor is blocked. The move byte stays 0xFE: the NPC is still a
    walker, it just cannot move."""
    track = patrol(n, length, axis, seed)
    pos = [(r["x"], r["y"]) for r in track]
    pos[block_at:] = [pos[block_at - 1]] * (n - block_at)
    return make_track(pos, move=WALK)


def dataset(seed: int = 0, areas: int = 6, per_area=(3, 3, 3)) -> dict:
    """``{(run, area, ident): track}``: ``per_area`` counts of (stationary, wandering,
    patrolling) tracks in each of ``areas`` synthetic maps."""
    r = rng(seed, 33)
    out = {}
    for a in range(areas):
        area, k = f"map-{a}", 0
        for maker in (stationary, wandering, patrol):
            for _ in range(per_area[(stationary, wandering, patrol).index(maker)]):
                n = r.randint(30, 70)
                if maker is patrol:
                    t = maker(n, r.randint(4, 7), r.choice("xy"), r.randrange(10 ** 9))
                else:
                    t = maker(n, seed=r.randrange(10 ** 9)) if maker is wandering else maker(n)
                out[("syn", area, f"slot{k}")] = t
                k += 1
    return out


def to_rows(track_map: dict, run: str = "syn", area: str = "map-1") -> list:
    """Emit rows in the ``iter_positions`` shape for ``{ident: track}`` tracks that share
    one run and area."""
    n = max((len(t) for t in track_map.values()), default=0)
    rows = []
    for i in range(n):
        ents = [[ident, t[i]["label"], t[i]["x"], t[i]["y"], t[i]["move"]]
                for ident, t in sorted(track_map.items()) if i < len(t)]
        rows.append({"f": i * 8, "run": run, "area": area, "player": [0, 0], "ents": ents})
    return rows
