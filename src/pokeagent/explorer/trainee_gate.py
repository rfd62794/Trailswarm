"""trainee_gate: never train a fainted (or soon-fainting) switch-trainee.

Gen 1 EXP (UNVERIFIED, from memory of pokered GainExperience): only participants still alive when the enemy
faints share it - a fainted trainee earns nothing while the stage keeps spending steps and battles. The pure gate
is explorer.status_care.trainee_eligible; this module reads the live party (ramstructs), the trainee slot
(training_ctl.roster.trainee_slot over ctx.train_member) and the walk to the nearest known heal.

Two entry points, on purpose:

- ``trainee_check(ctx)``: a PURE READ (safe in ``applies()``, safe to call twice a step). Cheap path first: a
  living, unpoisoned trainee returns at once; the heal-walk search runs only for an ineligible one.
- ``trainee_ok(ctx)``: the check plus its actions (counters, the faint log row, the request) - call it from a
  step / tick, never from ``applies()``:
    fix "center"   -> heal_walk.start (walk to the nearest known Pokecenter and talk to the nurse; carried out
                      by the StatusCare behaviour, which runs before PlanGoal; abandoned with a logged reason)
    fix "revive" / "antidote" -> a StatusCare cure request on the slot (rope_press targets a party slot; when the
                      sequence cannot land it, StatusCare falls back to the same heal walk)

A fainted trainee also counts ``fainted_steps`` (once per step) in the status-care state so review tools can
subtract those steps from "training steps", and logs the faint at most once per FAINT_LOG_EVERY steps.
"""
from __future__ import annotations

from pokeagent.explorer import heal_walk
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.economy.prices import ANTIDOTE, FULL_HEAL, REVIVE
from pokeagent.explorer.status_care import (MAX_TRIES, Eligibility, MonStatus, of, record_row, status_kinds, trainee_eligible)
from pokeagent.explorer.training_ctl import roster
from pokeagent.goals import bag_contents
from pokeagent.knowledge.kb import table
from pokeagent.legs import grid as G
from pokeagent.ramstructs import read_party

FAINT_LOG_EVERY = 100   # steps between repeated "trainee fainted" log lines (untuned first value)
_FINE = Eligibility(True, "", "")


def trainee_check(ctx) -> Eligibility:
    """Eligibility of the run's switch-trainee (the Magikarp, or the slot ctx.train_member names). Pure."""
    party = read_party(ctx.emu)
    slot = roster.trainee_slot(ctx)
    if slot is None or not 0 <= slot < len(party):
        return Eligibility(True, "no trainee to gate", "")
    mon = party[slot]
    if mon.hp > 0 and "poison" not in status_kinds(mon.status):
        return _FINE                      # the common case costs two reads, never a path search
    st = of(ctx)
    if st.get("walk") is not None or ctx.step < st.get("walk_cool", 0):
        # a heal walk is running or just gave up: the verdict is known, so no path search (BFS) per step
        return Eligibility(False, f"slot {slot} unfit: heal walk pending or cooling down", "center")
    rows = [MonStatus(i, p.hp, p.max_hp, status_kinds(p.status)) for i, p in enumerate(party)]
    bag = bag_contents(ctx.emu)
    walk = outside_use.walk_to_center(ctx)
    steps = walk[0] / G.FRAME_WALK if walk else None
    return trainee_eligible(rows, slot, bag.get(REVIVE, 0) > 0, steps,
                            antidote_carried=bool(bag.get(ANTIDOTE, 0) or bag.get(FULL_HEAL, 0)))


def trainee_ok(ctx) -> Eligibility:
    """trainee_check plus its actions. Call from step()/tick hooks only."""
    elig = trainee_check(ctx)
    if elig.ok:
        return elig
    st = of(ctx)
    party = read_party(ctx.emu)
    slot = roster.trainee_slot(ctx)
    mon = party[slot]
    if mon.hp <= 0:
        if st.get("faint_step") != ctx.step:
            st["faint_step"] = ctx.step
            st["fainted_steps"] = st.get("fainted_steps", 0) + 1
        if ctx.step - st.get("faint_log_at", -10**9) >= FAINT_LOG_EVERY:
            st["faint_log_at"] = ctx.step
            name = table(None, "name_of_internal").get(str(mon.species), f"0x{mon.species:02X}")
            ctx.log(f"[trainee fainted: no exp (slot {slot} {name} L{mon.level}) - requesting a heal]", "res")
            record_row(ctx, {"event": "trainee_fainted", "slot": slot, "species": mon.species, "level": mon.level,
                             "map": ctx.view.m})
    if elig.fix == "center":
        heal_walk.start(ctx, f"trainee_gate: {elig.why}")
    elif elig.fix in ("revive", "antidote") and st.get("tries", 0) >= MAX_TRIES:
        heal_walk.start(ctx, f"trainee_gate: {elig.fix} did not land ({elig.why})")   # the item path is written off
    elif elig.fix in ("revive", "antidote") and st.get("seq") is None:
        bag = bag_contents(ctx.emu)
        item = REVIVE if elig.fix == "revive" else (ANTIDOTE if bag.get(ANTIDOTE, 0) else FULL_HEAL)
        st["request"] = (item, slot)   # StatusCare uses it on that slot (party_target targets it)
    return elig
