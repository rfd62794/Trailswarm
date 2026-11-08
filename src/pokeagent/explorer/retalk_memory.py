"""retalk_memory: a talk the retalk veto turned into B is a failed option the planner moves past.

``retalk_veto.veto`` swaps an A for a harmless B at the engine, but the planner never heard about it, so it chose
the same A next step (Viridian Forest, Blue marathon: 755 vetoed presses facing an already-beaten Bug Catcher).
Engine.step calls ``note`` when plan_goal's A is vetoed; plan_goal hands ``active`` to plan_step as ``_talk_vetoed``,
and the planner drops those standing spots as "talk here" candidates. The note expires after TALK_VETO_TTL steps, so a
veto that stops holding (hurt party, new goal) is retried instead of being remembered forever."""
from __future__ import annotations

TALK_VETO_TTL = 300  # steps a vetoed standing spot stays off the planner's list


def note(ctx, decision) -> None:
    """Remember the (map, x, y) the planner's vetoed A was pressed from."""
    if decision.behaviour == "plan_goal" and decision.button == "A":
        v = ctx.view
        ctx.talk_vetoed[(v.m, v.x, v.y)] = ctx.step


def active(ctx) -> frozenset:
    """Standing spots whose planned talk was vetoed within the last TALK_VETO_TTL steps (expired ones are dropped)."""
    for spot in [s for s, at in ctx.talk_vetoed.items() if ctx.step - at >= TALK_VETO_TTL]:
        del ctx.talk_vetoed[spot]
    return frozenset(ctx.talk_vetoed)
