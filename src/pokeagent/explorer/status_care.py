"""status_care: poison care and EXP-eligibility rules (pure: no emulator, no RAM reads).

UNVERIFIED Gen 1 facts (from memory of pokered; ONE helper each so the controller's ROM check fixes them in one edit):
- the party-struct status byte (+4): sleep = low 3 bits (a counter 1..7), poison = bit 3 (0x08), burn = bit 4 (0x10),
  freeze = bit 5 (0x20), paralysis = bit 6 (0x40);
- overworld poison: -1 HP per POISON_STEPS_PER_HP walked tiles, and a mon CAN faint from it (an all-fainted party is
  a blackout, which halves the money). Burn/paralysis do not tick outside battle; in battle poison/burn tick 1/16 max HP;
- EXP (pokered GainExperience / wPartyGainExpFlags): only participants still alive when the enemy faints share it; a
  participant that fainted before the kill earns nothing, and reviving mid-fight does not restore the share. The
  eligibility gate below only relies on "alive at the end".
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from pokeagent.explorer.economy.prices import ANTIDOTE, FULL_HEAL, HEAL_HP, POTION, REVIVE, SUPER_POTION, price
from pokeagent.knowledge import encounters
from pokeagent.knowledge.catch_math import BRN_BIT, FRZ_BIT, PAR_BIT, PSN_BIT, SLP_MASK
from pokeagent.knowledge.kb import table

log = logging.getLogger(__name__)

MAX_TRIES = 2                    # failed item uses before the item is written off for this episode (untuned first value)
POISON_STEPS_PER_HP = 4          # UNVERIFIED (from memory of pokered ApplyOutOfBattlePoisonDamage): 1 HP per 4 walked tiles
POISON_BATTLE_FRACTION = 1 / 16  # UNVERIFIED: in-battle poison/burn tick share of max HP (not used here; battle owns it)
CARE_MARGIN_STEPS = 8            # extra steps of slack before the nearest known heal (untuned first value)
ANTIDOTE_FLOOR = 1               # Antidotes to carry when the route ahead has poison (untuned first value)
POISON_LOOKAHEAD = 3             # unmet goals ahead whose {"map": [...]} detector counts as "poison ahead" (untuned first value)
TRAINEE_MIN_SAFE_STEPS = 30      # a poisoned trainee must survive this many walked tiles to be trained (untuned first value)
REVIVE_BEATS_WALK_STEPS = 150    # a carried Revive beats a heal walk longer than this (untuned first value)

ITEM_NAME = {ANTIDOTE: "ANTIDOTE", FULL_HEAL: "FULL HEAL", POTION: "POTION", SUPER_POTION: "SUPER POTION", REVIVE: "REVIVE"}


@dataclass(frozen=True)
class MonStatus:
    slot: int
    hp: int
    max_hp: int
    kinds: frozenset[str]


@dataclass(frozen=True)
class CareDecision:
    action: str               # "none" | "antidote" | "potion" | "walk_to_center" | "nothing_available"
    slot: int | None
    item: int | None
    why: str


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    why: str
    fix: str                  # "" | "center" | "revive" | "antidote"


def status_kinds(byte: int) -> frozenset[str]:
    """The party-struct status byte -> the status names on it (all of them, unlike catch_math.status_kind's
    one). The bit constants are catch_math's, so verifying them there fixes both: sleep = low 3 bits (a counter
    1..7), poison, burn, freeze, paralysis ("paralysis" here, "paralyse" in catch_math). UNVERIFIED (pokered)."""
    kinds = set()
    if byte & SLP_MASK:
        kinds.add("sleep")
    for bit, name in ((PSN_BIT, "poison"), (BRN_BIT, "burn"), (FRZ_BIT, "freeze"), (PAR_BIT, "paralysis")):
        if byte & bit:
            kinds.add(name)
    return frozenset(kinds)


def of(ctx) -> dict:
    """The run's status-care state dict ({seq, request, walk, sig, next_check, last, tries, items_out, ...}),
    held on the context's __dict__ (not a dataclass field: context.py is at its line ceiling)."""
    return ctx.__dict__.setdefault("_status_care", {})


def steps_to_faint(hp: int, per_hp: int = POISON_STEPS_PER_HP) -> int:
    """Worst-case walked tiles before overworld poison faints a mon at ``hp`` (the 4-step counter's phase is
    unknown, so the first HP may go after one tile). 0 for a mon already down."""
    return max(0, (hp - 1) * per_hp + 1) if hp > 0 else 0


def decide(party: list[MonStatus], bag: dict, steps_to_heal: float | None, kb=None) -> CareDecision:
    """The care table, first match wins; the worst-case poisoned member (smallest steps_to_faint) is the one treated.
    ``steps_to_heal`` = walked tiles to the nearest known heal (None = no heal known = infinite)."""
    living = [m for m in party if m.hp > 0]
    urgency = "blackout risk" if living and all("poison" in m.kinds for m in living) else "member loss"
    # A row per non-poison kind, all `none` in v1: burn/paralysis/sleep/freeze do not tick in the overworld, so no
    # field cure or walk is spent on them (the battle behaviours and the nurse own them). A later field cure
    # (PARLYZ HEAL, AWAKENING, ICE HEAL, BURN HEAL) is a one-edit change to the matching row.
    noted = [k for k in ("burn", "paralysis", "sleep", "freeze") if any(k in m.kinds for m in party)]
    sick = [m for m in living if "poison" in m.kinds]
    if not sick:
        return CareDecision("none", None, None,
                            "no poisoned member" + (f" ({', '.join(noted)} noted: no field cure in v1)" if noted else ""))
    need = steps_to_heal + CARE_MARGIN_STEPS if steps_to_heal is not None else math.inf
    worst = min(sick, key=lambda m: steps_to_faint(m.hp))
    faint = steps_to_faint(worst.hp)
    if all(steps_to_faint(m.hp) > need for m in sick):
        return CareDecision("none", None, None, f"poison ok: {steps_to_heal:.0f} steps to heal, {faint} to faint")
    if bag.get(ANTIDOTE, 0) > 0 or bag.get(FULL_HEAL, 0) > 0:
        item = ANTIDOTE if bag.get(ANTIDOTE, 0) > 0 else FULL_HEAL  # the cheaper purpose-built cure first
        return CareDecision("antidote", worst.slot, item,
                            f"{urgency}: slot {worst.slot} faints in {faint} steps ({_dist(steps_to_heal)} to the nurse) "
                            f"-> {ITEM_NAME[item]} ({price(item)} yen)")
    potion = next((i for i in (POTION, SUPER_POTION) if bag.get(i, 0) > 0 and steps_to_faint(worst.hp + HEAL_HP[i]) > need), None)
    if potion is not None:
        return CareDecision("potion", worst.slot, potion,
                            f"{urgency}: slot {worst.slot} faints in {faint}; a {ITEM_NAME[potion]} buys "
                            f"{steps_to_faint(worst.hp + HEAL_HP[potion])} > {need:.0f} needed")
    if steps_to_heal is not None:
        return CareDecision("walk_to_center", worst.slot, None,
                            f"{urgency}: slot {worst.slot} faints in {faint} steps, no cure carried -> walk to the nurse")
    return CareDecision("nothing_available", worst.slot, None,
                        f"{urgency}: slot {worst.slot} poisoned ({faint} steps to faint), no cure and no known heal")


def _dist(steps_to_heal: float | None) -> str:
    return f"{steps_to_heal:.0f}" if steps_to_heal is not None else "no known route"


def poisoners_on(map_id: int, wild_by_map=None, learnsets=None, moves=None, kb=None) -> list[str]:
    """Species on the map's grass that can poison us: poison-typed (species_by_dex), or holding a poison-effect
    move at the map's TOP wild level (party.moves_at + knowledge.moves.effect_of). Empty without the ROM tables."""
    from pokeagent.knowledge import moves as kmoves, party as kparty
    kbd = {"wild_by_map": wild_by_map if wild_by_map is not None else table(kb, "wild_by_map"),
           "learnsets": learnsets if learnsets is not None else table(kb, "learnsets"),
           "species_by_dex": table(kb, "species_by_dex"),
           "moves": moves if moves is not None else table(kb, "moves")}
    move_rows = {m.get("name", ""): m for m in kbd["moves"].values()}
    types_of = {r.get("name", ""): (r.get("type1", ""), r.get("type2", "")) for r in kbd["species_by_dex"].values()}
    out = []
    for name, (_lo, hi, _chance) in encounters.species_on(map_id, kbd).items():
        if "POISON" in types_of.get(name, ()):
            out.append(name)
            continue
        known = kparty.moves_at(name, hi, kbd)
        if any((e := kmoves.effect_of(move_rows.get(m))) is not None and e.status == "poison" for m in known):
            out.append(name)
    return out


def poison_ahead(goals: dict, here_map: int | None, wild_by_map=None, kb=None) -> bool:
    """True when the route ahead can poison us: the current map, the stage's training map (encounters.TRAIN_MAP),
    or any map of the next POISON_LOOKAHEAD unmet goals whose campaign detector is {"map": [...]} (campaign.json)."""
    from pokeagent.campaign import load_campaign
    from pokeagent.explorer.training import stage_goal
    maps = {here_map} if here_map is not None else set()
    train = encounters.TRAIN_MAP.get(stage_goal(goals) or "", None)
    if train is not None:
        maps.add(train)
    for g in [g for g in load_campaign() if not goals.get(g["id"])][:POISON_LOOKAHEAD]:
        det = g.get("detector")
        if isinstance(det, dict) and set(det) == {"map"}:
            maps.update(det["map"])
    return any(poisoners_on(m, wild_by_map, kb=kb) for m in maps)


def trainee_eligible(party: list[MonStatus], slot: int | None, revive_carried: bool, steps_to_heal: float | None,
                     antidote_carried: bool = False) -> Eligibility:
    """May the switch-trainee be trained now? Gen 1 EXP (UNVERIFIED, from memory of pokered GainExperience): only
    participants alive when the enemy faints share it, so a fainted (or soon-fainting) trainee earns nothing."""
    if slot is None or not 0 <= slot < len(party):
        return Eligibility(True, "no trainee to gate", "")
    m = party[slot]
    if m.hp <= 0:
        if revive_carried and (steps_to_heal is None or steps_to_heal > REVIVE_BEATS_WALK_STEPS):
            return Eligibility(False, f"slot {slot} fainted: no exp until revived", "revive")
        return Eligibility(False, f"slot {slot} fainted: no exp until healed", "center")
    if "poison" in m.kinds and steps_to_faint(m.hp) <= TRAINEE_MIN_SAFE_STEPS:
        return Eligibility(False, f"slot {slot} poisoned: faints in {steps_to_faint(m.hp)} steps",
                           "antidote" if antidote_carried else "center")
    return Eligibility(True, "", "")


def provenance(ctx) -> str:
    """The run's record provenance (standing rule): the start state's lineage via checkpoint_goals.start_lineage,
    'unknown' when there is no record - never guessed. Cached on the context."""
    if "_status_care_provenance" not in ctx.__dict__:
        from pokeagent.checkpoint_goals import start_lineage
        ctx.__dict__["_status_care_provenance"] = start_lineage(getattr(getattr(ctx, "opts", None), "state_path", "") or None)
    return ctx.__dict__["_status_care_provenance"]


def record_row(ctx, row: dict) -> None:
    """Append one row to the run's status_care.jsonl (best effort: a failure never ends a run)."""
    try:
        rec = {"step": ctx.step, "map": ctx.view.m if getattr(ctx, "view", None) else None,
               "provenance": provenance(ctx), **row}
        with (ctx.run_dir / "status_care.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception as exc:  # noqa: BLE001  a failed row never ends a run, but it is said once
        if not of(ctx).get("row_warned"):
            of(ctx)["row_warned"] = True
            log.warning("status_care.jsonl row not written: %r (further failures suppressed)", exc)


__all__ = ["MonStatus", "CareDecision", "Eligibility", "POISON_STEPS_PER_HP", "POISON_BATTLE_FRACTION",
           "CARE_MARGIN_STEPS", "ANTIDOTE_FLOOR", "POISON_LOOKAHEAD", "TRAINEE_MIN_SAFE_STEPS",
           "REVIVE_BEATS_WALK_STEPS", "ITEM_NAME", "status_kinds", "of", "steps_to_faint", "decide",
           "poisoners_on", "poison_ahead", "trainee_eligible", "provenance", "record_row"]
