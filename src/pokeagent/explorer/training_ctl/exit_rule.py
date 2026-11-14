"""Exit (training controller slice 5a): one writer and one reader set for the gym-hold flags.

Slice 5a moves only WHO writes and reads the two ad-hoc ctx flags - ``ctx.gym_hold_seen`` (the ``(step, bool)``
stamp of PlanGoal's gym-hold verdict) and ``ctx.__dict__["floor_unmet"]`` (gate_state's team-floor verdict) -
here, at the exact points and with the exact values main used (no timing or order change). Slice 5b folds
GrindBudget / stall_hold_holds and the gate_lifted / lifted_need block into this module and deletes the old
flags. The shadow (adapters.old_flags) keeps reading the raw attributes on purpose: it is the compare's
"old flags" half.
"""
from __future__ import annotations


def publish_hold(ctx, held: bool) -> None:
    """The ONE writer of ``ctx.gym_hold_seen`` (the ``(step, bool)`` stamp goal_talk and frontier read)."""
    ctx.gym_hold_seen = (ctx.step, bool(held))


def publish_floor(ctx, unmet: bool) -> None:
    """The ONE writer of the floor flag ``ctx.__dict__["floor_unmet"]`` (gate_state's per-step verdict)."""
    ctx.__dict__["floor_unmet"] = bool(unmet)


def floor_unmet(ctx) -> bool:
    """The floor flag's one read: False until gate_state first publishes it (a fresh run starts unwritten)."""
    return bool(ctx.__dict__.get("floor_unmet"))


def hold_clear(ctx, fresh: int) -> bool:
    """goal_talk's rule, verbatim: only a recent ``(step, False)`` stamp lets GoalTalk walk to the leader."""
    seen = getattr(ctx, "gym_hold_seen", None)
    return bool(seen) and seen[1] is False and ctx.step - seen[0] <= fresh


def floor_hold(ctx) -> bool:
    """frontier's rule, verbatim: the boss is held shut by the team floor while the stamped hold flag is True."""
    return floor_unmet(ctx) and (getattr(ctx, "gym_hold_seen", None) or (0, False))[1]
