"""Training v2 slice 4 (2026-11-13 A/B after slice 3): Cerulean's north edge (20,0)<->(20,1) ping-pong. ROM-free."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer import edge_hold

CERULEAN, R24 = 0x03, 0x23


def _maps(extra_crossing: bool = False):
    visited = {f"{x},{y}": 3 for x in (20, 21) for y in range(0, 8)}
    warps = {"20,0,UP": [R24, 10, 35]}
    if extra_crossing:
        warps["21,0,UP"] = [R24, 11, 35]
    return {str(CERULEAN): {"visited": visited, "blocked": [], "warps": warps},
            str(R24): {"visited": {"10,35": 1, "10,34": 1}, "blocked": [], "warps": {}, "encounters": {"10,34": 1}}}


def _ctx():
    return SimpleNamespace(mem=SimpleNamespace(temp_blocked={}), frame=0, log=lambda *a, **k: None)


def _walk(maps, steps, crossing_open_at=None):
    """Replay: the crossing press never changes the map; when train_route has no plan the 'frontier' pulls DOWN
    (the A/B trace), otherwise the plan's press is taken. Returns the sequence of (position, source)."""
    ctx, pos, seq, stuck = _ctx(), (CERULEAN, 20, 1), [], 0
    for i in range(steps):
        ctx.frame = i * 10
        ctx.mem.temp_blocked = {k: v for k, v in ctx.mem.temp_blocked.items() if v > ctx.frame}
        r = edge_hold.step(ctx, maps, pos, 30, 30, survives=True)
        if r is None:
            btn, src = "DOWN", "frontier"
        else:
            btn, src = r[0], "plan"
        stuck = stuck + 1 if (btn == "UP" and pos[2] == 0) else 0
        if stuck > 3:                                            # the loop veto: a 3x no-progress press hands the step to frontier
            btn, src, stuck = "DOWN", "frontier", 0
        seq.append((pos, btn, src))
        if crossing_open_at is not None and i >= crossing_open_at and (pos[1:], btn) == ((20, 0), "UP"):
            return seq, True
        if btn == "UP" and pos[2] > 0:
            pos = (CERULEAN, pos[1], pos[2] - 1)
        elif btn == "DOWN" and pos[2] < 7:
            pos = (CERULEAN, pos[1], pos[2] + 1)
        # UP at (20,0): the crossing fails, the position is unchanged
    return seq, False


def test_failed_crossing_is_held_not_pingponged():
    seq, _ = _walk(_maps(), 40)
    tries = [s for s in seq if s[0][1:] == (20, 0) and s[1] == "UP"]
    assert 1 <= len(tries) <= edge_hold.FAILS_TO_BLOCK + 1       # the dead press is tried twice, then held (not every other step)
    flips = sum(1 for a, b, c in zip(seq, seq[1:], seq[2:]) if a[0] == c[0] != b[0] and a[2] != b[2])
    assert flips == 0                                            # no plan/frontier alternation (the 2-cycle)


def test_hold_expires_and_the_crossing_is_retried():
    seq, _ = _walk(_maps(), 200)
    tries = [i for i, s in enumerate(seq) if s[0][1:] == (20, 0) and s[1] == "UP"]
    assert any(b - a > 30 for a, b in zip(tries, tries[1:]))     # retried only after the hold (600 frames = 60 steps), not every step


def test_another_crossing_is_taken_when_one_is_known():
    ctx, maps = _ctx(), _maps(extra_crossing=True)
    ctx.mem.temp_blocked[(CERULEAN, 20, 0)] = 10 ** 9
    r = edge_hold.step(ctx, maps, (CERULEAN, 20, 1), 30, 30, survives=True)
    assert r is not None and r[0] == "RIGHT"                     # sidestep to (21,1), then UP through the free crossing


def test_working_crossing_is_never_held():
    ctx, maps = _ctx(), _maps()
    pos = (CERULEAN, 20, 0)
    for _ in range(5):
        r = edge_hold.step(ctx, maps, pos, 30, 30, survives=True)
        assert r[0] == "UP"
        pos = (R24, 10, 35)                                      # the press changed the map
        edge_hold.note(ctx, pos)
        pos = (CERULEAN, 20, 0)
    assert not ctx.mem.temp_blocked
