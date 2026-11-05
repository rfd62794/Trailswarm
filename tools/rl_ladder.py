"""Fleet ladder: automatically seat and reseat RL learners across the campaign.

    uv run python tools/rl_ladder.py              # converge every --interval seconds
    uv run python tools/rl_ladder.py --once       # single pass
    uv run python tools/rl_ladder.py --interval 60

Desired fleet (ports 8890-8895):
  - every HOT segment (has a usable checkpoint but no rl_<seg>.state yet)
    gets 1 seat, then second seats in ladder order
  - CLEARED segments (rl_<seg>.state exists: an agent already reached the goal)
    yield seats to the frontier; they only keep alumni seats if ports remain
  - a live learner whose segment is still desired keeps its seat; anything else
    is killed (Q-table persists in runs/q_table_<port>.json) and the port is
    respawned on the desired segment

rl_cull.py still owns within-segment selection (kill weakest, sire offspring);
the ladder owns how many seats each segment gets. They compose: the ladder
frees ports, the culler improves whoever is sitting in them.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

from rl_cull import pid_alive, score  # shared process/status helpers
from rl_env import SEGMENT_STATES

REG = Path("runs/rl_agents.json")
STATE = Path("runs/rl_ladder.json")
PORTS = list(range(8890, 8896))
BELOW_NORMAL = 0x00004000

# (segment, tag prefix, max_steps) in campaign order
LADDER = [
    ("reach_pc", "pc", 200),
    ("potion", "pot", 300),
    ("exit_potion", "ex", 300),
    ("battle", "bat", 300),
    ("grind", "gr", 600),
    ("to_viridian", "vir", 400),
    ("to_route2", "r2", 500),
    ("to_pewter", "pew", 500),
    ("to_gym", "gym", 500),
]
ALNUM = "0123456789abcdefghijklmnopqrstuvwxyz"


def launchable(seg: str) -> bool:
    """A non-bedroom checkpoint exists, so the segment can start near its goal."""
    return any("bedroom" not in s and Path(s).exists() for s in SEGMENT_STATES.get(seg, []))


def cleared(seg: str) -> bool:
    from pokeagent.curriculum import stage_cleared
    return stage_cleared(seg)


def desired_seats() -> dict[str, int]:
    hot = [s for s, _, _ in LADDER if launchable(s) and not cleared(s)]
    alumni = [s for s, _, _ in LADDER if launchable(s) and cleared(s)]
    seats: dict[str, int] = {}
    for seg in hot[:len(PORTS)]:  # one seat per hot segment first
        seats[seg] = seats.get(seg, 0) + 1
    for seg in hot:  # then second seats in ladder order while ports remain
        if sum(seats.values()) < len(PORTS):
            seats[seg] += 1
    for seg in reversed(alumni):  # leftover ports consolidate the most recent cleared rungs
        if sum(seats.values()) < len(PORTS):
            seats[seg] = seats.get(seg, 0) + 1
    for seg in hot:  # still spare: third seats on the frontier
        while sum(seats.values()) < len(PORTS):
            seats[seg] += 1
        if sum(seats.values()) >= len(PORTS):
            break
    return seats


def status(port: str) -> dict:
    try:
        return json.loads(Path(f"runs/rlstatus_{port}.json").read_text())
    except Exception:
        return {}


def spawn(port: int, seg: str, prefix: str, max_steps: int, state: dict) -> None:
    pstate = state.setdefault("ports", {}).setdefault(str(port), {})
    seq = state.setdefault("seq", {})
    idx = seq.get(prefix, 0)
    seq[prefix] = idx + 1
    tag = f"{prefix}{ALNUM[idx % len(ALNUM)]}"
    q_table = f"runs/q_table_{port}.json"
    cmd = ["--segment", seg, "--episodes", "400", "--evals", "0",
           "--max-steps", str(max_steps), "--frame-port", str(port),
           "--seed", str(random.randrange(1 << 30)),
           "--publish-fps", "20", "--full-res", "--throttle-ms", "4",
           "--share-every", "25", "--n-step", "3", "--double-q", "--trace",
           "--save-q", q_table, "--tag", tag]
    from pokeagent.observations import schema_id
    from pokeagent.qmodels import model_compatible
    expected = schema_id(seg)
    if pstate.get("seg") == seg and model_compatible(q_table, expected, 6):
        cmd += ["--load-q", q_table]  # reseat on the same segment resumes its own table
    pstate["seg"] = seg
    log = open(f"runs/rltrain_{port}.log", "a")
    subprocess.Popen([sys.executable, "tools/rl_train.py"] + cmd, stdout=log,
                     stderr=subprocess.STDOUT, creationflags=BELOW_NORMAL, cwd=Path.cwd())
    print(f":{port} seat -> {seg} '{tag}'", flush=True)


def converge() -> None:
    try:
        reg = json.loads(REG.read_text())
    except Exception:
        reg = {}
    try:
        state = json.loads(STATE.read_text())
    except Exception:
        state = {"ports": {}}
    pstate = state.setdefault("ports", {})

    # drop dead registry entries; the port becomes free for reassignment
    for port in [p for p, i in reg.items() if not pid_alive(int(i.get("pid", 0)))]:
        print(f":{port} '{reg[port].get('tag')}' ({reg[port].get('segment')}) exited; seat free", flush=True)
        # clear that segment's pool file so a new occupant doesn't inherit foreign values
        seg = reg[port].get("segment", "")
        for f in Path("runs/qshare").glob(f"{seg}_{port}.json") if Path("runs/qshare").exists() else []:
            f.unlink()
        reg.pop(port)
    REG.write_text(json.dumps(reg, indent=1))

    seats = desired_seats()
    meta = {s: (p, m) for s, p, m in LADDER}

    # live learners per segment
    live: dict[str, list[tuple[str, dict]]] = {}
    for port, info in reg.items():
        live.setdefault(info.get("segment", "?"), []).append((port, info))

    # keep the best `seats[seg]` learners per desired segment; everyone else yields.
    # segments absent from `seats` want 0 seats: cleared rungs vacate for the frontier.
    for seg in set(live) | set(seats):
        want = seats.get(seg, 0)
        members = sorted(live.get(seg, []),
                         key=lambda m: (score(status(m[0])), -int(m[0])), reverse=True)
        for port, info in members[want:]:
            print(f":{port} '{info.get('tag')}' ({seg}) yields seat to frontier", flush=True)
            try:
                os.kill(int(info["pid"]), signal.SIGTERM)
            except Exception:
                pass
            reg.pop(port, None)
            # drop its pool contribution so foreign values can't be adopted
            for f in Path("runs/qshare").glob(f"{seg}_{port}.json") if Path("runs/qshare").exists() else []:
                f.unlink()
    REG.write_text(json.dumps(reg, indent=1))

    # spawn into remaining free ports, most-wanted segments first
    free = [str(p) for p in PORTS if str(p) not in reg]
    for seg, want in sorted(seats.items(), key=lambda kv: -kv[1]):
        have = sum(1 for i in reg.values() if i.get("segment") == seg)
        for _ in range(max(0, want - have)):
            if not free:
                break
            port = free.pop(0)
            prefix, max_steps = meta[seg]
            spawn(int(port), seg, prefix, max_steps, state)
    STATE.write_text(json.dumps(state, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=120.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        try:
            converge()
        except Exception as e:
            print(f"ladder error: {e}", flush=True)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
