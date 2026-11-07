"""ROM-gated: a confirm replay is only meaningful if the same state + seed + map memory gives the same run.

Runs the headless explorer twice from one start state for 200 steps and compares the decision logs line by line.
A run that received outside input (a non-agent press, e.g. something poking its control port) is retried: that is
interference, not nondeterminism, and the curriculum treats such replays as inconclusive too.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ROM = Path(os.environ.get("POKEAGENT_ROM") or REPO / "roms" / "Pokemon Red.gb")
START = REPO / "baselines" / "bedroom.state"
PORT = 9710   # >= 9700: clear of the swarm's 8800+ agents


def _run(tmp: Path, name: str, maps: Path) -> tuple[list[str], int]:
    wd = tmp / name
    wd.mkdir()
    shutil.copy(maps, wd / "m.json")
    cmd = [sys.executable, str(REPO / "tools" / "explore_demo.py"), "--headless", "--rom", str(ROM), "--state", str(START),
           "--maps", "m.json", "--steps", "200", "--seed", "7", "--starter", "squirtle", "--explore-rate", "0.0",
           "--box-pace", "8", "--control-port", str(PORT)]
    subprocess.run(cmd, cwd=wd, check=True, timeout=300, capture_output=True)
    run = next((wd / "runs").glob("explore-*"))
    decisions = (run / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    outside = sum(1 for ln in (run / "transitions.jsonl").read_text(encoding="utf-8").splitlines()
                  if json.loads(ln).get("source", "agent") != "agent")
    return decisions, outside


@pytest.mark.skipif(not ROM.exists() or not START.exists(), reason="needs the ROM and baselines/bedroom.state (gitignored)")
def test_same_state_seed_and_memory_give_identical_decision_logs(tmp_path):
    maps = tmp_path / "empty.json"
    maps.write_text(json.dumps({"maps": {}}))
    for attempt in range(3):
        a, out_a = _run(tmp_path, f"a{attempt}", maps)
        b, out_b = _run(tmp_path, f"b{attempt}", maps)
        if out_a or out_b:
            continue   # outside input on one of them: retry
        assert len(a) == len(b) > 150
        assert a == b
        return
    pytest.skip("outside input on every attempt; cannot judge determinism")
