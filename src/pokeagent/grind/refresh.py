"""Continued learning: runs/grind_atlas.json keeps sufficient statistics plus a cursor into runs/battles.jsonl, so ``refresh``
folds only the new battles. The ranked atlas is rebuilt from the stats when the build inputs (need levels, Pokecenter costs)
were saved by tools/grind_report.py. Reads runs/ only; writes runs/grind_atlas.json only."""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.grind.atlas import rank_spots
from pokeagent.grind.observed import Obs, fold, key_of, key_str, load_estimates
from pokeagent.grind.observed import FIELDS

ATLAS = "grind_atlas.json"
LEVELS = (6, 9, 12, 15, 18, 21, 24)


def load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("version") == 1:
            return d
    except (OSError, ValueError):
        pass
    return {"version": 1, "cursor": {"offset": 0}, "stats": {}, "inputs": {}, "atlas": {}}


def stats_of(doc: dict) -> dict:
    return {key_of(k): Obs(*v) for k, v in doc["stats"].items() if len(v) == len(FIELDS)}


def fold_new(doc: dict, runs_dir: Path, name_of=None) -> int:
    """Fold battles past the cursor into ``doc`` in place; returns the number folded. A shrunken log resets the cursor."""
    path, cur = runs_dir / "battles.jsonl", doc["cursor"]
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size < cur.get("offset", 0):
        cur["offset"], doc["stats"] = 0, {}
    stats, meta, est, n = stats_of(doc), {}, load_estimates(runs_dir / "xp_estimates.jsonl"), 0
    with path.open("rb") as fh:
        fh.seek(cur["offset"])
        data = fh.read()
    end = data.rfind(b"\n") + 1  # only whole lines; a half-written tail waits for next time
    for line in data[:end].splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        run = rec.get("run")
        if run not in meta:
            try:
                meta[run] = json.loads((runs_dir / run / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                meta[run] = {}
        fold(stats, rec, meta[run], name_of, est)
        n += 1
    cur["offset"] += end
    doc["stats"] = {key_str(k): o.to_list() for k, o in stats.items()}
    return n


def build_atlas(doc: dict, kb: dict, top: int = 3) -> dict:
    """{starter: {goal: {level: [spot dicts]}}} from the stats and saved inputs; {} when the inputs are missing."""
    inp, stats = doc.get("inputs") or {}, stats_of(doc)
    if not inp.get("need") or not kb:
        return {}
    species = {r["name"]: r for r in kb["species_by_dex"].values()}
    tables = {"wild": kb["wild_by_map"], "base_exp": {n: r["base_exp"] for n, r in species.items()}}
    cost = {int(k): v for k, v in (inp.get("center_cost") or {}).items()}
    names, cands = {int(k): v for k, v in (inp.get("names") or {}).items()}, inp.get("candidates") or {}
    out: dict = {}
    for sp, goals in inp["need"].items():
        growth = species.get(sp, {}).get("growth", "MEDIUM_SLOW")
        for goal, need in goals.items():
            for lvl in (x for x in LEVELS if x < need):
                spots = rank_spots(sp, lvl, need, tables, stats, cost, growth, cands.get(goal), top, names)
                out.setdefault(sp, {}).setdefault(goal, {})[str(lvl)] = [s.to_dict() for s in spots]
    return out


def save(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def refresh(runs_dir: str | Path = "runs", kb: dict | None = None) -> dict:
    """Entry point for the swarm supervisor: fold new battles, rebuild the ranked atlas, save. Returns {"folded", "offset"}.
    Never raises on missing data (no log = nothing folded)."""
    runs = Path(runs_dir)
    if not runs.is_dir():
        return {"folded": 0, "offset": 0}
    if kb is None:
        from pokeagent.knowledge.kb import ROM_KB as kb
    doc = load(runs / ATLAS)
    name_of = {k: v for k, v in (kb or {}).get("name_of_internal", {}).items()}
    n = fold_new(doc, runs, name_of)
    doc["atlas"] = build_atlas(doc, kb) or doc.get("atlas", {})
    save(runs / ATLAS, doc)
    return {"folded": n, "offset": doc["cursor"]["offset"]}
