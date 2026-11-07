"""Windowless, portless seeder for RAM discovery: one explorer run from a checkpoint with event RAM diffs on.

    uv run python tools/ram_seed.py --state to_route1 --steps 2000 [--seed 1] [--no-ram-diff]

Writes runs/ramseed-<state>-<seed>/{ram_events,ram_trace}.jsonl. Uses a private copy of maps.json (--maps, default
runs/maps.json is only read) so the live swarm memory is never touched. Never opens a window or a port.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from pokeagent.ramlab.headless import run_agent  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="checkpoint stem under runs/checkpoints")
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--maps", default=str(ROOT / "runs" / "maps.json"), help="read-only source of map memory")
    ap.add_argument("--states", default=str(ROOT / "runs" / "checkpoints"))
    ap.add_argument("--out", default=str(ROOT / "runs"))
    ap.add_argument("--no-ram-diff", action="store_true")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        maps = Path(tmp) / "maps.json"
        if Path(a.maps).is_file():
            shutil.copy(a.maps, maps)
        run_dir = Path(a.out) / f"ramseed-{a.state}-{a.seed}{'-off' if a.no_ram_diff else ''}"
        res = run_agent(ROOT / "roms" / "Pokemon Red.gb", Path(a.states) / f"{a.state}.state", maps, run_dir, a.steps,
                        ram_diff=not a.no_ram_diff, seed=a.seed)
    print(f"{a.state} seed {a.seed}: {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
