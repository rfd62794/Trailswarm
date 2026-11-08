"""The thin ctx glue for explorer.trainer_ledger: building the run's ledger, per-step upkeep, the
battle-win and talk hooks, per-run persistence and the beaten_trainers(ctx) seam Goal Procedures
calls. Split out of trainer_ledger.py to keep every new module under 300 lines; everything here is
re-exported from trainer_ledger and never raises.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

from pokeagent.explorer.trainer_ledger import FLAG_LEN, FLAG_LO, MATCH_MAX_DIST, TrainerLedger, load_flag_bits
from pokeagent.knowledge import items_catalog, trainers
from pokeagent.knowledge.kb import table

log = logging.getLogger(__name__)

TALK_MATCH_DIST = 1  # a talk probe starts only for an NPC recorded within this many tiles of a ROM placement
TRAINER_XP = 1.5  # xp_gain's trainer multiplier (grind.xpmath; duplicated: grind is not an explorer layer)


def run_provenance(ctx) -> str:
    """``organic`` | ``synthetic`` | ``unknown`` from the start state's ``<state>.fp.json`` lineage
    (statefp, PR #147 - read directly because statefp is not an explorer layer). ``promoted`` earned
    organic trust; a missing/unreadable record is ``unknown``, never guessed."""
    state = getattr(ctx.opts, "state_path", "") or ""
    if not state:
        return "unknown"
    try:
        fp = json.loads(Path(str(state) + ".fp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    lin = fp.get("lineage") or ("synthetic" if fp.get("synthetic") else None)
    return {"organic": "organic", "promoted": "organic", "synthetic": "synthetic"}.get(lin, "unknown")


def ledger_for(ctx) -> TrainerLedger:
    """The run's ledger, made on first use: flag table, restored per-run file, person-tile wiring."""
    led = getattr(ctx, "trainer_ledger", None)
    if led is not None:
        return led
    led = TrainerLedger({}, load_flag_bits(), provenance=run_provenance(ctx))
    ctx.trainer_ledger = led
    ctx.mem.beaten_tiles = led.beaten_tiles  # memory_nav._person_tile treats a beaten tile as a person's
    ensure_maps(ctx)
    led.restore(Path(ctx.run_dir) / "trainers.json")
    return led


def ensure_maps(ctx) -> None:
    """Register ROM placements for every visited map plus the current one, and share the static rows."""
    led = ctx.trainer_ledger
    for key in (*ctx.mem.data.get("maps", {}), ctx.view.m):
        try:
            mid = int(key)
        except (TypeError, ValueError):
            continue
        if led.known(mid):
            continue
        rows = trainers.trainers_on(mid)
        led.add_map(mid, rows)
        if rows:
            share_static(ctx, mid)


def share_static(ctx, map_id: int) -> None:
    """The shared, per-ROM half of an entry into ``mem.data["trainers"]`` - NEVER the beaten state."""
    rows = ctx.mem.data.setdefault("trainers", {})
    cat = items_catalog.load()  # None without a ROM: prize/XP stay None
    base_exp = {r.get("name"): int(r.get("base_exp") or 0) for r in table(None, "species_by_dex").values()}
    for e in ctx.trainer_ledger.entries(map_id):
        key = f"{map_id}:{e.idx}"
        if key not in rows:
            xp = sum(int(base_exp.get(sp, 0)) * lv / 7 * TRAINER_XP for lv, sp in e.mons)
            rows[key] = {"cls": e.cls, "party": e.party,
                         "prize": items_catalog.trainer_prize(cat, e.cls, e.party) if cat else None,
                         "xp": xp or None, "flag_bit": list(e.flag_bit) if e.flag_bit else None,
                         "provenance": ctx.trainer_ledger.provenance}


def beaten_trainers(ctx) -> set[tuple[int, int, int]]:
    """{(map, x, y)} of beaten ROM placements for THIS run - the seam Goal_Procedures' AfterVictory /
    ProcedureRunner call. Never raises; an empty set when there is no ROM data."""
    try:
        return ledger_for(ctx).beaten_tiles()
    except Exception as exc:  # noqa: BLE001
        _log_skip(ctx, exc)
        return set()


def _log_skip(ctx, exc) -> None:
    """Report a swallowed ledger failure through ctx.log; if the logger itself fails, the module logger."""
    try:
        ctx.log(f"[trainer_ledger skipped: {exc!r}]", "res")
    except Exception as log_exc:  # noqa: BLE001
        log.warning("trainer_ledger skipped: %r (ctx.log failed: %r)", exc, log_exc)


def current_party(ctx):
    """our_party() with each member's HP replaced by its CURRENT hp (a hurt party sims worse). [] when the
    read fails or there is no ROM data; the reason is logged once per battle number."""
    from pokeagent.knowledge.party import our_party
    from pokeagent.ramstructs import read_party
    reason = None
    try:
        cur = [m.hp for m in read_party(ctx.emu)]
        party = our_party(ctx.emu)
        out = [replace(c, hp=cur[i]) for i, c in enumerate(party) if i < len(cur)]
        if out:
            return out
        reason = "no party data (ROM tables missing?)"
    except Exception as exc:  # noqa: BLE001
        reason = repr(exc)
    led = ledger_for(ctx)
    if led.party_warned != (ctx.battles, reason):
        led.party_warned = (ctx.battles, reason)
        _log_skip(ctx, f"trainer hunt cannot read the party, every trainer is ignore: {reason}")
    return []


def avoid_pass(ctx, led) -> None:
    """Routing-only sight-line avoidance for whatever destination is being walked to (an explicit goto or
    the committed frontier tile) - independent of which behaviour is walking, so a planner goto is
    covered. Re-made only when (map, destination, unbeaten set) changes or the block expires; the
    "avoiding ..." line is logged once per such change, never per step."""
    from pokeagent.explorer import trainer_route
    from pokeagent.explorer.world import WorldGraph
    v = ctx.view
    if v.battling or v.box or ctx.proc is not None:
        return
    dest = tuple(ctx.goto) if ctx.goto else ctx.frontier_target
    unbeaten = tuple(e.idx for e in led.entries(v.m) if e.state != "beaten")
    if not dest or not unbeaten:
        return
    key = (v.m, dest, unbeaten)
    changed = led.avoid_key != key
    if not changed and ctx.frame < led.avoid_until:
        return
    led.avoid_key, led.avoid_until = key, ctx.frame + trainer_route.AVOID_BLOCK_FRAMES
    player = (v.m, v.x, v.y)
    g = WorldGraph(ctx.mem.data["maps"])
    g.blocked_now = frozenset(ctx.mem.temp_blocked)
    goal_fn = (lambda n, d=dest: n == d)
    p = g.path(player, goal_fn)
    opts = trainer_route.options(led, v.m, player, g, len(p) if p is not None else 0, current_party(ctx))
    for o in opts:
        if o.action == "avoid":
            trainer_route.block_sight(ctx, o, goal_fn, quiet=not changed)


def tick(ctx) -> None:
    """Per-step ledger upkeep: new maps, talk probes, the every-50-steps flag sync, persistence."""
    try:
        led = ledger_for(ctx)
        ensure_maps(ctx)
        battling = bool(getattr(ctx.view, "battling", False) or ctx.in_battle)
        changed = led.tick(ctx.step, battling=battling, text_open=bool(getattr(ctx.view, "box", False)))
        if led.needs_flags() and led.flag_due(ctx.step):
            led.sync_flags(ctx.emu.read_range(FLAG_LO, FLAG_LEN))  # read-only: flags are never written
            changed = True
        if changed:
            led.save(Path(ctx.run_dir) / "trainers.json")
        avoid_pass(ctx, led)
    except Exception as exc:  # noqa: BLE001  the ledger must never end a run
        _log_skip(ctx, exc)


def _positions(npc: dict) -> list[tuple[int, int]]:
    """Every tile an NPC entry was seen on (positions keys plus ``last``/``x``/``y``)."""
    out = []
    for p in (npc.get("positions") or {}):
        try:
            out.append(tuple(int(v) for v in str(p).split(",")[:2]))
        except ValueError:
            continue
    for v in (npc.get("last"), (npc.get("x"), npc.get("y"))):
        if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] is not None:
            out.append((int(v[0]), int(v[1])))
    return out


def _enemy_names(ctx) -> list[str] | None:
    """The battle record's enemy species as names (the match tie-break); None when unknown."""
    bl = ctx.battle_log or {}
    sp = bl.get("enemy_species") or (bl.get("enemy") or [None])[0]
    name = table(None, "name_of_internal").get(str(sp)) if sp else None
    return [name] if name else None


def note_battle_won(ctx, npc: dict, battle_map: int) -> None:
    """battle.py calls this where it sets ``ctx.trainer_npc["beaten"]``: pin the win to a placement."""
    try:
        led = ledger_for(ctx)
        positions = _positions(npc)
        idx = led.match(battle_map, positions, _enemy_names(ctx))
        if idx is None:
            ctx.log(f"[trainer_ledger: no ROM placement within {MATCH_MAX_DIST} of {positions[:3]} on map {battle_map}]", "res")
            return
        led.mark_beaten(battle_map, idx, "battle_log", ctx.step)
        e = led.entries(battle_map)[idx]
        ctx.log(f"[trainer_ledger: {e.cls} p{e.party} ({e.x},{e.y}) beaten (battle_log)]", "res")
        led.save(Path(ctx.run_dir) / "trainers.json")
    except Exception as exc:  # noqa: BLE001
        _log_skip(ctx, exc)


def note_talk(ctx, before, npc: dict, got_text: bool) -> None:
    """record_interaction's A press at an NPC: arm the talk probe for the ROM placement the NPC IS (an NPC
    recorded within TALK_MATCH_DIST tiles of it - never a bystander merely near an unbeaten trainer)."""
    try:
        if not got_text or npc is None:
            return
        led = ledger_for(ctx)
        idx = led.match(before[0], _positions(npc), max_dist=TALK_MATCH_DIST)
        if idx is not None:
            led.note_talk(before[0], idx, ctx.step)
    except Exception as exc:  # noqa: BLE001
        _log_skip(ctx, exc)


def save_run(ctx) -> None:
    """Persist at shutdown (demos.shutdown), same as the battle-end cadence."""
    led = getattr(ctx, "trainer_ledger", None)
    if led is not None:
        try:
            led.save(Path(ctx.run_dir) / "trainers.json")
        except Exception as exc:  # noqa: BLE001  a failed shutdown write loses the run's ledger: say so
            _log_skip(ctx, f"save_run failed, ledger not written: {exc!r}")
