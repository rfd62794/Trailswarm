"""Trainee release (trainee independence): the per-member verdict "can stand alone on map M".

Per (slot, map): the ROM-math estimate (``solo_viable``) AND the map's observed solo record - while
released it leads and stays in (no switch trick, full XP); a faint, a blackout or a win nearly dead
revokes it for REVOKE_COOLDOWN steps. Missing data is never released. ``note_battle`` is the one
writer of ``ctx.__dict__["release"]``; ``ladder_spots`` is the atlas read ``area_ladder.pick`` needs.
"""
from __future__ import annotations

import logging

from pokeagent.explorer.kb import ROM_KB
from pokeagent.grind import area_ladder, atlas, solo_viable, stage_maps
from pokeagent.knowledge import team_floor, team_plan
from pokeagent.knowledge.encounters import MAP_NAMES, map_name
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import our_party, species_row
from pokeagent.magikarp import trainee_slot_for
from pokeagent.ramstructs import read_party

log = logging.getLogger(__name__)

PROBATION_FIGHTS = 3      # solo fights observed on this map before the observed record counts (untuned)
MIN_OBS_WIN = 0.9         # observed solo win share once PROBATION_FIGHTS exist
REVOKE_COOLDOWN = 400     # steps a revoked (slot, map) stays on the switch trick (untuned)
KEEP_FIGHTS = 8           # the bounded solo history per (slot, map)
_warned: set = set()


def _verdict(ctx, slot, map_id, rec) -> bool:
    """The uncached verdict (``verdict`` memoizes it per step)."""
    ours = our_party(ctx.emu)
    c = ours[slot] if slot is not None and 0 <= slot < len(ours) and len(ours) == len(read_party(ctx.emu)) else None
    if getattr(ctx, "step", 0) < rec.get("revoked_until", 0) or c is None or c.name == "MAGIKARP":
        return False
    sv = solo_viable.solo_verdict(c, ROM_KB, map_id)
    rec["model"] = sv[0] if sv else None
    if not solo_viable.passes(sv):
        return False
    fights = rec.get("fights", ())
    return len(fights) < PROBATION_FIGHTS or sum(1 for f in fights if f["won"]) / len(fights) >= MIN_OBS_WIN


def verdict(ctx, slot, map_id) -> bool:
    """True = the trainee stands alone on ``map_id``. Memoized per (step, slot, map): a flip logs."""
    rec = ctx.__dict__.setdefault("release", {}).setdefault((slot, map_id), {"fights": [], "revoked_until": 0})
    if "v" not in rec or rec["v"][0] != getattr(ctx, "step", None):
        try:
            v = _verdict(ctx, slot, map_id, rec)
        except Exception:  # noqa: BLE001
            v = False                                       # a bad party/kb read is missing data
        was = rec.get("v", [None, False])[1]
        if v != was:
            ctx.log(f"[release] slot {(slot or 0) + 1} on {map_name(map_id)}: {'released' if v else 'dropped'} - "
                    f"model {(rec.get('model') or 0.0):.2f} win, observed {sum(1 for f in rec['fights'] if f['won'])}/{len(rec['fights'])}", "res")
        rec["v"] = [getattr(ctx, "step", None), v]
    return rec["v"][1]


def note_battle(ctx, slot, map_id, *, won, hp_left, fainted, blackout) -> None:
    """The one writer: fold a fight the released trainee stood alone for into its (slot, map)
    record; a faint, a blackout or a win under half the solo margin revokes it."""
    if not verdict(ctx, slot, map_id):
        return                                                # not a solo fight: nothing to learn
    rec = ctx.__dict__["release"][(slot, map_id)]
    rec["fights"].append({"won": bool(won), "hp_left": hp_left})
    del rec["fights"][:-KEEP_FIGHTS]
    revoked = fainted or blackout or (won and hp_left < solo_viable.SOLO_MARGIN * 0.5)
    if revoked:
        rec["revoked_until"] = ctx.step + REVOKE_COOLDOWN
        why = "fainted" if fainted else "blackout" if blackout else f"won at {hp_left:.0%} HP"
        ctx.log(f"[release] slot {slot + 1} on {map_name(map_id)}: revoked ({why}) for {REVOKE_COOLDOWN} steps", "res")
    v = _verdict(ctx, slot, map_id, rec)
    if not v and not revoked:                                 # the observed record alone dropped it
        ctx.log(f"[release] slot {slot + 1} on {map_name(map_id)}: dropped - observed {sum(1 for f in rec['fights'] if f['won'])}/{len(rec['fights'])}", "res")
    rec["v"] = [getattr(ctx, "step", None), v]


def note_wild(ctx, map_id, *, won, outcome, trainer) -> None:
    """battle.py's per-battle feed: a WILD fight's result for the rotation trainee."""
    if trainer: return
    try:
        pm = read_party(ctx.emu)
        slot = trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None), team_plan.of(ctx).get("breakers") or ())
    except Exception:  # noqa: BLE001
        return
    if slot is not None and 0 <= slot < len(pm):
        p = pm[slot]
        note_battle(ctx, slot, map_id, won=won, hp_left=p.hp / p.max_hp if p.max_hp else 0.0,
                    fainted=p.hp <= 0, blackout=outcome == "blackout")


def released(ctx, slot) -> bool:
    """The release verdict for the map we're on (``roster.released`` delegates here)."""
    return verdict(ctx, slot, getattr(getattr(ctx, "view", None), "m", None))


def ladder_spots(ctx, stage, maps, here):
    """(atlas Spot rows, trained slot) for the ladder: the stage's allowed AND known-reachable rungs
    ranked for the member the rotation trains. ``[]`` = no rung data: the caller keeps the pin."""
    rungs = stage_maps.allowed(stage) or stage_maps.LADDER_BY_STAGE.get(stage)
    ours = our_party(ctx.emu) if rungs else []
    if not ours or len(ours) != len(read_party(ctx.emu)):
        return [], None                                       # an unaligned or empty party read is missing data
    slot = trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None), team_plan.of(ctx).get("breakers") or ())
    slot = slot if slot is not None and 0 <= slot < len(ours) else max(range(len(ours)), key=lambda i: ours[i].level, default=None)
    c = ours[slot]
    tables = {"wild": table(ROM_KB, "wild_by_map"), "base_exp": {r["name"]: r["base_exp"] for r in table(ROM_KB, "species_by_dex").values()}}
    return (atlas.rank_spots(c.name, c.level, team_floor.FLOOR_BY_GOAL.get(stage), tables, {}, {},
                             (species_row(c.name, ROM_KB) or {}).get("growth", "MEDIUM_SLOW"),
                             candidates=area_ladder.known_rungs(maps, here, rungs), top=len(rungs), names=MAP_NAMES), slot)


def warn_ladder(e) -> None:
    """stage_target's once-per-run failure line (the pick falls back to the stage pin)."""
    if "ladder" not in _warned:
        _warned.add("ladder")
        log.warning("area ladder failed (%r); the stage pin stands", e)
