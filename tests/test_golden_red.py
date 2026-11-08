"""ROM-gated golden guard for Pokemon Red (multi-game framework plan, phase 1).

Runs the same explorer command as tools/golden_trace.py (headless, seed 42, bedroom state,
stop at potion, 400 steps) in a scratch copy of the inputs and pins the sha256 of the
resulting transitions.jsonl. Phases 2-4 must leave EXPECTED_SHA256 unchanged; if a change
is deliberate, re-record it from a base-commit run in the same PR. Only a digest is stored.

Why not call golden_trace.py itself: it compares transitions.jsonl byte for byte, but the
potion pickup record embeds the run directory name ("item.run"), so it reports DIFFERS on
every run; and it starts run A from empty map memory while run B inherits what A learned.
So: one warm-up run builds maps.json, then two measured runs each start from a fresh copy
of it, with the run name masked before hashing. Skips when the ROM, kb/rom_tables.json or baselines are absent.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NEEDED = ["roms/Pokemon Red.gb", "baselines/bedroom.state", "kb/rom_tables.json"]
OPTIONAL = ["baselines/bedroom.state.meta.json"]
EXPECTED_SHA256 = "a9b5a8f86afd3614bd7a55c52d23b3b2e0f6bc0eab17d88b30f5ac3f4b575911"  # transitions.jsonl, run name masked, warm maps


def _explore(cwd: Path, maps: Path, port: int) -> str:
    before = set((cwd / "runs").glob("explore-*"))
    subprocess.run([sys.executable, "tools/explore_demo.py", "--headless", "--state", "baselines/bedroom.state",
                    "--stop-at-goal", "potion", "--steps", "400", "--seed", "42", "--maps", str(maps),
                    "--control-port", str(port)], cwd=cwd, check=True, capture_output=True, timeout=600)
    (run,) = set((cwd / "runs").glob("explore-*")) - before
    text = (run / "transitions.jsonl").read_text(encoding="utf-8")
    return hashlib.sha256(re.sub(r'"run": "explore-[^"]*"', '"run": "X"', text).encode()).hexdigest()


def test_red_golden_trace(tmp_path):
    missing = [p for p in NEEDED if not (ROOT / p).exists()]
    if missing:
        pytest.skip(f"golden trace needs gitignored local files: {', '.join(missing)}")
    for d in ("tools", "src"):  # src too: explore_demo and the kb lookups resolve relative to the scratch tree
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("__pycache__"))
    for rel in NEEDED + OPTIONAL:
        if (ROOT / rel).exists():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, tmp_path / rel)
    (tmp_path / "runs").mkdir()
    warm = tmp_path / "runs" / "maps.json"
    _explore(tmp_path, warm, 9000)  # warm-up: builds map memory; its hash is not pinned
    digests = []
    for i in (1, 2):
        copy = tmp_path / f"maps{i}.json"
        shutil.copy(warm, copy)
        digests.append(_explore(tmp_path, copy, 9000 + i))
        time.sleep(1)
    print("GOLDEN SHA256:", digests[0])
    assert digests[0] == digests[1], "Red trace is not deterministic across two runs"
    assert digests[0] == EXPECTED_SHA256
