"""Grind episodes: the self-started grind session GrindDrill walks and paces.

Starts when the training gate (``ctx.train_need``, set by plan_goal from ``training.required_level`` /
``gate_for`` / the ``GrindBudget`` - reused, not duplicated) says the trainee is under level and
``grind.points.choose`` names a point; ends on the need reached, the budget caps, blackouts, or hurt
with no potion. While it lives, ``boundary`` pins the run to the point's map plus its Pokecenter map
(the Nugget Bridge 3<->35 ping-pong fix); the measured result folds into the ledger
(runs/grind_points.json + ``mem.data["grind_points"]``) and one row lands in runs/legs/grind_drills.jsonl.
State lives in ``ctx._grind_state["episode"]`` (context.py is at its line ceiling).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.explorer import party_log, train_route
from pokeagent.explorer.economy import heal_items
from pokeagent.explorer.grind import GRIND_BATTLES, GRIND_BLACKOUTS, GRIND_STEPS
from pokeagent.explorer.perceive import lead_level, party_hp
from pokeagent.explorer.trainer_hooks import run_provenance
from pokeagent.goals import bag_contents
from pokeagent.grind import points as gp
from pokeagent.grind.drill import log_episode
from pokeagent.magikarp import trainee_slot_for
from pokeagent.ramstructs import read_party

LOG = Path("runs/legs/grind_drills.jsonl")
LEDGER = Path("runs/grind_points.json")


def active(ctx) -> dict | None:
    return ctx.__dict__.get("_grind_state", {}).get("episode")


def boundary(ctx) -> frozenset | None:  # the map set a live episode pins the run to; None otherwise
    ep = active(ctx)
    return frozenset(ep["maps"]) if ep else None


def leaves_set(ctx, button: str, allowed) -> bool:  # does ``button`` step onto a warp that exits ``allowed``
    w = ctx.mem.m(ctx.view.m)["warps"].get(f"{ctx.view.x},{ctx.view.y},{button}")
    return bool(w) and w[0] not in allowed


def _levels(ctx) -> list:
    try:
        return [m.level for m in read_party(ctx.emu)]
    except Exception:  # noqa: BLE001
        return []


def _ledger(ctx, st: dict):
    led = st.get("ledger")  # loaded once: the file, else the swarm table, else atlas priors
    if led is None:
        led = gp.GrindLedger.load(LEDGER)
        if not led.points:
            led = gp.GrindLedger.from_table(ctx.mem.data.get("grind_points"), path=LEDGER)
        if not led.points:
            try:
                doc = json.loads(Path("runs/grind_atlas.json").read_text(encoding="utf-8"))
                from pokeagent.knowledge.kb import ROM_KB
                led.seed_from_atlas(doc, kb=ROM_KB, maps=ctx.mem.data.get("maps"))
            except (OSError, ValueError):
                pass
        st["ledger"] = led
    return led


def update(ctx) -> dict | None:  # start or continue the run's episode (GrindDrill.applies calls this)
    st = ctx.__dict__.setdefault("_grind_state", {"heading": "RIGHT"})
    ep = st.get("episode")
    if ep is not None:
        why = _end_reason(ctx, ep)
        if why:
            _finish(ctx, st, ep, why)
            return None
        return ep
    need = getattr(ctx, "train_need", 0)
    if ctx.view.battling or ctx.in_battle or not need:
        return None
    levels = _levels(ctx)
    try:  # the trainee is the named/Magikarp slot's member; the lead stands in when there is none
        slot = trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None))
    except Exception:  # noqa: BLE001
        slot = None
    lvl = levels[slot] if slot is not None and slot < len(levels) else (levels[0] if levels else lead_level(ctx.emu))
    if not 0 < lvl < need:
        return None
    led = _ledger(ctx, st)
    pt = gp.choose(led, levels or [lvl], need, (ctx.view.m, ctx.view.x, ctx.view.y), ctx.mem, trainee_slot=slot)
    if pt is None:
        return None
    pt.patch = gp.patch_of(ctx.mem.data.get("maps", {}), pt.map_id) or pt.patch
    pl = party_log.of(ctx)
    st["episode"] = ep = {"point": pt, "start_step": ctx.step, "start_xp": pl.exp_total, "battles0": ctx.battles,
                          "blackouts0": pl.blackouts, "need": need, "slot": slot,
                          "maps": {pt.map_id, pt.center_map} - {None},
                          "id": f"{Path(ctx.run_dir).name}@{ctx.step}", "provenance": run_provenance(ctx)}
    ctx.log(f"[grind episode] start on {pt.name or f'0x{pt.map_id:02X}'}: trainee L{lvl} -> L{need} "
            f"({(pt.xp_per_min_measured or pt.xp_per_min_prior):.0f} xp/min expected)", "res")
    return ep


def _end_reason(ctx, ep: dict) -> str | None:
    if ctx.view.battling or ctx.in_battle:
        return None  # the battle behaviours own the fight; the episode waits
    levels, slot = _levels(ctx), ep["slot"]
    lvl = levels[slot] if slot is not None and slot < len(levels) else (levels[0] if levels else lead_level(ctx.emu))
    if lvl >= ep["need"]:
        return f"trainee reached L{ep['need']}"
    if not getattr(ctx, "train_need", 0):
        return "the training gate lifted"
    pl = party_log.of(ctx)
    if pl.blackouts - ep["blackouts0"] >= GRIND_BLACKOUTS:
        return f"{GRIND_BLACKOUTS} blackouts"
    if ctx.battles - ep["battles0"] >= GRIND_BATTLES:
        return f"{GRIND_BATTLES} battles"
    if ctx.step - ep["start_step"] >= GRIND_STEPS:
        return f"{GRIND_STEPS} steps"
    hp, mx = party_hp(ctx.emu)
    if mx and hp / mx < train_route.MIN_HP_FRACTION and not heal_items.heal_count(bag_contents(ctx.emu)):
        return "hurt with no potion"
    return None


def _finish(ctx, st: dict, ep: dict, why: str) -> None:
    st["episode"] = None
    pl = party_log.of(ctx)
    xp, blk = max(0, pl.exp_total - ep["start_xp"]), max(0, pl.blackouts - ep["blackouts0"])
    steps = max(1, ctx.step - ep["start_step"])
    pt = gp.episode_result(ep["point"], xp, steps, blk, provenance=ep["provenance"], ep_id=ep["id"])
    _ledger(ctx, st).upsert(pt)
    try:
        _ledger(ctx, st).save()
        ctx.mem.data["grind_points"] = _ledger(ctx, st).to_table()  # the swarm merges this table like "trainers"
    except OSError as e:
        ctx.log(f"[grind points not written: {e!r}]", "res")
    per_min = xp / (steps / gp.STEPS_PER_MIN)
    rec = {"source": "episode", "kind": "grind_episode", "run": Path(ctx.run_dir).name, "map": pt.map_id,
           "name": pt.name, "start_step": ep["start_step"], "end_step": ctx.step, "steps": steps,
           "xp_gained": xp, "blackouts": blk, "xp_per_min": round(per_min, 3),
           "reason": why, "provenance": ep["provenance"], "t": time.time()}
    try:
        log_episode(rec, LOG)
    except OSError as e:
        ctx.log(f"[grind episode row not written: {e!r}]", "res")
    ctx.log(f"[grind episode] end on {pt.name or f'0x{pt.map_id:02X}'} ({why}): "
            f"{xp:.0f} xp in {steps} steps ({per_min:.0f}/min), {blk} blackouts", "res")
