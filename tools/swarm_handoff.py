"""Rolling supervisor upgrade: hand a live swarm's agents to a NEW supervisor without stopping any of them.

New supervisor: request_handoff() claims runs/swarm.handoff exclusively (swarm_claims.py; holds its pid) and waits for
runs/swarm/adopt-<pid>.json (30 s, one more look after, else it refuses: no double supervision). Old supervisor:
hand_over() moves runs/spawn.lock to the new pid (swarm_lock.py), merges agents that already exited, writes
adopt-<pid>.json (per live agent: slot, pid tree root, seed, config, memory copy, run dir, start hash, process identity)
and exits WITHOUT killing anyone. The new one adopts them: polls their pids, applies its watchdog, merges on exit,
refills on its code. Any failure after the lock moved puts the lock back and the old supervisor keeps supervising.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from swarm_claims import claim, read_json, withdraw, write_atomic  # noqa: F401
from swarm_ident import SIGNATURE, Ident
from swarm_lock import acquire_after_handoff, adopt_lock, lock_holder, transfer_lock  # noqa: F401
from swarm_slot import Slot

ANSWER_S = 30.0
EXTRA_S = 5.0  # grace for an old supervisor that had already committed (lock moved) when we withdrew


class ProcHandle:
    """Popen-like view of an agent we did not start: liveness by pid, kill takes down the recorded root's tree.
    A pid whose creation time or command line no longer matches the recording is a different process: gone, never killed."""

    def __init__(self, pid: int, state: Callable[[int], str], kill_pid: Callable[[int], None], ident=None, rec: dict | None = None):
        self.pid, self._state, self._kill, self.ident, self.rec = pid, state, kill_pid, ident or Ident(), rec or {}
        self.reused = False

    def same_process(self, full: bool = False) -> bool:
        if self.reused:
            return False
        want = self.rec.get("created")
        if want is not None and self.ident.created(self.pid) not in (None, want):
            self.reused = True
        elif full and self.rec.get("sig"):
            cmd = self.ident.cmdline(self.pid)
            self.reused = cmd is not None and self.rec["sig"] not in cmd
        return not self.reused

    def poll(self):
        if self._state(self.pid) == "gone" or not self.same_process():
            return "gone"
        return None  # 'unknown' (access denied) counts as alive

    def owned(self) -> bool:
        """Positive proof this pid is the recorded agent: creation time AND signature both read and matching."""
        want, sig = self.rec.get("created"), self.rec.get("sig")
        if want is None or not sig or self.ident.created(self.pid) != want:
            return False
        cmd = self.ident.cmdline(self.pid)
        return cmd is not None and sig in cmd

    def kill(self) -> bool:
        """True = gone or killed. False = alive but not provably ours: nothing sent, the caller must keep the handle."""
        if self._state(self.pid) == "gone":
            return True
        if not self.owned():
            return False
        self._kill(self.pid)
        return True


def default_state():
    from pokeagent.registry import process_state
    from swarm_proc import kill_tree
    return process_state, kill_tree


def adopt_path(swarm_dir: Path, pid: int) -> Path:
    return Path(swarm_dir) / f"adopt-{pid}.json"


def read_adopt(swarm_dir: Path, pid: int) -> dict | None:
    return read_json(adopt_path(swarm_dir, pid))


def _run_dir(root: Path, seed: int, started_wall: float) -> str | None:
    try:
        from swarm_watch import find_run_dir
        d = find_run_dir(root, seed, started_wall)
        return str(d) if d else None
    except Exception:
        return None


def _record(sup, s) -> dict:
    cfg = {k: (str(v) if isinstance(v, Path) else v) for k, v in s.cfg.items()}
    wall = cfg.get("started_wall", time.time())
    created = sup.ident.created(s.handle.pid)
    return {"slot": s.idx, "pid": s.handle.pid, "seed": cfg["seed"], "role": s.role, "own": cfg["own"],
            "hash": cfg.get("hash"), "started_wall": wall, "run_dir": _run_dir(sup.root, cfg["seed"], wall),
            "ident": {"created": created, "sig": SIGNATURE} if created is not None else {"sig": SIGNATURE}, "cfg": cfg}


def hand_over(sup) -> bool:
    """Old side. False = not handing over (request unreadable/dead/withdrawn, lock not ours, or an error): keep running.
    Otherwise: merge exited agents once, record the live ones, leave them running; the caller exits without kill_all."""
    req = read_json(sup.handoff_file)
    if not req or not isinstance(req.get("pid"), int):
        return False
    pid = req["pid"]

    def still_asked() -> bool:  # the claim is still that requester's, and it is alive to receive the answer
        cur = read_json(sup.handoff_file)
        return bool(cur) and cur.get("pid") == pid and sup.state(pid) != "gone"

    if not still_asked():
        return False
    if not transfer_lock(sup.root, pid):
        if getattr(sup, "_refused", None) != pid:
            sup._refused = pid
            sup.log(f"handoff to pid {pid} refused: runs/spawn.lock is not ours to transfer; still supervising")
        return False
    try:
        if not still_asked():  # withdrawn while we moved the lock: take it back
            transfer_lock(sup.root, os.getpid(), expect=pid)
            return False
        agents = []
        for s in sup.slots:
            if s.handle is None:
                continue
            rc = s.handle.poll()
            if rc is not None:
                sup._finish(s, rc)  # exited since the last tick: merge it here, exactly once
            else:
                agents.append(_record(sup, s))
        write_atomic(adopt_path(sup.swarm_dir, pid),
                     {"from_pid": os.getpid(), "to_pid": pid, "next_seq": sup.seq, "agents": agents})
    except Exception as e:  # nothing was handed over: undo the lock move and carry on as the supervisor
        transfer_lock(sup.root, os.getpid(), expect=pid)
        adopt_path(sup.swarm_dir, pid).unlink(missing_ok=True)
        sup.log(f"handoff to pid {pid} failed ({e!r}); lock restored, still supervising")
        return False
    sup.stopping = sup.handed_over = True  # only now: the answer is on disk
    if (read_json(sup.handoff_file) or {}).get("pid") == pid:
        sup.handoff_file.unlink(missing_ok=True)  # the acknowledgement; never someone else's newer claim
    sup.log(f"handoff to pid {pid}: {len(agents)} running agents left running, lock transferred; old supervisor exiting")
    return True


def request_handoff(root: Path, wait_s: float = ANSWER_S, clock: Callable[[], float] = time.monotonic,
                    sleep: Callable[[float], None] = time.sleep, pid: int | None = None,
                    alive: Callable[[int], bool] | None = None) -> dict | None:
    """New side: ask the live supervisor to hand over. None = refused (another upgrade is in flight, or no answer)."""
    pid = pid or os.getpid()
    alive = alive or (lambda p: default_state()[0](p) != "gone")
    runs = Path(root) / "runs"
    req, mine = runs / "swarm.handoff", adopt_path(runs / "swarm", pid)
    mine.unlink(missing_ok=True)  # only OUR stale answer; other requesters' files are never touched
    if not claim(req, pid, alive):
        return None  # a live requester is mid-request: no concurrent handoffs
    end = clock() + wait_s
    while clock() < end:
        data = read_adopt(mine.parent, pid)
        if data is not None:
            return data
        sleep(1.0)
    withdraw(req, pid)  # atomic rename: a late old supervisor now sees no claim
    data = read_adopt(mine.parent, pid)  # answered before it saw the withdrawal? then we adopt
    if data is None and lock_holder(root) == str(pid):  # it had already moved the lock: its answer is about to land
        end = clock() + EXTRA_S
        while data is None and clock() < end:
            sleep(1.0)
            data = read_adopt(mine.parent, pid)
    return data


def adopt(sup, data: dict) -> int:
    """Install the old supervisor's agents into this one's slots; resize to sup's slot count (retire extras)."""
    by_idx: dict[int, Slot] = {}
    for a in data.get("agents", []):
        cfg = dict(a["cfg"])
        cfg["own"], cfg["started_wall"] = Path(a["own"]), a["started_wall"]
        h = ProcHandle(a["pid"], sup.state, sup.kill_pid, sup.ident, a.get("ident"))
        if sup.state(a["pid"]) != "gone" and not h.same_process(full=True):
            sup.log(f"slot {a['slot']}: pid {a['pid']} is no longer the recorded agent (pid reused); treated as exited")
        s = Slot(a["slot"], a["role"], h, cfg, started=sup.clock() - max(0.0, time.time() - a["started_wall"]))
        by_idx[s.idx] = s
        if cfg.get("steps") != sup.steps or (sup.starter and cfg.get("starter") != sup.starter):
            sup.log(f"slot {s.idx}: adopted agent keeps its old settings (steps {cfg.get('steps')}, starter "
                    f"{cfg.get('starter')}); new settings apply to its refill")
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
