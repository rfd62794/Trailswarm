"""Blocked-corridor detection: the model expects the NPC to move, and it does not."""
from __future__ import annotations

from statistics import median

from pokeagent.vision_motion import synthetic
from pokeagent.vision_motion.nextpos import CountTable, context, iter_steps


def flag_blocked(track, model, window: int = 6, min_expected_move: float = 0.5) -> int | None:
    """The first index ending a ``window``-long run of same-tile samples over which the
    model's mean ``P(next != stay)`` (given the track so far) is >= ``min_expected_move``;
    ``None`` when it never flags."""
    for i in range(window - 1, len(track)):
        seg = track[i - window + 1: i + 1]
        if len({(r["x"], r["y"]) for r in seg}) != 1:
            continue
        probs = [model.prob_nonstay(context(track, t))
                 for t in range(i - window + 1, i + 1)]
        if sum(probs) / window >= min_expected_move:
            return i
    return None


def blocked_report(seed: int = 0, n: int = 100, window: int = 6,
                   min_expected_move: float = 0.5, block_at: int = 30) -> dict:
    """The ``blocked_corridor`` report block: the count-table model is fitted on a separate
    set of synthetic patrol/wander/stationary tracks, then scored on ``n`` fresh seeded
    tracks of each kind."""
    rng = synthetic.rng(seed, salt=0xB1)
    train = [synthetic.patrol(70, rng.randint(4, 7), rng.choice("xy"), rng.randrange(10 ** 9))
             for _ in range(30)]
    train += [synthetic.wandering(70, rng.randrange(10 ** 9)) for _ in range(30)]
    train += [synthetic.stationary(70) for _ in range(30)]
    model = CountTable().fit(s for t in train for s in iter_steps(t))
    sets = {
        "blocked": [synthetic.patrol_blocked(70, 6, "x", block_at, rng.randrange(10 ** 9))
                    for _ in range(n)],
        "patrol": [synthetic.patrol(70, 6, "x", rng.randrange(10 ** 9)) for _ in range(n)],
        "paused": [synthetic.patrol(70, 6, "x", rng.randrange(10 ** 9), pause=2)
                   for _ in range(n)],
        "stationary": [synthetic.stationary(70) for _ in range(n)],
        "wandering": [synthetic.wandering(70, rng.randrange(10 ** 9)) for _ in range(n)],
    }
    flags = {k: [flag_blocked(t, model, window, min_expected_move) for t in ts]
             for k, ts in sets.items()}
    delays = [f - block_at for f in flags["blocked"] if f is not None]
    return {
        "window": window, "min_expected_move": min_expected_move, "n": n,
        "detection_rate": sum(f is not None for f in flags["blocked"]) / n,
        "median_delay": median(delays) if delays else None,
        "false_positive_rate": {k: sum(f is not None for f in flags[k]) / n
                                for k in ("patrol", "paused", "stationary", "wandering")},
    }
