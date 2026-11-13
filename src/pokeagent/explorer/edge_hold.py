"""edge_hold: one plan at a map edge (2026-11-13 A/B after slice 3: Cerulean (20,0) <-> (20,1) ping-pong, 39 loop detections).

train_route proposes the Route 24 crossing "UP at (20,0)" every step. When that press does not change the map (a trainer or NPC
on the far tile, a mid-transition read) the loop veto kills the proposal at (20,0) and frontier takes over and walks away
(DOWN, "14 steps to (23,9)"); one tile later train_route proposes the crossing again - the two rules alternate every step.

This wraps train_route.step: a crossing press that twice failed to leave the map temp-blocks the edge tile for HOLD_FRAMES (the same
mem.temp_blocked the wanderer-NPC wait uses, routing only, never saved). While it holds, train_route answers with a different
crossing if the learned graph has one, or None (one owner: frontier) - never the dead press - and when the block expires the
crossing is tried again once.
"""
from __future__ import annotations

from pokeagent.explorer import train_route

FAILS_TO_BLOCK = 2     # consecutive no-map-change presses of the same crossing before it is held
HOLD_FRAMES = 600      # frames the edge tile stays temp-blocked (anomalies.TEMP_BLOCK_FRAMES is 300 for a wanderer)


def _state(ctx) -> dict:
    return ctx.__dict__.setdefault("edge_hold", {"last": None, "fails": 0})


def _crossing(maps: dict, pos: tuple, button: str) -> bool:
    return f"{pos[1]},{pos[2]},{button}" in (maps.get(str(pos[0])) or {}).get("warps", {})


def note(ctx, pos: tuple) -> None:
    """Called at the top of each routed step with where we stand now: judge the previous crossing press."""
    st = _state(ctx)
    last, st["last"] = st["last"], None
    if last is None:
        return
    if last[0] != pos:   # moved (map change or a step back): the crossing is not stuck
        st["fails"] = 0
        return
    st["fails"] += 1
    if st["fails"] >= FAILS_TO_BLOCK:
        ctx.mem.temp_blocked[pos] = ctx.frame + HOLD_FRAMES
        st["fails"] = 0
        ctx.log(f"[edge_hold: crossing {last[1]} at map 0x{pos[0]:02X} ({pos[1]},{pos[2]}) failed x{FAILS_TO_BLOCK}; "
                f"held {HOLD_FRAMES} frames, routing another way]", "res")


def step(ctx, maps: dict, pos: tuple, *args, **kw):
    """train_route.step with the crossing guard (same arguments after ``pos``; ``blocked`` is ctx.mem.temp_blocked)."""
    note(ctx, pos)
    held = pos in ctx.mem.temp_blocked
    r = None if held else train_route.step(maps, pos, ctx.mem.temp_blocked, *args, **kw)
    if r is not None and r[0] in ("UP", "DOWN", "LEFT", "RIGHT") and _crossing(maps, pos, r[0]):
        _state(ctx)["last"] = (pos, r[0])
    return r
