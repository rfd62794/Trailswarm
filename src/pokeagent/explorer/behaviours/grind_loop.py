"""grind_loop: tell a training pace in the grass from a stuck loop.

2026-11-12 laptop run (12,000 steps, Cerulean -> beat_misty): about 1,090 steps went to SHAKE random walks, because pacing a
few grass tiles while wild battles come up looks like "60 presses on <=6 tiles". That pace IS the training: while the
trainee stage is live, a window that saw a battle start is progress, so LoopGuard skips its 60-press shake. A window with
no battle (a real stall on the edge) still shakes.
"""
from __future__ import annotations

WINDOW = 60  # LoopGuard's loop window (non-battle presses)


def note_step(ctx) -> None:
    """Record ctx.battles once per non-battle press, in step with LoopGuard's position history (same trim)."""
    h = ctx.__dict__.setdefault("battle_hist", [])
    h.append(ctx.battles)
    del h[:-150]


def reset(ctx) -> None:
    ctx.__dict__["battle_hist"] = []


def paced_in_training(ctx) -> bool:
    """True when the team_ready stage is training and a battle began inside the last WINDOW presses."""
    h = ctx.__dict__.get("battle_hist") or []
    return bool(ctx.train_route_live) and len(h) >= WINDOW and h[-WINDOW] != ctx.battles
