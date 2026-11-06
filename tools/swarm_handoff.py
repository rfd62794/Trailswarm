"""Rolling supervisor upgrade: hand a live swarm's agents to a NEW supervisor without stopping any of them.

New supervisor: request_handoff() writes runs/swarm.handoff and waits for runs/swarm/adopt.json (30 s, else it refuses:
no double supervision). Old supervisor: sees the request, hand_over() writes adopt.json (per live agent: slot, pid tree
root, seed, config, memory copy, run dir, start hash), stops refilling and exits WITHOUT killing anyone, releasing the lock.
The new one adopt()s them: polls their pids, applies its watchdog, merges their memory on exit, refills on its own code.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

ANSWER_S = 30.0


class ProcHandle:
    """Popen-like view of an agent we did not start: liveness by pid, kill takes down the recorded root's tree."""

    def __init__(self, pid: int, state: Callable[[int], str], kill_pid: Callable[[int], None]):
        self.pid, self._state, self._kill = pid, state, kill_pid

    def poll(self):
        return None if self._state(self.pid) != "gone" else "gone"  # 'unknown' (access denied) counts as alive

    def kill(self) -> None:
        self._kill(self.pid)


def default_state():
    from pokeagent.registry import process_state
    from swarm_proc import kill_tree
    return process_state, kill_tree


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def read_adopt(swarm_dir: Path) -> dict | None:
    try:
        return json.loads((Path(swarm_dir) / "adopt.json").read_text())
    except (OSError, ValueError):
        return None


def _run_dir(root: Path, seed: int, started_wall: float) -> str | None:
    try:
        from swarm_watch import find_run_dir
        d = find_run_dir(root, seed, started_wall)
        return str(d) if d else None
    except Exception:
        return None


def hand_over(sup) -> None:
    """Old side: record every live agent, then leave them running. The caller exits its loop without kill_all."""
    sup.stopping = sup.handed_over = True
    agents = []
    for s in sup.slots:
        if s.handle is None or s.handle.poll() is not None:
            continue
        cfg = {k: (str(v) if isinstance(v, Path) else v) for k, v in s.cfg.items()}
        wall = cfg.get("started_wall", time.time())
        agents.append({"slot": s.idx, "pid": s.handle.pid, "seed": cfg["seed"], "role": s.role, "own": cfg["own"],
                       "hash": cfg.get("hash"), "started_wall": wall,
                       "run_dir": _run_dir(sup.root, cfg["seed"], wall), "cfg": cfg})
    _write_atomic(sup.swarm_dir / "adopt.json", {"from_pid": os.getpid(), "next_seq": sup.seq, "agents": agents})
    sup.handoff_file.unlink(missing_ok=True)  # the acknowledgement: adopt.json exists, request gone
    sup.log(f"handoff: {len(agents)} running agents handed to the new supervisor (left running); old supervisor exiting")


def request_handoff(root: Path, wait_s: float = ANSWER_S, clock: Callable[[], float] = time.monotonic,
                    sleep: Callable[[float], None] = time.sleep) -> dict | None:
    """New side: ask the live supervisor to hand over. None = no answer in wait_s (caller refuses to start)."""
    runs = Path(root) / "runs"
    adopt_file, req = runs / "swarm" / "adopt.json", runs / "swarm.handoff"
    adopt_file.unlink(missing_ok=True)  # a stale answer from an earlier handoff must not count
    _write_atomic(req, {"from_pid": os.getpid(), "at": time.time()})
    end = clock() + wait_s
    while clock() < end:
        data = read_adopt(adopt_file.parent)
        if data is not None:
            return data
        sleep(1.0)
    req.unlink(missing_ok=True)
    return None


def adopt(sup, data: dict) -> int:
    """Install the old supervisor's agents into this one's slots; resize to sup's slot count (retire extras)."""
    Slot = type(sup.slots[0])
    by_idx: dict[int, Slot] = {}
    for a in data.get("agents", []):
        cfg = dict(a["cfg"])
        cfg["own"], cfg["started_wall"] = Path(a["own"]), a["started_wall"]
        s = Slot(a["slot"], a["role"], ProcHandle(a["pid"], sup.state, sup.kill_pid), cfg,
                 started=sup.clock() - max(0.0, time.time() - a["started_wall"]))
        by_idx[s.idx] = s
        if sup.watch_factory:
            sup.watchers[s.idx] = sup.watch_factory(cfg)
    want = len(sup.slots)
    for s in sup.slots:
        by_idx.setdefault(s.idx, s)
    for i in range(want):
        by_idx.setdefault(i, Slot(i, sup.roles[i % len(sup.roles)]))
    for idx in [i for i in by_idx if i >= want]:
        if by_idx[idx].handle is None:
            del by_idx[idx]
        else:
            by_idx[idx].retire = True  # finishes, is merged, then is not refilled
    sup.slots = [by_idx[i] for i in sorted(by_idx)]
    sup.seq = max(sup.seq, int(data.get("next_seq", 0)))
    n = len(data.get("agents", []))
    sup.log(f"adopted {n} running agents; {sup.status()}")
    return n
