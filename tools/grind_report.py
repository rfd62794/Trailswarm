"""Grind atlas: the best places to level up, per starter, lead level and next gym goal (read-only over runs/).

    uv run python tools/grind_report.py                         # reads runs/, writes runs/grind_atlas.json (new file)
    uv run python tools/grind_report.py --runs D --out F.json   # other runs dir / output (for tests and dry runs)

Builds the incremental stats (cursor into battles.jsonl), saves the build inputs (levels needed, Pokecenter costs from the ROM
map graph), ranks, prints the top 3 per (starter, level, goal). pokeagent.grind.refresh.refresh() later folds only new battles.
Without a ROM the Pokecenter cost is unknown (far for every spot) and the table says so.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeagent.grind import refresh as R  # noqa: E402
from pokeagent.grind.atlas import FRAMES_PER_STEP  # noqa: E402
from pokeagent.grind.centers import center_costs  # noqa: E402

STARTERS = ("BULBASAUR", "CHARMANDER", "SQUIRTLE")
GOALS = ("beat_brock", "beat_misty", "beat_surge")
# Hand-written Gen 1 geography (map ids: Route n = 11+n for 1-8; see atlas/map_names.json): the grass reachable BEFORE each gym,
# cumulative. Brock: Routes 1/2/22 + Viridian Forest. Misty: + Routes 3/4, Mt Moon, Route 24/25. Surge: + Routes 5/6/11 (no Cut needed).
_B = [12, 13, 33, 51]
_M = _B + [14, 15, 59, 60, 61, 35, 36]
GOAL_MAPS = {"beat_brock": _B, "beat_misty": _M, "beat_surge": _M + [16, 17, 22]}
SURGE_FALLBACK = [(21, "VOLTORB"), (18, "PIKACHU"), (24, "RAICHU")]  # used only if the ROM trainer table lacks LT.SURGE


def need_levels(kb: dict) -> tuple[dict, dict]:
    """({starter: {goal: lead level wanted}}, {goal: source note}) from the repo's readiness maths (required_level for the
    gyms it knows, plain readiness vs Surge's party for the rest)."""
    from pokeagent.explorer import training
    from pokeagent.goals import GOALS as LADDER
    from pokeagent.knowledge import party, readiness, trainers
    out: dict = {}
    for sp in STARTERS:
        c = party.trainer_mon(sp, 5, kb)
        if c is None:
            continue
        for goal in GOALS:
            goals = {g: True for g in LADDER[:LADDER.index(goal)]}
            lvl = None
            if goal in training.TRAIN_LEVEL_BY_GOAL:
                lvl = training.required_level(goals, 0, [c])[0]
            else:
                boss = [tuple(x) for x in (kb["trainers"].get("LT.SURGE") or [SURGE_FALLBACK])[0]]
                r = readiness.assess([c], boss, "SURGE", kb)
                lvl = r.required if r else None
            if lvl:
                out.setdefault(sp, {})[goal] = lvl
    return out, {g: "training.required_level" if g in training.TRAIN_LEVEL_BY_GOAL else "readiness.assess" for g in GOALS}


def map_graph(rom_path) -> dict:
    """{map: {neighbour: frames}}: crossing a map ~ half its long side in tiles at 16 frames/tile; a warp = 8 tiles. An ESTIMATE
    from map connections and warps (exact in-map par needs entry tiles; see pokeagent.legs.par.map_par)."""
    from pokeagent.atlas import rom_maps
    heads = rom_maps.all_headers(rom_maps.load(rom_path))
    g: dict = {}
    for m, h in heads.items():
        cross = max(h.w, h.h) * 2 // 2 * 16
        for c in h.connections:
            g.setdefault(m, {})[c.target] = cross
        for _x, _y, _dw, dest in h.warps:
            if dest in heads:
                g.setdefault(m, {})[dest] = 8 * 16
    return g


def print_trainer_section(map_id: int, label: str, ledger, party, base_exp: dict, cat, wild_spots,
                          kb=None) -> None:
    """The 'trainers worth saving or taking' section for one map, plus the area-resistance line.
    Pure renderer: everything needed comes in as arguments."""
    from pokeagent.grind.trainer_spots import rank_trainer_grinds
    from pokeagent.knowledge.area_resistance import resistance
    print(f"== trainers worth saving or taking ({label}) ==")
    grinds = rank_trainer_grinds(ledger, map_id, party, base_exp, cat, wild_spots, kb=kb)
    best_wild = max((s["xp_per_step"] if isinstance(s, dict) else s.xp_per_step for s in wild_spots), default=0.0)
    if not grinds:
        print("  (none the party beats with margin)")
    for g in grinds:
        e = g.entry
        verdict = "take" if g.xp_per_step >= best_wild else "save"
        prize = f" + {g.prize}yen" if g.prize else ""
        print(f"  {e.cls} p{e.party} ({e.x},{e.y}): {g.value:.0f} value / {g.steps:.0f} steps = "
              f"{g.xp_per_step:.2f}xp/step (xp {g.xp:.0f}{prize}, margin {g.margin:+.2f}) - {verdict} vs wild {best_wild:.2f}")
    entries = ledger.entries(map_id)
    res = resistance(party, [list(e.mons) for e in entries], None, None, kb)
    if res:
        worst = min((i for i, t in enumerate(res["trainers"]) if t["margin"] is not None),
                    key=lambda i: res["trainers"][i]["margin"], default=None)
        who = f" ({entries[worst].cls} p{entries[worst].party})" if worst is not None else ""
        weak = f", weak to: {', '.join(res['weak_to'])}" if res["weak_to"] else ""
        area = f"{res['area_margin']:+.2f}" if res["area_margin"] is not None else "n/a"
        print(f"area resistance ({label}, {len(entries)} trainers): min margin {area}{who}{weak}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(ROOT / "runs"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    runs = Path(a.runs)
    from pokeagent.atlas.rom_maps import map_name
    from pokeagent.explorer.world import POKECENTER_MAPS
    from pokeagent.knowledge.kb import ROM_KB as kb
    from pokeagent.legs.grid import rom_path
    if not kb:
        print("no kb/rom_tables.json: run tools/rom_tables.py first")
        return 1
    out_path = Path(a.out) if a.out else runs / R.ATLAS
    doc = R.load(out_path)
    n = R.fold_new(doc, runs, kb.get("name_of_internal"))
    need, _src = need_levels(kb)
    rp = rom_path()
    cost = center_costs(map_graph(rp), POKECENTER_MAPS) if rp else {}
    doc["inputs"] = {"need": need, "center_cost": {str(k): v for k, v in cost.items()}, "candidates": GOAL_MAPS,
                     "names": {str(m): map_name(m) for m in range(256)}, "rom": bool(rp)}
    doc["atlas"] = R.build_atlas(doc, kb)
    R.save(out_path, doc)
    print(f"folded {n} new battles (cursor {doc['cursor']['offset']}); pokecenter costs: {'ROM map-graph estimate' if rp else 'UNKNOWN'};"
          f" step = {FRAMES_PER_STEP} frames (assumed)\n")
    for sp, goals in doc["atlas"].items():
        for goal, lv in goals.items():
            print(f"== {sp} before {goal} (needs L{need[sp][goal]}) ==")
            for L, spots in lv.items():
                row = "  ".join(f"{s['name']} {s['xp_per_min']:.0f}xp/min risk {s['blackout']:.0%} n={s['n_obs']}"
                                + (f" ~{s['steps_to_goal'] / 225:.0f}min" if s["steps_to_goal"] else "") for s in spots)
                print(f"  L{L:>2} (+{need[sp][goal] - int(L)} lv): {row}")
    _trainer_sections(kb, need, doc["atlas"])
    return 0


def _trainer_sections(kb: dict, need: dict, atlas: dict) -> None:
    """For each starter/goal, the trainer-grind section of every candidate map with ROM trainers,
    next to that map's wild spots at the lead's lowest listed level - report only: GrindDrill does
    not change (Trainer_Grind_Pick_Directive is the follow-up)."""
    from pokeagent.atlas.rom_maps import map_name
    from pokeagent.explorer.trainer_ledger import TrainerLedger
    from pokeagent.knowledge import items_catalog, party, trainers
    cat = items_catalog.load()
    base_exp = {r.get("name"): int(r.get("base_exp") or 0) for r in kb.get("species_by_dex", {}).values()}
    for sp in STARTERS:
        for goal in GOALS:
            lead_lv = (need.get(sp) or {}).get(goal)
            levels = (atlas.get(sp) or {}).get(goal) or {}
            if not lead_lv or not levels:
                continue
            ours = [party.trainer_mon(sp, int(min(levels, key=int)), kb)]
            wild = [s for s in levels[min(levels, key=int)] if s.get("map_id") in GOAL_MAPS.get(goal, [])]
            for m in GOAL_MAPS.get(goal, []):
                rows = trainers.trainers_on(m, kb)
                if not rows:
                    continue
                ledger = TrainerLedger({m: rows})  # nothing beaten yet: the full one-time board
                spots = [s for s in wild if s.get("map_id") == m]
                print_trainer_section(m, map_name(m), ledger, [c for c in ours if c], base_exp, cat, spots, kb=kb)


if __name__ == "__main__":
    sys.exit(main())
