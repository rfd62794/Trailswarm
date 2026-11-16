"""The area ladder: which of a stage's allowed maps to train on, by expected XP per step.

Each stage's grind map used to be a hard pin (encounters.TRAIN_MAP). ``pick`` ranks the stage's
candidate maps - atlas Spot rows the caller already restricted to allowed AND known-reachable
maps - solo-viable rungs first, the best overall else. A switch needs SWITCH_GAIN over the
current rung, a hop inside MAX_TRAVEL_STEPS and MIN_DWELL_STEPS since the last switch, so two
near-equal maps never ping-pong. ``known_rungs`` is the reachability filter (visited AND a
learned route); ``decide`` wraps the pick in the run's cache {"map", "since"}. Pure: grind only.
"""
from __future__ import annotations

from pokeagent.grind.points import FAR_TRAVEL, travel_steps

SWITCH_GAIN = 1.25        # a new map must beat the current one's xp_per_step by 25% (untuned; named, not config)
MIN_DWELL_STEPS = 600     # no switch within this many planning steps of the last one (untuned)
MAX_TRAVEL_STEPS = 320    # same cap as Level_Banded: a map further than this is not a rung


def known_rungs(maps: dict, here, candidates) -> set:
    """candidates the run can actually reach: the map was visited AND a learned route reaches it
    (training_ctl.target.known's rule, kept grind-pure: the maps dict and the pos in, a set out).
    A map never visited or with no learned route is not a rung."""
    return {m for m in candidates
            if (maps.get(str(m)) or {}).get("visited") and travel_steps(maps, here, m) < FAR_TRAVEL}


def pick(spots: list, solo_ok, current: int | None, travel, since_switch: int) -> int | None:
    """The map to train on: among `spots` (atlas Spot rows already restricted to allowed AND known maps) the
    one with the best xp_per_step that `solo_ok(map_id)` is True for; if none is solo-ok, the best overall
    (today's behaviour). Stay on `current` unless a rung beats it by SWITCH_GAIN, travel(map) <=
    MAX_TRAVEL_STEPS and since_switch >= MIN_DWELL_STEPS. None when `spots` is empty (the caller then
    keeps the TRAIN_MAP pin: a missing table never sends the run somewhere new)."""
    if not spots:
        return None
    pool = [s for s in spots if solo_ok(s.map_id)] or list(spots)
    near = [s for s in pool if s.map_id == current or travel(s.map_id) <= MAX_TRAVEL_STEPS]
    if not near:
        return None
    best = max(near, key=lambda s: (s.xp_per_step, s.map_id == current))
    cur = next((s for s in pool if s.map_id == current), None)
    if cur is None or best.map_id == current:
        return best.map_id                        # a first pick, or current is no rung, or a tie stays
    gain = best.xp_per_step / cur.xp_per_step if cur.xp_per_step > 0 else float("inf")
    return best.map_id if gain >= SWITCH_GAIN and since_switch >= MIN_DWELL_STEPS else current


def decide(lad: dict, spots: list, solo_ok, travel, at_step: int) -> tuple[int | None, int | None]:
    """pick() with the pick cache ``lad`` = {"map", "since"} (ctx.__dict__["ladder"]) stamped on a switch:
    the rung is sticky and this is the one writer. Returns (map or None, the previous rung or None) so the
    caller can log the switch."""
    old = lad.get("map")
    out = pick(spots, solo_ok, old, travel, at_step - lad.get("since", at_step))
    if out is not None and out != old:
        lad["map"], lad["since"] = out, at_step
    return out, old
