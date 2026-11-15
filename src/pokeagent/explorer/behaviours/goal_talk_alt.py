"""goal_talk fallback: the person's usual stand tile is occupied (a beaten gym trainer parked on it) or confirmed blocked.

2026-11-15 run explore-20261115-130324-24368: a Jr. Trainer who walked to the player stayed on Misty's only stand tile (4,3) until the map
reloaded, and goal_talk pressed LEFT into her ~1,400 steps. Gen 1 lets you talk from any orthogonally adjacent walkable tile while facing
the person, so: try another adjacent tile the learned map reaches; if none, leave the map once (re-entry reloads every sprite) and retry;
after that hand back to the planner (return None). All bounded, nothing here ever presses indefinitely.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.perceive import DIRS

OPPOSITE = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
FAILS = 3          # no-move presses into a stand tile before it counts as blocked
GAP = 6            # steps without goal_talk acting after which the per-visit state is forgotten (a map change, a long dialog)
STEP_CAP = 80      # alternate-walk/exit steps per visit before giving up
REENTRIES = 1      # map exit + re-entry attempts per goal per run


def state(ctx, m: int) -> dict:
    st = ctx.__dict__.setdefault("talk_alt_state", {})
    step = getattr(ctx, "step", 0)
    gap = step - st.get("seen", step)
    if not st or st.get("m") != m or gap > GAP or (st.get("leaving") and gap > 1):  # a gap while leaving = we left and came back: fresh sprites
        st.clear()
        st.update(m=m, dead=set(), fails={}, last=None, steps=0, leaving=False)
    st["seen"] = step
    return st


def occupied(ctx, npc: tuple[int, int]) -> set[tuple[int, int]]:
    """Tiles live sprites stand on (other than the person we want), from the RAM sprite table; empty when there is no emulator."""
    emu = getattr(ctx, "emu", None)
    if emu is None:
        return set()
    try:
        from pokeagent.explorer.anomaly_sprites import read_sprites
        return {(x, y) for _, x, y in read_sprites(emu).values()} - {npc}
    except Exception:
        return set()


def observe(ctx, st: dict) -> None:
    """Our own press at a stand tile last step moved nothing: count it; FAILS of them mark that tile blocked."""
    last, v = st["last"], ctx.view
    st["last"] = None
    if last and last[0] >= getattr(ctx, "step", 0) - 2 and last[1:3] == (v.x, v.y) and not v.box:
        n = st["fails"][last[3]] = st["fails"].get(last[3], 0) + 1
        if n >= FAILS:
            st["dead"].add(last[3])


def npc_tile(sx: int, sy: int, facing: str) -> tuple[int, int]:
    dx, dy = DIRS[facing]
    return sx + dx, sy + dy


def stands(sx: int, sy: int, facing: str) -> list[tuple[int, int, str]]:
    """(x, y, facing) for the usual stand tile first, then the other orthogonal neighbours of the person."""
    nx, ny = npc_tile(sx, sy, facing)
    alts = [(nx + dx, ny + dy, OPPOSITE[d]) for d, (dx, dy) in DIRS.items() if (nx + dx, ny + dy) != (sx, sy)]
    return [(sx, sy, facing)] + alts


def step(ctx, g, st: dict, goal: str, m: int, spec: tuple, occ: set) -> Decision | None:
    _, sx, sy, facing, who = spec
    v, bad = ctx.view, st["dead"] | occ
    options = [s for s in stands(sx, sy, facing) if s[:2] not in bad]
    for x, y, f in options:
        if (v.x, v.y) == (x, y):
            if ctx.facing != f:
                return Decision(f, "goal_talk_face", f"goal {goal}: facing {who} ({f}) from alternate tile ({x},{y})")
            ctx.goal_talk_tries[goal] = ctx.goal_talk_tries.get(goal, 0) + 1
            return Decision("A", "goal_talk", f"goal {goal}: A at {who} from ({x},{y}) (try {ctx.goal_talk_tries[goal]})")
    if st["steps"] >= STEP_CAP:
        return None
    g.blocked_now = frozenset(g.blocked_now) | {(m, *t) for t in occ}
    best = None
    for x, y, f in options:
        p = g.path((m, v.x, v.y), lambda n, t=(m, x, y): n == t)
        if p and (best is None or len(p) < len(best[0])):
            best = (p, (x, y))
    if best:
        p, tile = best
        st["steps"] += 1
        if len(p) == 1:
            st["last"] = (getattr(ctx, "step", 0), v.x, v.y, tile)
        return Decision(p[0], "goal_talk_alt", f"goal {goal}: stand tile blocked, {len(p)} steps to ({tile[0]},{tile[1]}) to talk to {who}")
    return _leave(ctx, g, st, goal, m)


def _leave(ctx, g, st: dict, goal: str, m: int) -> Decision | None:
    """No usable tile: walk out of the map (re-entering reloads the sprites); once per goal per run, then hand back to the planner."""
    done = ctx.__dict__.setdefault("talk_alt_reentries", {})
    if not st["leaving"] and done.get(goal, 0) >= REENTRIES:
        return None
    p = g.path((ctx.view.m, ctx.view.x, ctx.view.y), lambda n: n[0] != m)
    if not p:
        return None
    if not st["leaving"]:
        st["leaving"] = True
        done[goal] = done.get(goal, 0) + 1
    st["steps"] += 1
    return Decision(p[0], "goal_talk_leave", f"goal {goal}: no free tile next to the person, leaving the map to reload its sprites")
