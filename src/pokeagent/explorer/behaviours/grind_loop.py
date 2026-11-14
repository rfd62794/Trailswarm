"""grind_loop: tell a training pace in the grass from a stuck loop.

2026-11-12 laptop run (12,000 steps, Cerulean -> beat_misty): about 1,090 steps went to SHAKE random walks, because pacing a
few grass tiles while wild battles come up looks like "60 presses on <=6 tiles". That pace IS the training: while the
trainee stage is live, a window that saw a battle start is progress, so LoopGuard skips its 60-press shake. A window with
no battle (a real stall on the edge) still shakes.
"""
from __future__ import annotations

WINDOW = 60  # LoopGuard's loop window (non-battle presses)
MAX_EXEMPT_WINDOWS = 3  # consecutive exempt windows before a shake is forced anyway (review: an exemption must not be unbounded)


def note_step(ctx) -> None:
    """Record ctx.battles once per non-battle press, in step with LoopGuard's position history (same trim)."""
    h = ctx.__dict__.setdefault("battle_hist", [])
    h.append(ctx.battles)
    del h[:-150]


def reset(ctx) -> None:
    ctx.__dict__["battle_hist"] = []
    ctx.__dict__["exempt_presses"] = 0


def mark_live(ctx, planned):
    """Pass a train_route step through, flagging the run as training. The team_ready stage sets ctx.train_route_live itself,
    but the gym hold and the grind latch (stage beat_misty, floor unmet) walk to the SAME grass through the SAME
    train_route.step (its text still says "goal team_ready") without it: the pacing there was shaken (2026-11-13 A/B: #235's
    exemption never fired, the two 12,000-step runs were byte-identical). Slice 3: the write goes through training_ctl.sustain.publish (the single writer)."""
    if planned is not None:
        from pokeagent.explorer.training_ctl import sustain
        sustain.publish(ctx, True)
    return planned


def paced_in_training(ctx) -> bool:
    """True when the team_ready stage is training and a battle began inside the last WINDOW presses."""
    h = ctx.__dict__.get("battle_hist") or []
    live = bool(ctx.train_route_live) or bool((ctx.__dict__.get("_grind_state") or {}).get("episode"))  # a grind episode paces its grass too
    if not (live and len(h) >= WINDOW and h[-WINDOW] != ctx.battles):
        return False
    n = ctx.__dict__["exempt_presses"] = ctx.__dict__.get("exempt_presses", 0) + 1
    if n > MAX_EXEMPT_WINDOWS * WINDOW:  # 3 windows spared: shake once (the caller resets the count)
        return False
    return True
