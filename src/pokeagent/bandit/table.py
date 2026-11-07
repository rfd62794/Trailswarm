"""Posterior and Thompson choice. A cell is (context key, arm) -> [n, sum, sumsq] of episode rewards.

The prior is the Explorer's own default arm: until the default has MIN_N samples in a context the bandit answers
the default (an unvisited context behaves like the Explorer today). After that every arm gets a Gaussian posterior
on its mean reward and Thompson sampling picks; an alternative's prior mean is the default's empirical mean minus
ALT_MARGIN, so it is tried but must earn its place.
"""
from __future__ import annotations

import math
import random

MIN_N = 5            # default-arm samples a context needs before the bandit may deviate
PRIOR_N = 2.0        # pseudo-observations behind the prior mean
SIGMA0 = 1.0         # reward spread assumed until an arm has two samples
SIGMA_FLOOR = 0.25
DEFAULT_PRIOR = 0.0  # optimistic: better than any real episode reward (rewards are mostly negative)
ALT_MARGIN = 0.1

Cells = dict  # {key: {arm: [n, sum, sumsq]}}


def add_cell(cells: Cells, key: str, arm: str, n: float, s: float, ss: float) -> None:
    c = cells.setdefault(key, {}).setdefault(arm, [0, 0.0, 0.0])
    c[0] += n; c[1] += s; c[2] += ss


def absorb(cells: Cells, other: Cells) -> None:
    """Add every cell of ``other`` into ``cells`` (deltas are additive; never call twice for one delta)."""
    for key, arms in other.items():
        for arm, (n, s, ss) in arms.items():
            add_cell(cells, key, arm, n, s, ss)


def record(cells: Cells, key: str, arm: str, reward: float) -> None:
    add_cell(cells, key, arm, 1, reward, reward * reward)


def stats(cells: Cells, key: str, arm: str) -> tuple[float, float, float]:
    n, s, ss = cells.get(key, {}).get(arm, (0, 0.0, 0.0))
    return n, s, ss


def posterior(cells: Cells, key: str, arm: str, default: str) -> tuple[float, float]:
    """(mean, sd) of the belief about this arm's mean reward."""
    n, s, ss = stats(cells, key, arm)
    dn, ds, _ = stats(cells, key, default)
    if dn >= MIN_N:
        base = ds / dn
        mu0 = base if arm == default else base - ALT_MARGIN
    else:
        mu0 = DEFAULT_PRIOR if arm == default else DEFAULT_PRIOR - ALT_MARGIN
    mean = (PRIOR_N * mu0 + s) / (PRIOR_N + n)
    if n >= 2:
        sigma = max(math.sqrt(max(ss / n - (s / n) ** 2, 0.0)), SIGMA_FLOOR)
    else:
        sigma = SIGMA0
    return mean, sigma / math.sqrt(PRIOR_N + n)


def choose(cells: Cells, key: str, arms: tuple[str, ...], default: str, rng: random.Random) -> str:
    """Thompson sampling, but the default while it has fewer than MIN_N samples here."""
    if stats(cells, key, default)[0] < MIN_N:
        return default
    best, best_draw = default, -math.inf
    for arm in arms:
        mean, sd = posterior(cells, key, arm, default)
        draw = rng.gauss(mean, sd)
        if draw > best_draw:
            best, best_draw = arm, draw
    return best
