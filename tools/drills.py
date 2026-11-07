"""Leg and grind drills: what is worth drilling and how the drills did (read-only).

    uv run python tools/drills.py report                     # worst legs, drilled counts, before/after, grind XP/min vs the atlas
    uv run python tools/drills.py report --runs-dir runs --top 10

Run a drill with tools/explore_headless.py (or explore_demo.py) --drill-leg 12:5,6->12,12 / --drill-grind 13 after a run with
--save-leg-states has made entry states; the swarm does it for you with tools/swarm.py --continuous --drills 0.2 --save-leg-states.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeagent.atlas.rom_maps import map_name  # noqa: E402
from pokeagent.legs import schedule, states  # noqa: E402
from pokeagent.legs.drill_fold import load_drills  # noqa: E402


def load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_jsonl(p: Path) -> list[dict]:
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def fmt_eff(e) -> str:
    return "  -  " if e is None else f"{e:5.2f}"


def atlas_prior(atlas: dict, starter: str, map_id: int, level: int) -> float | None:
    """xp_per_min of the atlas spot for ``map_id`` (this starter, the level band nearest ``level``); None when not ranked."""
    best = None
    for goals in (atlas.get((starter or "").upper()) or atlas.get(starter) or {}).values():
        for lvl, spots in goals.items():
            for s in spots:
                if s["map_id"] == map_id and (best is None or abs(int(lvl) - level) < best[0]):
                    best = (abs(int(lvl) - level), s["xp_per_min"])
    return None if best is None else best[1]


def report(runs: Path, top: int) -> list[str]:
    legs = load_json(runs / "legs.json").get("legs", {})
    drills = load_drills(runs / "legs" / "drills.jsonl")
    keys = states.keys(runs / "legs" / "states")
    now = time.time()
    out = [f"{len(legs)} legs, {len(keys)} entry-state keys, {len(drills)} leg drills"]
    ranked = sorted((r for r in legs.values() if r.get("par_frames") is not None and r["samples"] >= 1),
                    key=lambda r: -schedule.waste(r))
    out += ["", "worst legs by waste = samples x (median - par)", f"{'leg':<44}{'n':>4}{'par':>6}{'median':>8}{'waste':>9}  state  note"]
    for r in ranked[:top]:
        has = (r["map"], *r["entry"]) in keys
        note = "retired" if schedule.retired(r, drills, now) else "drillable" if has and r["samples"] >= schedule.MIN_SAMPLES else ""
        out.append(f"{(map_name(r['map'])[:20] + ' ' + r['key'].split(':', 1)[1]):<44}{r['samples']:>4}{r['par_frames']:>6.0f}"
                   f"{r['median_frames']:>8.0f}{schedule.waste(r):>9.0f}  {'yes' if has else ' no'}    {note}")
    drilled = [r for r in legs.values() if r.get("drill_n")]
    out += ["", f"drilled legs: {len(drilled)}", f"{'leg':<44}{'drills':>7}{'solved':>7}{'eff before':>11}{'eff after':>10}{'best drill':>11}"]
    for r in sorted(drilled, key=lambda r: -r["drill_n"])[:top]:
        best = max((d["efficiency"] for d in r["drills"] if d.get("efficiency") is not None), default=None)
        out.append(f"{(map_name(r['map'])[:20] + ' ' + r['key'].split(':', 1)[1]):<44}{r['drill_n']:>7}{r['drill_solved']:>7}"
                   f"{fmt_eff(r.get('efficiency_run')):>11}{fmt_eff(r.get('efficiency')):>10}{fmt_eff(best):>11}")
    gd = load_jsonl(runs / "legs" / "grind_drills.jsonl")
    atlas = load_json(runs / "grind_atlas.json").get("atlas", {})
    out += ["", f"grind drills: {len(gd)}"]
    for g in gd[-top:]:
        prior = atlas_prior(atlas, g.get("starter", ""), g["map"], g.get("lead_level", 0))
        out.append(f"  map {g['map']} ({map_name(g['map'])}) L{g.get('lead_level', '?')}: {g['xp']:.0f} XP / {g['steps']} steps = "
                   f"{g['xp_per_min']:.1f} XP/min, {g.get('battles', 0)} battles; atlas prior "
                   + ("n/a (map not ranked)" if prior is None else f"{prior:.1f} XP/min"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="worst legs, drilled counts, before/after efficiency, grind-drill XP/min vs the atlas")
    r.add_argument("--runs-dir", default=str(ROOT / "runs" if (ROOT / "runs").is_dir() else Path("C:/Github/PokeAgent/runs")))
    r.add_argument("--top", type=int, default=10)
    a = ap.parse_args(argv)
    print("\n".join(report(Path(a.runs_dir), a.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
