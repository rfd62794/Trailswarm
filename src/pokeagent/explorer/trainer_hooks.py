"""The thin ctx glue for explorer.trainer_ledger: building the run's ledger, per-step upkeep, the
battle-win and talk hooks, per-run persistence and the beaten_trainers(ctx) seam Goal Procedures
calls. Split out of trainer_ledger.py to keep every new module under 300 lines; everything here is
re-exported from trainer_ledger and never raises.
"""
from __future__ import annotations

from pathlib import Path

from pokeagent.explorer.trainer_ledger import FLAG_LEN, MATCH_MAX_DIST, TrainerLedger, load_flag_bits
from pokeagent.grind.xpmath import xp_gain
from pokeagent.knowledge import items_catalog, trainers
from pokeagent.knowledge.kb import table
from pokeagent.ramlab.flags import FLAG_LO


def run_provenance(ctx) -> str:
    """``organic`` | ``synthetic`` | ``unknown`` from the start state's fingerprint lineage (PR #147).
    ``promoted`` earned organic trust; a missing/unreadable record is ``unknown``, never guessed."""
    state = getattr(ctx.opts, "state_path", "") or ""
    if not state:
        return "unknown"
    try:
        from pokeagent import statefp
        lin = statefp.lineage(Path(state))
    except Exception:  # noqa: BLE001
        return "unknown"
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
            xp = sum(xp_gain(base_exp.get(sp, 0), lv, trainer=True) for lv, sp in e.mons)
            rows[key] = {"cls": e.cls, "party": e.party,
                         "prize": items_catalog.trainer_prize(cat, e.cls, e.party) if cat else None,
                         "xp": xp or None, "flag_bit": list(e.flag_bit) if e.flag_bit else None,
                         "provenance": ctx.trainer_ledger.provenance}


def beaten_trainers(ctx) -> set[tuple[int, int, int]]:
    """{(map, x, y)} of beaten ROM placements for THIS run - the seam Goal_Procedures' AfterVictory /
    ProcedureRunner call. Never raises; an empty set when there is no ROM data."""
    try:
        return ledger_for(ctx).beaten_tiles()
    except Exception:  # noqa: BLE001
        return set()


def _log_skip(ctx, exc) -> None:
    try:
        ctx.log(f"[trainer_ledger skipped: {exc!r}]", "res")
    except Exception:  # noqa: BLE001
        pass


def tick(ctx) -> None:
    """Per-step ledger upkeep: new maps, talk probes, the every-50-steps flag sync, persistence."""
    try:
        led = ledger_for(ctx)
        ensure_maps(ctx)
        battling = bool(getattr(ctx.view, "battling", False) or ctx.in_battle)
        changed = led.tick(ctx.step, battling=battling)
        if led.needs_flags() and led.flag_due(ctx.step):
            led.sync_flags(ctx.emu.read_range(FLAG_LO, FLAG_LEN))  # read-only: flags are never written
            changed = True
        if changed:
            led.save(Path(ctx.run_dir) / "trainers.json")
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
    """record_interaction's A press at an NPC: match it to a placement and arm the talk probe."""
    try:
        if not got_text or npc is None:
            return
        led = ledger_for(ctx)
        idx = led.match(before[0], _positions(npc))
        if idx is not None:
            led.note_talk(before[0], idx, ctx.step)
    except Exception:  # noqa: BLE001
        pass


def save_run(ctx) -> None:
    """Persist at shutdown (demos.shutdown), same as the battle-end cadence."""
    led = getattr(ctx, "trainer_ledger", None)
    if led is not None:
        try:
            led.save(Path(ctx.run_dir) / "trainers.json")
        except Exception:  # noqa: BLE001
            pass
