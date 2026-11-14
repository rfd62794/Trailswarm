"""Seeded weighted selection: the formulas, determinism, no mutation, rare favoured, on_route."""
from __future__ import annotations

import random

from pokeagent.goexplore import select
from pokeagent.goexplore.archive import Archive, Entry


def ent(cid, goals=0, steps=100, n_seen=0, novelty=0.0):
    return Entry(cid=cid, state=f"cells/{cid}.state", goals=goals, steps=steps,
                 n_seen=n_seen, novelty=novelty)


def arch(n):
    a = Archive()
    for i in range(n):
        a.offer(ent(f"1.0.{i}.0.0.0.0"))
    return a


def test_rarity_matches_formula():
    assert select.rarity(0) == 1.0
    assert select.rarity(3) == 0.5
    assert select.rarity(8) == 1.0 / 3.0


def test_progress_terms():
    e = ent("c", goals=2, novelty=1.5)
    assert select.progress(e) == 1 + 2 + 1.5
    assert select.progress(ent("c", novelty=99)) == 1 + 5.0     # novelty capped at 5.0
    assert select.progress(e, on_route=True) == select.progress(e) + 1.0
    assert select.weight(e) == select.progress(e) * select.rarity(0)


def test_seeded_selection_is_deterministic():
    def seq(seed):
        a = arch(20)
        rng = random.Random(seed)
        out = []
        for _ in range(50):
            c = select.choose(a, rng)
            out.append(c)
            a.mark_seen(c)
        return out
    random.seed(1)
    state0 = random.getstate()
    assert seq(7) == seq(7)
    assert seq(7) != seq(8)
    assert random.getstate() == state0          # the global random state is untouched


def test_choose_empty_is_none():
    assert select.choose(Archive(), random.Random(0)) is None


def test_choose_does_not_mutate():
    a = arch(5)
    seen0 = {c: e.n_seen for c, e in a.entries.items()}
    rng = random.Random(3)
    for _ in range(20):
        select.choose(a, rng)
    assert {c: e.n_seen for c, e in a.entries.items()} == seen0


def test_rare_cells_are_favoured():
    a = Archive()
    a.offer(ent("fresh", goals=1))
    a.offer(ent("stale", goals=1, n_seen=99))
    rng = random.Random(11)
    counts = {"fresh": 0, "stale": 0}
    for _ in range(2000):
        counts[select.choose(a, rng)] += 1
    assert counts["fresh"] > 2 * counts["stale"]


def test_on_route_boosts_weight():
    a = Archive()
    a.offer(ent("near"))
    a.offer(ent("far"))
    rng = random.Random(5)
    counts = {"near": 0, "far": 0}
    for _ in range(2000):
        counts[select.choose(a, rng, on_route=frozenset({"near"}))] += 1
    assert counts["near"] > counts["far"]
