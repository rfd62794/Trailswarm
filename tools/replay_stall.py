"""replay_stall: re-run one stalled segment headless (ONE emulator) and say whether the stall reproduces.

    uv run python tools/replay_stall.py <run> [--steps N] [--dry-run]

Uses the dossier's start state, seed, starter and stop goal, with --maps-copy (the segment's input maps, else runs/maps.json),
runs tools/explore_headless.py until about the stall step, and compares the new signature with the dossier's: same
signature and the stall step within +-10% = reproduced. Writes nothing under runs/ (explore_headless works in a temp dir).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pokeagent import stalls  # noqa: E402

TOLERANCE = 0.10
MARGIN = 1.10  # run a little past the stall step so the same window is full


def replay_args(dossier: dict, root: Path, steps: int | None = None) -> list[str]:
    """argv for tools/explore_headless.py reproducing this dossier's segment run."""
    ss = dossier.get("start_state") or {}
    if not ss.get("state_file"):
        raise ValueError("dossier has no start state file on disk (segment inputs rotated and no checkpoint)")
    maps = ss.get("maps_copy") or str(root / "runs" / "maps.json")
    n = steps or int(int(dossier.get("presses") or 3000) * MARGIN)
    args = ["--state", ss["state_file"], "--seed", str(dossier.get("seed") or 1), "--steps", str(n),
            "--starter", str(dossier.get("starter") or "bulbasaur"), "--maps-copy", maps]
    if ss.get("stop_at_goal"):
        args += ["--stop-at-goal", str(ss["stop_at_goal"])]
    return args


def compare(dossier: dict, fresh: dict | None, steps_fresh: int) -> dict:
    """Reproduced = same signature (map, behaviour, rule, button, outcome, sprite_adjacent) and the step within +-10%."""
    want = int(dossier.get("presses") or 0)
    same = bool(fresh) and fresh["signature_key"] == dossier["signature_key"]
    near = want > 0 and abs(steps_fresh - want) <= TOLERANCE * want
    ds, fs = dossier["signature"], (fresh or {}).get("signature") or {}
    close = bool(fresh) and all(ds.get(k) == fs.get(k) for k in ("map", "outcome"))
    return {"reproduced": same and near, "same_signature": same, "same_map_and_outcome": close, "steps_within_10pct": near,
            "dossier_steps": want, "replay_steps": steps_fresh,
            "dossier_signature": dossier["signature"], "replay_signature": fresh["signature"] if fresh else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="replay_stall", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--steps", type=int, default=None, help="presses to run (default: stall presses + 10%%)")
    ap.add_argument("--root", default=os.environ.get("POKEAGENT_ROOT", str(ROOT)))
    ap.add_argument("--dry-run", action="store_true", help="print the explore_headless command and stop")
    a = ap.parse_args(argv)
    root = Path(a.root)
    dpath = root / "runs" / "stalls" / f"{a.run}.json"
    if not dpath.exists():
        print(json.dumps({"error": f"no dossier {dpath}; run tools/stalls.py backfill"}))
        return 2
    dossier = json.loads(dpath.read_text(encoding="utf-8"))
    cmd = [sys.executable, str(ROOT / "tools" / "explore_headless.py"), *replay_args(dossier, root, a.steps)]
    if a.dry_run:
        print(json.dumps({"cmd": cmd}))
        return 0
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    try:
        res = json.loads(proc.stdout[proc.stdout.index("{"):])
    except ValueError:
        print(json.dumps({"error": "explore_headless failed", "stderr": proc.stderr[-800:]}))
        return 1
    work = Path(res["work"])
    fresh = stalls.build_dossier(root, "replay", {"pos": None}, rdir=work, maps_doc=_maps_of(work, root), anomalies=[])
    out = compare(dossier, fresh, int(res.get("steps") or 0))
    out["work"] = str(work)
    print(json.dumps(out, indent=1))
    return 0 if out["reproduced"] else 1


def _maps_of(work: Path, root: Path) -> dict:
    try:
        return json.loads((work / "maps.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


if __name__ == "__main__":
    sys.exit(main())
