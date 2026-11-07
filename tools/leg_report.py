"""Score the agent's real legs against par (read-only over runs/explore-*).

    uv run python tools/leg_report.py                       # last 200 runs, 25 worst legs
    uv run python tools/leg_report.py --runs 200 --prefix explore-20261106- --top 15 --json out.json

A leg is one traversal of one map: entry tile -> the press that leaves it. Par is the cheapest route on the ROM collision grid
(16 frames/tile, grass penalty, ledges one-way; see pokeagent.legs.grid). Actual frames come from presses (legs.split).
Efficiency = par / best actual; sorted worst first. Writes the per-leg record table runs/legs.json (a new file) unless --no-write.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeagent.atlas.rom_maps import map_name  # noqa: E402
from pokeagent.legs import grid as G  # noqa: E402
from pokeagent.legs.par import par  # noqa: E402
from pokeagent.legs.split import efficiency, load_rows, median, split_legs  # noqa: E402


def legit_exit(g, leg) -> bool:
    """The leaving press steps onto a warp tile or off the map edge (not a whiteout, fly or scripted move)."""
    dx, dy = G.DIRS.get(leg.button, (0, 0))
    nx, ny = leg.exit[0] + dx, leg.exit[1] + dy
    return leg.exit in g.solid or (nx, ny) in g.solid or not g.inside(nx, ny)


def fight_steps(path: Path) -> set:
    """Steps whose decision was made in a battle: grinding / wild fights, not travel."""
    steps = set()
    if path.exists():
        for r in load_rows(path):
            if r.get("battle"):
                steps.add(int(r.get("step", -1)))
    return steps


def fought(fights: set, leg) -> bool:
    return any(s in fights for s in range(leg.step0, leg.step1 + 1))


def collect(runs_dir: Path, prefix: str, n: int, get, keep_fights: bool = False):
    names = sorted(p.name for p in runs_dir.glob(prefix + "*") if (p / "transitions.jsonl").exists())[-n:]
    groups, skipped = defaultdict(list), defaultdict(int)
    for name in names:
        fights = set() if keep_fights else fight_steps(runs_dir / name / "decisions.jsonl")
        for leg in split_legs(load_rows(runs_dir / name / "transitions.jsonl"), name):
            g = get(leg.map)
            if fights and fought(fights, leg):
                skipped["fought (grinding/battle: not travel)"] += 1
            elif not leg.complete:
                skipped["incomplete"] += 1
            elif g is None or not legit_exit(g, leg):
                skipped["irregular exit"] += 1
            else:
                groups[leg.key].append(leg)
    return names, groups, skipped


def score(get, groups) -> list[dict]:
    out = []
    for key, legs in groups.items():
        first = legs[0]
        res = par(get(first.map), first.entry, first.exit)
        pf = None if res is None else res[0] + G.FRAME_WALK  # + the press that leaves the map
        fr = [l.frames for l in legs]
        best = min(legs, key=lambda l: l.frames)
        out.append({"key": key, "map": first.map, "name": map_name(first.map), "entry": list(first.entry), "exit": list(first.exit),
                    "button": first.button, "dest": list(first.dest), "samples": len(legs),
                    "par_frames": pf, "par_steps": None if res is None else len(res[1]),
                    "best_frames": min(fr), "median_frames": median(fr), "efficiency": efficiency(pf, fr),
                    "best_presses": best.presses, "best_moved": best.moved, "best_run": best.run, "best_step0": best.step0,
                    "best_buttons": best.buttons, "par_path": None if res is None else [list(p) for p in res[1]]})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--prefix", default="explore-")
    ap.add_argument("--runs-dir", default=str(ROOT / "runs" if (ROOT / "runs").is_dir() else Path("C:/Github/PokeAgent/runs")))
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--min-samples", type=int, default=1)
    ap.add_argument("--min-par", type=float, default=0, help="ignore legs whose par is under this many frames (door bounces)")
    ap.add_argument("--sort", choices=("eff", "waste"), default="eff", help="eff: worst par/best first; waste: most total frames over par")
    ap.add_argument("--json", help="also write the printed rows here")
    ap.add_argument("--out", help="per-leg record table (default: <runs-dir>/legs.json)")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--keep-fights", action="store_true", help="count legs with battle presses too (default: excluded, so efficiency is travel only)")
    a = ap.parse_args(argv)
    get = G.rom_grids()
    if get is None:
        print("ROM not found (roms/Pokemon Red.gb): cannot compute par", file=sys.stderr)
        return 2
    names, groups, skipped = collect(Path(a.runs_dir), a.prefix, a.runs, get, a.keep_fights)
    rows = score(get, groups)
    keep = [r for r in rows if r["efficiency"] is not None and r["samples"] >= a.min_samples and r["par_frames"] >= a.min_par]
    scored = sorted(keep, key=(lambda r: (r["efficiency"], -(r["best_frames"] - r["par_frames"]))) if a.sort == "eff"
                    else (lambda r: -r["samples"] * (r["median_frames"] - r["par_frames"])))
    print(f"{len(names)} runs, {len(rows)} distinct legs ({len(scored)} with par), skipped {dict(skipped)}")
    print(f"{'map':<24}{'entry':>9}{'exit':>9} btn  {'par':>6}{'best':>8}{'median':>8}{'eff':>6}{'n':>5}{'tiles':>6}{'moved':>6}")
    for r in scored[:a.top]:
        print(f"{r['name'][:23]:<24}{str(tuple(r['entry'])):>9}{str(tuple(r['exit'])):>9} {r['button'][:1]:<3} {r['par_frames']:>6.0f}"
              f"{r['best_frames']:>8.0f}{r['median_frames']:>8.0f}{r['efficiency']:>6.2f}{r['samples']:>5}{r['par_steps'] - 1:>6}{r['best_moved']:>6}")
    if a.json:
        Path(a.json).write_text(json.dumps(scored[:a.top] if a.top else scored, indent=1))
    if not a.no_write:
        table = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "runs": len(names), "frame_model": "16/tile moved, 6 idle, +16 leaving press",
                 "legs": {r["key"]: r for r in rows}}
        Path(a.out or Path(a.runs_dir) / "legs.json").write_text(json.dumps(table, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
