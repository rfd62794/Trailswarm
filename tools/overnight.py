"""Overnight swarm orchestrator: run rounds of headless agents on the objective that needs it most, merge, review,
promote checkpoints, and write a one-line status per round to runs/overnight-status.log.

    uv run python tools/overnight.py --hours 6 --agents 8 --steps 800

Each round picks ONE objective:
  - the first goal in GOALS whose segment consistency over the last 12 runs is below 70%  -> --segment <goal>
  - else the furthest checkpoint we have                                                -> explorers from it (frontier)
  - every third round                                                                   -> --roles (trainers + explorers)
Rounds alternate explorer/exploiter mixes inside swarm.py. Between rounds the review tool runs and the status line
records: round, objective, agents, wall time, per-goal consistency, records, maps/tiles known, best level.
Robert's rule: max out the machine overnight, headless, and leave a record a morning reader can act on.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOALS = ["potion", "left_house", "first_pokemon", "won_battle", "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel"]


def consistency(last_n: int = 16) -> dict[str, float]:
    """Per goal: of the recent runs that STARTED before it (first press map/goal state), the share that reached it.
    A run counts as 'attempting' a goal when it has at least 20 presses and its start was upstream of the goal."""
    ms_path = ROOT / "runs" / "milestones.json"
    if not ms_path.exists():
        return {}
    ms = json.loads(ms_path.read_text())
    runs = [p for p in sorted((ROOT / "runs").glob("explore-*"), key=lambda p: p.stat().st_mtime)
            if (p / "transitions.jsonl").exists() and sum(1 for _ in open(p / "transitions.jsonl", encoding="utf-8")) >= 5]
    out = {}
    def start_idx(p):
        try:
            meta = json.loads((p / "meta.json").read_text())
        except Exception:
            return None, None
        st = meta.get("start", "baseline")
        si = -1 if st in ("baseline", "bedroom") else GOALS.index(st) if st in GOALS else GOALS.index("to_route1") if st == "team_best" else None
        stop = GOALS.index(meta["stop_at_goal"]) if meta.get("stop_at_goal") in GOALS else len(GOALS)
        return si, stop
    for i, g in enumerate(GOALS):
        # an ATTEMPT at goal i: the run started upstream of it (start index < i) and was not stopped before it
        tries = []
        for p in runs[-80:]:
            si, stop = start_idx(p)
            if si is not None and si < i and stop >= i:
                tries.append(p.name)
        tries = tries[-last_n:]
        out[g] = round(sum(1 for e in ms.get(g, []) if e["run"] in tries) / max(1, len(tries)), 2) if len(tries) >= 3 else None
    return out


def furthest_checkpoint() -> str | None:
    for g in reversed(GOALS):
        if (ROOT / "runs" / "checkpoints" / f"{g}.state").exists():
            return g
    return None


def run_swarm(args: list[str], timeout: int) -> str:
    cmd = [sys.executable, str(ROOT / "tools" / "swarm.py")] + args
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return (out.stdout + out.stderr).strip().splitlines()[-1] if (out.stdout or out.stderr) else "no output"
    except subprocess.TimeoutExpired:
        return "swarm round timed out"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--steps", type=int, default=800)
    a = ap.parse_args()
    log = ROOT / "runs" / "overnight-status.log"
    t_end = time.time() + a.hours * 3600
    rnd = 0
    while time.time() < t_end:
        rnd += 1
        cons = consistency()
        weak = next((g for g in GOALS if cons.get(g) is not None and cons.get(g) < 0.7 and (g == GOALS[0] or (ROOT / "runs" / "checkpoints" / f"{GOALS[GOALS.index(g) - 1]}.state").exists())), None)
        if rnd % 3 == 0 and (ROOT / "runs" / "checkpoints" / "team_best.state").exists():
            objective, args = "roles (train + explore from the strongest team)", ["--roles"]
        elif weak:
            objective, args = f"segment {weak} (consistency {cons.get(weak)})", ["--segment", weak]
        else:
            far = furthest_checkpoint()
            objective, args = f"explore beyond {far}", (["--segment", GOALS[min(len(GOALS) - 1, GOALS.index(far) + 1)]] if far and GOALS.index(far) + 1 < len(GOALS) else [])
        t0 = time.time()
        last = run_swarm(["--agents", str(a.agents), "--steps", str(a.steps)] + args, timeout=max(600, a.steps * 3))
        subprocess.run([sys.executable, str(ROOT / "tools" / "review_runs.py")], cwd=ROOT, capture_output=True, text=True, timeout=300)
        maps = json.loads((ROOT / "runs" / "maps.json").read_text())
        tiles = sum(len(m.get("visited", {})) for m in maps["maps"].values())
        line = (f"{time.strftime('%H:%M')} round {rnd}: {objective}; {a.agents}x{a.steps} in {time.time() - t0:.0f}s; "
                f"consistency {consistency()}; maps {len(maps['maps'])} tiles {tiles} best level {maps.get('team_best_level', '?')}; {last}")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
