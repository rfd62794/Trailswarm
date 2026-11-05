"""Golden-trace check: same seed + same checkpoint + pinned maps => identical transitions.

    uv run python tools/golden_trace.py [--steps 400] [--seed 42] [--segment potion]

Runs the explorer twice headless with identical inputs and a private copy of
maps.json, then compares transitions.jsonl byte-for-byte. Use before/after any
extraction PR: a diff means either the refactor changed behavior or emulation
is not deterministic — investigate before merging.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def latest_run(runs: Path) -> Path:
    return max(runs.glob("explore-*"), key=lambda p: p.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--state", default="baselines/bedroom.state")
    ap.add_argument("--stop-at-goal", default="potion")
    a = ap.parse_args()

    runs = Path("runs")
    tmp = Path(tempfile.mkdtemp(prefix="golden-"))
    shutil.copy(runs / "maps.json", tmp / "maps.json") if (runs / "maps.json").exists() else None
    outs = []
    for i in (1, 2):
        subprocess.run([sys.executable, "tools/explore_demo.py", "--headless",
                        "--state", a.state, "--stop-at-goal", a.stop_at_goal,
                        "--steps", str(a.steps), "--seed", str(a.seed),
                        "--maps", str(tmp / "maps.json"), "--control-port", str(9000 + i)],
                       check=True)
        outs.append(latest_run(runs) / "transitions.jsonl")
        time.sleep(1)
    same = filecmp.cmp(*outs, shallow=False)
    print(f"run A: {outs[0].parent.name}\nrun B: {outs[1].parent.name}")
    print("GOLDEN TRACE:", "IDENTICAL" if same else "DIFFERS — investigate before merging")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
