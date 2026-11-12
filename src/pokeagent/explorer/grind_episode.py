"""Grind episodes: the self-started grind session GrindDrill walks and paces.

Starts when the training gate (``ctx.train_need``, set by plan_goal from ``training.required_level`` /
``gate_for`` / the ``GrindBudget`` - reused, not duplicated) says the trainee is under level and
``grind.points.choose`` names a point; ends on the need reached, the budget caps, blackouts, an unfit
trainee, or hurt with no potion. While it lives, ``boundary`` pins the run to the point's map plus its
Pokecenter map (the Nugget Bridge 3<->35 ping-pong fix); a measured result folds into the ledger
(runs/grind_points.json + ``mem.data["grind_points"]``) and one row lands in runs/legs/grind_drills.jsonl.
State lives in ``ctx._grind_state["episode"]`` (context.py is at its line ceiling).

Restart discipline (PR #165 review): an episode never starts in a state that would end it next step - the
same ``_end_reason`` checks run on the would-be episode at start; ``EPISODE_COOLDOWN`` steps must pass
after any end before another start; and an episode too short or too quiet to mean anything
(< MIN_EPISODE_STEPS or zero battles) lands in the drill log as an ``aborted`` row but never reaches the
ledger's measured mean. The start/finish work runs from ``tick`` (the engine's per-step hook) -
GrindDrill.applies() only reads ``active()`` / the under-level flag: no BFS, no file writes.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from pokeagent.explorer import party_log, story_blockers, train_route
from pokeagent.explorer.economy import heal_items
from pokeagent.explorer.grind import GRIND_BATTLES, GRIND_BLACKOUTS, GRIND_STEPS
from pokeagent.explorer.perceive import lead_level, party_hp
from pokeagent.explorer.trainer_hooks import run_provenance
from pokeagent.goals import bag_contents
from pokeagent.grind import atlas, measure, stage_maps
from pokeagent.grind import points as gp
from pokeagent.grind.drill import log_episode
from pokeagent.magikarp import trainee_slot_for
from pokeagent.party_view import read_party_view
from pokeagent.ramstructs import read_party

log = logging.getLogger(__name__)

LOG = Path("runs/legs/grind_drills.jsonl")
LEDGER = Path("runs/grind_points.json")
EPISODE_COOLDOWN = 300   # steps after an episode ends before another may start (restart-thrash fix; untuned)
MIN_EPISODE_STEPS = 50   # shorter than this (or zero battles): 'aborted' row, never folded into the mean
NO_POINT_RECHECK = 200   # steps a 'no point fits' answer is cached (choose() BFS-es travel per point)
_warned: set = set()


def _warn_once(key: str, msg: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning(msg, *args)


def _state(ctx) -> dict:
    return ctx.__dict__.setdefault("_grind_state", {"heading": "RIGHT"})


def active(ctx) -> dict | None:
    return ctx.__dict__.get("_grind_state", {}).get("episode")


def boundary(ctx) -> frozenset | None:  # the map set a live episode pins the run to; None otherwise
    ep = active(ctx)
    return frozenset(ep["maps"]) if ep else None


def leaves_set(ctx, button: str, allowed) -> bool:
    """Does ``button`` step off ``allowed`` - a learned warp, a one-sighting map change (``warp_cand``),
    or a ``paths`` edge where a run recorded one?"""
    d = ctx.mem.m(ctx.view.m)
    key = f"{ctx.view.x},{ctx.view.y},{button}"
    w = d["warps"].get(key)
    if w:
        return w[0] not in allowed
    if key in d.get("warp_cand", {}):
        return True  # the map changed here once: under an episode that counts as leaving, confirmed or not
    to = (d.get("paths", {}).get(key) or {}).get("to")
    return bool(to) and to[0] not in allowed


def _levels(ctx) -> list:
    try:
        return [m.level for m in read_party(ctx.emu)]
    except Exception as e:  # noqa: BLE001
        _warn_once("levels", "grind episode: party read failed (%r); treating levels as unknown", e)
        return []


def _slot(ctx) -> int | None:
    try:  # the trainee is the named/Magikarp slot's member; the lead stands in when there is none
        return trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None))
    except Exception as e:  # noqa: BLE001
        _warn_once("slot", "grind episode: trainee slot read failed (%r); falling back to the lead", e)
        return None


def _lvl_of(ctx, levels: list, slot: int | None) -> int:
    if slot is not None and 0 <= slot < len(levels):
        return levels[slot]
    return levels[0] if levels else lead_level(ctx.emu)


def _trainee_ok(ctx) -> bool:
    try:
        from pokeagent.explorer.trainee_gate import trainee_check  # deferred: trainee_gate -> behaviours -> grind_drill -> this module
        return trainee_check(ctx).ok
    except Exception as e:  # noqa: BLE001
        _warn_once("trainee", "grind episode: trainee check failed (%r); treating the trainee as not fit", e)
        return False


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
            except (OSError, ValueError) as e:
                _warn_once("atlas", "grind episode: atlas seed skipped (%r)", e)
        st["ledger"] = led
    return led


def update(ctx) -> dict | None:
    """The per-step episode driver (the engine's ``tick`` hook calls it): end a live episode that met
    an end condition, else try to start one."""
    st = _state(ctx)
    ep = st.get("episode")
    if ep is not None:
        why = _end_reason(ctx, ep)
        if why:
            _finish(ctx, st, ep, why)
        return st.get("episode")
    if getattr(getattr(ctx, "opts", None), "drill_grind", None) is not None:
        return None  # a --drill-grind run measures the map it was told: no self-started episodes
    if start(ctx, "the training gate"):  # start() keeps the 'no point fits' cache (NO_POINT_RECHECK steps)
        return st["episode"]
    return None


def tick(ctx) -> None:  # the engine's per-step hook: never raises, never writes outside an episode end
    try:
        update(ctx)
    except Exception as e:  # noqa: BLE001
        _warn_once("tick", "grind episode: update failed (%r)", e)


def start(ctx, reason: str = "the training gate") -> bool:
    """The explicit entry point (PR #166 calls it via getattr): the same gates and EPISODE_COOLDOWN as
    update() applies. False - with the reason logged once per change - when it cannot start."""
    st = _state(ctx)
    if st.get("episode") is not None:
        return True
    if ctx.step < st.get("no_point_until", 0):
        return False  # 'no point fits' is cached for NO_POINT_RECHECK steps (choose() BFS-es per point)
    ep, why = _try_start(ctx, st)
    if ep is None:
        if why == "no grind point fits":
            st["no_point_until"] = ctx.step + NO_POINT_RECHECK
        if why != st.get("start_why"):
            ctx.log(f"[grind episode] not starting ({reason}): {why}", "res")
        st["start_why"] = why
        return False
    st["start_why"] = None
    return True


def _try_start(ctx, st: dict) -> tuple[dict | None, str | None]:
    """(episode, None) when one began, else (None, why). The same ``_end_reason`` checks run on the
    would-be episode first: it never starts in a state that would end it next step."""
    if ctx.step < st.get("cooldown_until", 0):
        return None, f"cooling down until step {st['cooldown_until']} ({EPISODE_COOLDOWN} after an end)"
    if ctx.view.battling or ctx.in_battle:
        return None, "in battle"
    need = getattr(ctx, "train_need", 0)
    if not need:
        return None, "the training gate is closed"
    if getattr(ctx, "center_intent", None):
        return None, f"inside a Pokecenter on purpose ({ctx.center_intent})"
    if getattr(ctx, "goto", None):
        return None, "a goto is in progress"
    if getattr(ctx, "proc", None) is not None:
        return None, "a procedure is running"
    levels, slot = _levels(ctx), _slot(ctx)
    lvl = _lvl_of(ctx, levels, slot)
    if not 0 < lvl < need:
        return None, f"trainee level {lvl} not under L{need}"
    pl = party_log.of(ctx)
    ep = {"slot": slot, "need": need, "battles0": ctx.battles, "blackouts0": pl.blackouts,
          "start_step": ctx.step}
    why = _end_reason(ctx, ep)  # hurt-no-potion / unfit trainee / lifted gate: never start into them
    if why:
        return None, f"would end at once ({why})"
    pt = gp.choose(_ledger(ctx, st), levels or [lvl], need, (ctx.view.m, ctx.view.x, ctx.view.y), ctx.mem,
                   trainee_slot=slot, blocked=story_blockers.blocked_tiles(ctx),
                   only_maps=stage_maps.allowed(getattr(ctx, "stage_goal", None)))
    if pt is None:
        return None, "no grind point fits"
    pt.patch = gp.patch_of(ctx.mem.data.get("maps", {}), pt.map_id) or pt.patch
    ep.update(point=pt, start_xp=pl.exp_total,
              maps={pt.map_id, pt.center_map} - {None},
              id=f"{Path(ctx.run_dir).name}@{ctx.step}", provenance=run_provenance(ctx))
    st["episode"] = ep
    ctx.log(f"[grind episode] start on {pt.name or f'0x{pt.map_id:02X}'}: trainee L{lvl} -> L{need} "
            f"({(pt.xp_per_min_measured or pt.xp_per_min_prior):.0f} xp/min expected)", "res")
    return ep, None


def _end_reason(ctx, ep: dict) -> str | None:
    if ctx.view.battling or ctx.in_battle:
        return None  # the battle behaviours own the fight; the episode waits
    lvl = _lvl_of(ctx, _levels(ctx), ep["slot"])
    if lvl >= ep["need"]:
        return f"trainee reached L{ep['need']}"
    if not getattr(ctx, "train_need", 0):
        return "the training gate lifted"
    if not _trainee_ok(ctx):
        return "the trainee is not fit to train"
    pl = party_log.of(ctx)
    if pl.blackouts - ep["blackouts0"] >= GRIND_BLACKOUTS:
        return f"{GRIND_BLACKOUTS} blackouts"
    if ctx.battles - ep["battles0"] >= GRIND_BATTLES:
        return f"{GRIND_BATTLES} battles"
    if ctx.step - ep["start_step"] >= GRIND_STEPS:
        return f"{GRIND_STEPS} steps"
    hp, mx = party_hp(ctx.emu)
    if (mx and hp / mx < train_route.MIN_HP_FRACTION or read_party_view(ctx.emu).any_fainted) \
            and not heal_items.heal_count(bag_contents(ctx.emu)):
        return "hurt with no potion"
    pt = ep.get("point")
    if pt is not None and ctx.view.m != pt.map_id:  # a story blocker met on the way cuts the point off: the story goal goes first
        wall = story_blockers.blocked_tiles(ctx)
        if wall and not story_blockers.reachable(ctx.mem.data.get("maps", {}), (ctx.view.m, ctx.view.x, ctx.view.y), pt.map_id, wall):
            return "a story blocker bars the way to the point"
    return None


def _xp_gained(ctx, ep: dict) -> int:
    """Measured XP: the levels.jsonl exp-total delta between the episode's bounds (replayable from the
    run record); the in-RAM party_log total stands in only when the run has no levels rows."""
    rows = list(measure.read_jsonl(Path(ctx.run_dir) / "levels.jsonl"))
    if rows:
        return measure.xp_gained_in_episode(rows, ep["start_step"], ctx.step)
    return max(0, party_log.of(ctx).exp_total - ep["start_xp"])


def _party_changed(ctx, ep: dict) -> bool:
    rows = list(measure.read_jsonl(Path(ctx.run_dir) / "levels.jsonl"))
    return measure.party_changed_in_episode(rows, ep["start_step"], ctx.step)


def _finish(ctx, st: dict, ep: dict, why: str) -> None:
    st["episode"] = None
    st["cooldown_until"] = ctx.step + EPISODE_COOLDOWN
    pl = party_log.of(ctx)
    steps, battles = max(0, ctx.step - ep["start_step"]), max(0, ctx.battles - ep["battles0"])
    xp, blk = _xp_gained(ctx, ep), max(0, pl.blackouts - ep["blackouts0"])
    aborted = steps < MIN_EPISODE_STEPS or battles == 0
    if not aborted and _party_changed(ctx, ep):  # a deposit/release mid-episode makes the exp-total delta meaningless
        aborted, why = True, f"{why}; party membership changed mid-episode"
    pt = ep["point"]
    if not aborted:  # a real measurement: fold it into the ledger and the shared swarm table
        pt = gp.episode_result(pt, xp, max(1, steps), blk, provenance=ep["provenance"], ep_id=ep["id"])
        _ledger(ctx, st).upsert(pt)
        try:
            _ledger(ctx, st).save()
            ctx.mem.data["grind_points"] = _ledger(ctx, st).to_table()  # the swarm merges this table like "trainers"
        except OSError as e:
            ctx.log(f"[grind points not written: {e!r}]", "res")
    per_min = xp / (steps / atlas.STEPS_PER_MIN) if steps else 0.0
    rec = {"source": "episode", "kind": "grind_episode", "run": Path(ctx.run_dir).name, "map": pt.map_id,
           "name": pt.name, "start_step": ep["start_step"], "end_step": ctx.step, "steps": steps,
           "battles": battles, "xp_gained": xp, "blackouts": blk, "xp_per_min": round(per_min, 3),
           "status": "aborted" if aborted else "measured",
           "reason": why, "provenance": ep["provenance"], "t": time.time()}
    try:
        log_episode(rec, LOG)
    except OSError as e:
        ctx.log(f"[grind episode row not written: {e!r}]", "res")
    ctx.log(f"[grind episode] {'abort' if aborted else 'end'} on {pt.name or f'0x{pt.map_id:02X}'} ({why}): "
            f"{xp:.0f} xp in {steps} steps ({per_min:.0f}/min), {blk} blackouts", "res")
