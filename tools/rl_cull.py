"""Survival-of-the-fittest for the RL fleet: per segment, keep the champion,
re-seat the weakest as its offspring.

    uv run python tools/rl_cull.py              # loop, cull every --interval seconds
    uv run python tools/rl_cull.py --once       # single pass then exit
    uv run python tools/rl_cull.py --interval 60

Reads runs/rl_agents.json (registered learners, incl. their launch cmd) and
runs/rlstatus_<port>.json (solved-only stats). A segment is only culled once
its champion has a win — before that there is no evidence to select on. The
offspring inherits the champion's Q-table (--load-q) and extends the lineage
tag by one character (0-9 then a-z). Spawned below-normal priority, output to
runs/rltrain_<port>.log.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

REG = Path("runs/rl_agents.json")
STATE = Path("runs/rl_cull.json")
ALNUM = "0123456789abcdefghijklmnopqrstuvwxyz"
BELOW_NORMAL = 0x00004000  # Windows creation flag: learners yield to the desktop


def pid_alive(pid: int) -> bool:
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only, never kills
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def set_arg(cmd: list[str], flag: str, value) -> list[str]:
    cmd = list(cmd)
    if flag in cmd:
        cmd[cmd.index(flag) + 1] = str(value)
    else:
        cmd += [flag, str(value)]
    return cmd


def save_q_path(cmd: list[str], port: str) -> str | None:
    if "--save-q" in cmd:
        return cmd[cmd.index("--save-q") + 1]
    return f"runs/q_table_{port}.json"


def score(st: dict) -> tuple:
    # higher is better: solved-only avg steps first (lower steps = better), then win count
    if st.get("win_avg") is not None:
        return (1, -st["win_avg"], st.get("wins", 0))
    return (0, st.get("wins", 0), -st.get("steps_avg", 1e9))


def cull_once() -> None:
    try:
        reg = json.loads(REG.read_text())
    except Exception:
        return
    try:
        state = json.loads(STATE.read_text())
    except Exception:
        state = {"counters": {}}

    # drop dead registry entries (crashed learners); rl_admin --reap handles full resets
    for port in [p for p, i in reg.items() if not pid_alive(int(i.get("pid", 0)))]:
        print(f":{port} pid {reg[port].get('pid')} is dead; dropping registry entry")
        reg.pop(port)
    REG.write_text(json.dumps(reg, indent=1))

    by_seg: dict[str, list[tuple[str, dict, dict]]] = {}
    for port, info in reg.items():
        try:
            st = json.loads(Path(f"runs/rlstatus_{port}.json").read_text())
        except Exception:
            continue
        if not st.get('schema') or st.get('tag') != info.get('tag') or not info.get('cmd'):
            continue
        by_seg.setdefault((info.get('segment', '?'), st['schema']), []).append((port, info, st))

    for seg, members in by_seg.items():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=lambda m: (score(m[2]), -int(m[0])))
        champ_port, champ_info, champ_st = ranked[-1]
        if champ_st.get("win_avg") is None:
            continue  # nobody has won yet: no evidence to select on
        worst_port, worst_info, worst_st = ranked[0]
        if worst_port == champ_port or worst_st.get("win_avg") is not None:
            continue  # every member has won: all are winners, let them race
        champ_table = save_q_path(champ_info.get("cmd", []), champ_port)
        from pokeagent.qmodels import model_compatible
        actions = champ_st.get('actions', 6)
        if not champ_table or not model_compatible(champ_table, champ_st['schema'], actions):
            continue

        # lineage: champion tag + next variant char for this lineage
        counters = state.setdefault("counters", {})
        idx = counters.get(champ_info.get("tag", "?"), 0)
        counters[champ_info.get("tag", "?")] = idx + 1
        new_tag = f"{champ_info.get('tag', '?')}{ALNUM[idx % len(ALNUM)]}"

        cmd = set_arg(worst_info.get("cmd", []), "--tag", new_tag)
        cmd = set_arg(cmd, "--seed", random.randrange(1 << 30))
        cmd = set_arg(cmd, "--load-q", champ_table)
        print(f"[{seg}] cull :{worst_port} '{worst_info.get('tag')}' "
              f"(win_avg {worst_st.get('win_avg')}) -> sire '{new_tag}' "
              f"from :{champ_port} '{champ_info.get('tag')}' (win_avg {champ_st.get('win_avg')})", flush=True)

        try:
            os.kill(int(worst_info["pid"]), signal.SIGTERM)
        except Exception:
            pass
        reg.pop(worst_port, None)
        REG.write_text(json.dumps(reg, indent=1))
        log = open(f"runs/rltrain_{worst_port}.log", "a")
        subprocess.Popen([sys.executable, "tools/rl_train.py"] + cmd,
                         stdout=log, stderr=subprocess.STDOUT,
                         creationflags=BELOW_NORMAL, cwd=Path.cwd())
    STATE.write_text(json.dumps(state, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=120.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        cull_once()
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
