"""One place to train: keeps grind episodes and the team_ready / gym-hold train_route on the same map.

Slice 5 (real-ROM seed 12, Cerulean ping-pong): team_ready walked train_route to Route 24 while a grind episode
on Viridian Forest pinned frontier to the episode's maps, so frontier refused the Cerulean (20,0) UP crossing
and plan_goal walked back, 7.2% of all steps. The rule, both directions:

* a grind episode may START only on the map train_route trains at while team_ready is training (Route 24);
  no point there -> no episode. The gym hold alone does not narrow episodes;
* an episode already live (begun before the stage) wins: the retarget now lives with the episode
  (GrindDrill walks it).
"""
from __future__ import annotations

from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.explorer.training_ctl import release
from pokeagent.explorer.world import WorldGraph
from pokeagent.grind import area_ladder, stage_maps
from pokeagent.grind.points import FAR_TRAVEL, travel_steps
from pokeagent.knowledge.encounters import TRAIN_MAP, map_name, species_on

ROUTE_MAPS = range(0x0C, 0x25)  # overworld route ids (Route 1 .. Route 25): caves and towns are never the fallback
MIN_GRASS_TILES = 8             # encounter-proven tiles a map needs to be a patch worth walking to
TRAINEE_REACH = 12              # untuned: a map whose weakest wild level is more than this above the trainee is too hard
REVALIDATE_STEPS = 50           # the sticky pick is re-checked for a route this often
NO_BATTLE_WINDOW = 600          # steps with no new battle before the pick is dropped (and not repicked this stage)


def suits(trainee_level: int | None, map_id: int) -> bool:
    """The map's wild table (encounters.species_on) fits the trainee: its top level is not below the trainee (no XP)
    and its weakest is within TRAINEE_REACH above it. No level or no table = not suitable (never a guess)."""
    lv = list(species_on(map_id).values())
    if not trainee_level or not lv:
        return False
    return max(hi for _, hi, _ in lv) >= trainee_level and min(lo for lo, _, _ in lv) <= trainee_level + TRAINEE_REACH


def _trainee_level(ctx) -> int | None:
    from pokeagent.explorer import grind_episode  # deferred: grind_episode imports this module
    try:
        lvl = grind_episode._lvl_of(ctx, grind_episode._levels(ctx), grind_episode._slot(ctx))
    except Exception:  # noqa: BLE001
        return None
    return lvl or None


def _reachable(ctx, mid: int) -> bool:
    g = WorldGraph(ctx.mem.data.get("maps", {}))
    g.blocked_now = frozenset(ctx.mem.temp_blocked)
    return g.path(ctx.pos(), lambda n: n[0] == mid) is not None or ctx.pos()[0] == mid


def _kept(ctx, cache: dict, stage) -> int | None:
    """The cached pick when it is still good, else None (cache cleared). Dropped when the stage changed, the route is
    cut off (re-checked every REVALIDATE_STEPS), or NO_BATTLE_WINDOW steps passed with no new battle (it is then barred
    for this stage so the next pick differs)."""
    if cache.get("stage") != stage or cache.get("map") is None:
        return None
    step, battles = getattr(ctx, "step", 0), getattr(ctx, "battles", 0)
    if battles != cache.get("battles"):
        cache["battles"], cache["since"] = battles, step
    if step - cache.get("since", step) >= NO_BATTLE_WINDOW:
        cache.setdefault("barred", set()).add(cache["map"])
        ctx.log(f"[train target: no battle on {map_name(cache['map'])} for {NO_BATTLE_WINDOW} steps - picking again]", "res")
        cache["map"] = None
        return None
    if step - cache.get("checked", step) >= REVALIDATE_STEPS:
        cache["checked"] = step
        if not _reachable(ctx, cache["map"]):
            cache["map"] = None
            return None
    return cache["map"]


def nearest_grass(ctx) -> int | None:
    """The nearest learned route map with proven grass that SUITS the trainee (see ``suits``), or None. The pick is
    sticky per stage but re-validated (``_kept``). None when nothing suitable is known: the caller falls back."""
    stage = getattr(ctx, "stage_goal", None)
    cache = ctx.__dict__.setdefault("near_grass", {})
    kept = _kept(ctx, cache, stage)
    if kept is not None:
        return kept
    if cache.get("stage") != stage:
        cache.clear()
    maps, here, lvl = ctx.mem.data.get("maps", {}), ctx.pos(), _trainee_level(ctx)
    barred = cache.get("barred", set())
    best, unsuited = None, 0
    for mid in ROUTE_MAPS:
        d = maps.get(str(mid)) or {}
        if mid in barred or not d.get("visited") or len(d.get("encounters") or {}) < MIN_GRASS_TILES:
            continue
        steps = travel_steps(maps, here, mid)
        if steps >= FAR_TRAVEL:
            continue
        if not suits(lvl, mid):
            unsuited += 1
            continue
        if best is None or (steps, mid) < best:
            best = (steps, mid)
    if best is None:
        if unsuited and cache.get("why") != (stage, lvl):
            cache["why"] = (stage, lvl)
            ctx.log(f"[train target: {unsuited} known grass map(s) do not suit a L{lvl} trainee - falling back to Route 24]", "res")
        return None
    step = getattr(ctx, "step", 0)
    cache.update(stage=stage, map=best[1], since=step, checked=step, battles=getattr(ctx, "battles", 0))
    return best[1]


def _pinned(ctx, stage) -> int:
    """The no-ladder answer. Order: the pre-Brock stage map; a stage pinned in TRAIN_MAP keeps its Route 24 default;
    any other stage (everything after Misty) trains at the nearest SUITABLE proven grass, else Route 24."""
    if stage_maps.allowed(stage) and stage in TRAIN_MAP:
        return TRAIN_MAP[stage]
    if stage in TRAIN_MAP:
        return ROUTE24
    return nearest_grass(ctx) or ROUTE24


def stage_target(ctx) -> int:
    """The map train_route walks to for the current stage: the area ladder's rung when it answers (stages with
    rungs only), else ``_pinned``. Any ladder failure falls back to the pin."""
    stage = getattr(ctx, "stage_goal", None)
    maps, here = ctx.mem.data.get("maps", {}), ctx.pos()
    try:
        spots, slot = release.ladder_spots(ctx, stage, maps, here)
        out, old = area_ladder.decide(ctx.__dict__.setdefault("ladder", {}), spots,
                                      lambda m: release.verdict(ctx, slot, m),
                                      lambda m: travel_steps(maps, here, m), ctx.step)
        if out is not None:
            pin = _pinned(ctx, stage)
            if out != old and (old is not None or out != pin):
                xp = {s.map_id: s.xp_per_step for s in spots}
                ctx.log(f"[ladder] {map_name(old or pin)} -> {map_name(out)} (xp/step {xp.get(old, 0.0):.1f} -> {xp.get(out, 0.0):.1f})", "res")
            return out
    except Exception as e:  # noqa: BLE001
        release.warn_ladder(e)
    return _pinned(ctx, stage)


def stage_training(ctx) -> bool:
    """True while team_ready trains (plan_goal's train_route_live). The gym hold alone does NOT narrow episodes:
    pre-Brock the Pewter hold must keep the full PRE_BROCK set (Viridian Forest), and later gyms must not be
    pinned to Route 24 (review of 376f738)."""
    return bool(getattr(ctx, "train_route_live", False))


def only_maps(ctx) -> frozenset | None:
    """``grind.points.choose``'s ``only_maps`` for a new episode: the stage list, narrowed to the train
    target while the stage is training (None = unrestricted)."""
    allowed = stage_maps.allowed(getattr(ctx, "stage_goal", None))
    if not stage_training(ctx):
        return allowed
    tgt = stage_target(ctx)
    return frozenset({tgt}) if allowed is None else frozenset(allowed & {tgt}) or frozenset({tgt})
