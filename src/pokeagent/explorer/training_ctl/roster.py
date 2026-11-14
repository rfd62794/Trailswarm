"""Roster (training controller slice 4): the ONE owner of "which party slot is the switch-trainee".

Six call sites of ``magikarp.trainee_slot_for`` asked the question with subtly different arguments
(only switch_out's ``trainee_out`` passes the band breakers). Slice 4a puts them all behind this one
entry point with identical arguments - a QUERY, like ``sustain.heal_now``: no memo, no ctx write (the
sites run at different points of a step and caching would change decisions).
"""
from __future__ import annotations

import pokeagent.magikarp as magikarp

from pokeagent.knowledge import team_plan
from pokeagent.ramstructs import read_party


def trainee_slot(ctx, *, breakers: bool = False) -> int | None:
    """THE one entry for "which party slot is the switch-trainee"."""
    return magikarp.trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None),
                                     (team_plan.of(ctx).get("breakers") or ()) if breakers else ())


def note_faints(ctx) -> int:
    """The run's monotonic faint counter, stored in ``team_plan.of(ctx)`` beside ``order_hold``:
    ``n`` members at hp 0 now vs the last observed count (``faints_prev``) - a faint (n rises) adds
    the difference, a heal or revive (n drops) never subtracts, so a heal can never undo a faint's
    reorder trigger. Stamped per ``ctx.step``: a second call in the same step returns the stored
    value. ORDER-INDEPENDENT on purpose (a reorder permutes slots, so a per-slot comparison would
    miscount). Never resets within a run (blackouts and Pokecenter heals do not reset it; a new
    context starts at 0). Blind spot, accepted: a revive and a new faint inside one single step
    cancel out."""
    st = team_plan.of(ctx)
    if st.get("faints_step") == ctx.step:
        return st.get("faints", 0)
    st["faints_step"] = ctx.step
    n = sum(1 for m in read_party(ctx.emu) if m.hp == 0)
    st["faints"] = st.get("faints", 0) + max(0, n - st.get("faints_prev", n))
    st["faints_prev"] = n
    return st["faints"]
