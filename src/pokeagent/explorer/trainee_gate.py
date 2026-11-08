"""trainee_gate: never train a fainted (or soon-fainting) switch-trainee.

Gen 1 EXP (UNVERIFIED, from memory of pokered GainExperience): only participants still alive when the enemy
faints share it - a fainted trainee earns nothing while the stage keeps spending steps and battles. The pure gate
is explorer.status_care.trainee_eligible; this module reads the live party (ramstructs), the trainee slot
(magikarp.trainee_slot_for over ctx.train_member) and the walk to the nearest known heal, then acts:

- fix "center"   -> ctx.center_intent (the existing Pokecenter path is only REQUESTED through that field)
- fix "revive" / "antidote" -> a StatusCare cure request on the slot (rope_press targets a party slot; when the
  sequence cannot land it, StatusCare falls back to the same ctx.center_intent walk)

A fainted trainee also counts ctx.trainee_fainted_steps (once per step) so review tools can subtract those steps
from "training steps", and logs the faint at most once per FAINT_LOG_EVERY steps into status_care.jsonl.
"""
from __future__ import annotations

from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.economy.prices import ANTIDOTE, FULL_HEAL, REVIVE
from pokeagent.explorer.status_care import (Eligibility, MonStatus, record_row, status_kinds, trainee_eligible)
from pokeagent.goals import bag_contents
from pokeagent.knowledge.kb import table
from pokeagent.legs import grid as G
from pokeagent.magikarp import trainee_slot_for
from pokeagent.ramstructs import read_party

FAINT_LOG_EVERY = 100   # steps between repeated "trainee fainted" log lines (untuned first value)


def trainee_ok(ctx) -> Eligibility:
    """Eligibility of the run's switch-trainee (the Magikarp, or the slot ctx.train_member names)."""
    party = read_party(ctx.emu)
    slot = trainee_slot_for(ctx.emu, ctx.train_member)
    if slot is None or not 0 <= slot < len(party):
        return Eligibility(True, "no trainee to gate", "")
    rows = [MonStatus(i, p.hp, p.max_hp, status_kinds(p.status)) for i, p in enumerate(party)]
    bag = bag_contents(ctx.emu)
    walk = outside_use.walk_to_center(ctx)
    steps = walk[0] / G.FRAME_WALK if walk else None
    elig = trainee_eligible(rows, slot, bag.get(REVIVE, 0) > 0, steps,
                            antidote_carried=bool(bag.get(ANTIDOTE, 0) or bag.get(FULL_HEAL, 0)))
    if elig.ok:
        return elig
    mon = party[slot]
    if mon.hp <= 0:
        if ctx.trainee_faint_step != ctx.step:
            ctx.trainee_faint_step = ctx.step
            ctx.trainee_fainted_steps += 1
        if ctx.step - ctx.trainee_faint_log_at >= FAINT_LOG_EVERY:
            ctx.trainee_faint_log_at = ctx.step
            name = table(None, "name_of_internal").get(str(mon.species), f"0x{mon.species:02X}")
            ctx.log(f"[trainee fainted: no exp (slot {slot} {name} L{mon.level}) - healing first]", "res")
            record_row(ctx, {"event": "trainee_fainted", "slot": slot, "species": mon.species, "level": mon.level,
                             "map": ctx.view.m})
    if elig.fix == "center":
        ctx.center_intent = "trainee_gate"
    elif elig.fix in ("revive", "antidote") and ctx.status_care.get("seq") is None:
        item = REVIVE if elig.fix == "revive" else (ANTIDOTE if bag.get(ANTIDOTE, 0) else FULL_HEAL)
        ctx.status_care["request"] = (item, slot)   # StatusCare uses it on that slot (party_target targets it)
    return elig
