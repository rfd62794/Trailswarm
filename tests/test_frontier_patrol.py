"""Frontier fallback with nothing left to explore (run explore-20261107-191457-26240: ~17,000 steps of UP/DOWN
dithering in the Cerulean Gym corridor, 50-75% of presses flagged reversal). SYNTHETIC fixtures: a fully explored
1-wide corridor with near-equal visit counts, replayed through the real explore pick and the real loop veto."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import frontier
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.behaviours.frontier import TABU_LEN, _memory_step
from pokeagent.explorer.loop_memory import LOOP_NO_PROGRESS_N
from pokeagent.explorer import loop_veto
from pokeagent.explorer.memory import MapMemory

MAP, X, TOP, BOT = 65, 9, 1, 12
# column-9 visit counts of the Cerulean Gym corridor, read from the run's maps.json (uneven by +-35)
COUNTS = {1: 797, 2: 733, 3: 803, 4: 754, 5: 787, 6: 748, 7: 779, 8: 758, 9: 772, 10: 762, 11: 757, 12: 766}
STEP = {"UP": (0, -1), "DOWN": (0, 1)}


def corridor(tmp_path) -> MapMemory:
    """Column x=9, y=1..12: every tile visited ~750x, walls both sides, closed at both ends: no frontier anywhere."""
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(MAP)
    for y in range(TOP, BOT + 1):
        d["visited"][f"{X},{y}"] = COUNTS[y]
        d["blocked"] += [f"{X},{y},LEFT", f"{X},{y},RIGHT"]
    d["blocked"] += [f"{X},{TOP},UP", f"{X},{BOT},DOWN"]
    mem.recent_talk |= {f"{X},{TOP},UP", f"{X},{BOT},DOWN"}  # the wall ends were already probed with A
    return mem


def walk(mem, steps, start_y=6):
    """Drive the real _memory_step; apply its press to a tiny world, update visits/momentum like press_track."""
    ctx = SimpleNamespace(mem=mem, facing="DOWN", view=SimpleNamespace(tm=None), emu=SimpleNamespace(read=lambda a: 0),
                          last_dir=None, recent_tiles={}, frontier_target=None, frontier_route=[], frontier_at=None,
                          last_press=None, novelty=None)
    y, trail = start_y, []
    for _ in range(steps):
        name, _why = _memory_step(ctx, MAP, X, y)
        ctx.last_press = name
        trail.append((y, name))
        if name in STEP and f"{X},{y},{name}" not in mem.m(MAP)["blocked"]:
            y += STEP[name][1]
            ctx.last_dir = name
            ctx.facing = name
            mem.m(MAP)["visited"][f"{X},{y}"] += 1
            stood = ctx.recent_tiles.setdefault(MAP, [])
            stood.append((X, y))
            del stood[:-TABU_LEN]
    return trail


def reversals(trail):
    return sum(1 for (_, a), (_, b) in zip(trail, trail[1:]) if {a, b} == {"UP", "DOWN"})


def test_no_frontier_patrol_does_not_dither(tmp_path):
    trail = walk(corridor(tmp_path), 120)
    # a patrol turns around only at the two dead ends: at most one reversal per corridor traverse (10 tiles)
    assert reversals(trail) <= 120 // (BOT - TOP) + 2, [b[0] for b in trail[:40]]


def test_synthetic_replay_veto_exhausts_on_the_dither(tmp_path):
    """The UP/DOWN pair repeats every other step, so the ledger DOES reach LOOP_NO_PROGRESS_N - but frontier is the
    last behaviour, so the re-choose finds no alternative and the press goes through (veto_exhausted)."""
    ctx = SimpleNamespace(step=0, facing="UP", run_dir=tmp_path, mem=SimpleNamespace(data={}), loops=None, logs=[],
                          view=SimpleNamespace(m=MAP, x=X, y=0, lines=[], battling=False))
    ctx.log = lambda text, tag=None: ctx.logs.append(text)

    class OnlyFrontier:
        def choose(self, c, skip=frozenset()):
            return None if "frontier" in skip else Decision("UP", "frontier", "x", behaviour="frontier")

    pressed = []
    for i in range(12):  # (9,3) UP / (9,2) DOWN ... exactly the alternation in the run
        ctx.step, ctx.view.y, ctx.facing = i, (3 if i % 2 == 0 else 2), ("DOWN" if i % 2 == 0 else "UP")
        button = "UP" if i % 2 == 0 else "DOWN"
        dec = loop_veto.check(ctx, OnlyFrontier(), Decision(button, "frontier", "x", behaviour="frontier"))
        pressed.append(dec.button)
        loop_veto.record(ctx, dec, [])  # moved onto an already-visited tile: no progress reasons
    assert pressed == ["UP", "DOWN"] * 6  # never altered
    kinds = [r["kind"] for r in map(__import__("json").loads, (tmp_path / "loops.jsonl").read_text().splitlines())]
    assert kinds and set(kinds) == {"veto_exhausted"} and LOOP_NO_PROGRESS_N == 3
