"""Permanent fix for stale RL learners: a PID registry + reap tool.

    uv run python tools/rl_admin.py --reap        # kill every registered learner, unlink zombie slots
    uv run python tools/rl_admin.py --list        # show registered agents

rl_train registers {port, pid, tag} in runs/rl_agents.json at startup and
unregisters on clean exit. Reaping kills by exact PID (no cmdline guessing)
and removes orphaned shared-memory slots.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

REG = Path("runs/rl_agents.json")


def registry() -> dict:
    try:
        return json.loads(REG.read_text())
    except Exception:
        return {}


def save(reg: dict) -> None:
    REG.write_text(json.dumps(reg, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reap", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    reg = registry()
    if a.list:
        for port, info in sorted(reg.items()):
            print(f":{port}  pid {info.get('pid')}  tag {info.get('tag')}  segment {info.get('segment')}")
        return 0
    if a.reap:
        from multiprocessing import shared_memory
        killed = 0
        for port, info in reg.items():
            try:
                os.kill(int(info["pid"]), signal.SIGTERM)
                killed += 1
            except Exception:
                pass
            try:  # unlink any slot the dead process left behind
                shared_memory.SharedMemory(name=f"pokeagent_frames_{port}").unlink()
            except Exception:
                pass
        save({})
        print(f"reaped {killed} registered learners; slots cleared")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
