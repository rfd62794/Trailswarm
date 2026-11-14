"""Roster (training controller slice 4): the ONE owner of "which party slot is the switch-trainee".

Six call sites of ``magikarp.trainee_slot_for`` asked the question with subtly different arguments
(only switch_out's ``trainee_out`` passes the band breakers). Slice 4a puts them all behind this one
entry point with identical arguments - a QUERY, like ``sustain.heal_now``: no memo, no ctx write (the
sites run at different points of a step and caching would change decisions).
"""
from __future__ import annotations

from pokeagent import magikarp
from pokeagent.knowledge import team_plan


def trainee_slot(ctx, *, breakers: bool = False) -> int | None:
    """THE one entry for "which party slot is the switch-trainee"."""
    return magikarp.trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None),
                                     (team_plan.of(ctx).get("breakers") or ()) if breakers else ())
