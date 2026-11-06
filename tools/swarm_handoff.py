"""Rolling supervisor upgrade: hand a live swarm's agents to a NEW supervisor without stopping any of them.

New supervisor: request_handoff() claims runs/swarm.handoff exclusively (O_EXCL, holds its pid) and waits for
runs/swarm/adopt-<pid>.json (30 s, one more look after, else it refuses: no double supervision). Old supervisor:
hand_over() merges agents that already exited, writes adopt-<pid>.json (per live agent: slot, pid tree root, seed,
config, memory copy, run dir, start hash, process identity), moves runs/spawn.lock to the new pid, and exits WITHOUT
killing anyone. The new one adopts them: polls their pids, applies its watchdog, merges on exit, refills on its code.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Callable

from swarm_ident import SIGNATURE, Ident
from swarm_slot import Slot

ANSWER_S = 30.0


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

    def kill(self) -> None:
        if self._state(self.pid) != "gone" and self.same_process(full=True):
            self._kill(self.pid)


def default_state():
    from pokeagent.registry import process_state
    from swarm_proc import kill_tree
    return process_state, kill_tree


def _create_exclusive(path: Path, data: dict) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data))
    return True


def _write_atomic(path: Path, data: dict | str, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data if isinstance(data, str) else json.dumps(data, indent=indent))
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def adopt_path(swarm_dir: Path, pid: int) -> Path:
    return Path(swarm_dir) / f"adopt-{pid}.json"


def read_adopt(swarm_dir: Path, pid: int) -> dict | None:
    return _read_json(adopt_path(swarm_dir, pid))


def transfer_lock(root: Path, new_pid: int) -> bool:
    """Old side: point runs/spawn.lock at the new supervisor, only if it is ours. No window where it is free."""
    lock = Path(root) / "runs" / "spawn.lock"
    try:
        if lock.read_text().strip() != str(os.getpid()):
            return False
        _write_atomic(lock, str(new_pid))
        return True
    except OSError:
        return False


@contextlib.contextmanager
def adopt_lock(root: Path):
    """New side: take over the lock the old supervisor already pointed at us; refuse if it is not ours."""
    from pokeagent import resources
    lock = Path(root) / "runs" / "spawn.lock"
    try:
        ours = lock.read_text().strip() == str(os.getpid())
    except OSError:
        ours = False
    if not ours:
        raise resources.LockBusy(f"{lock} was not transferred to pid {os.getpid()}")
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            if lock.read_text().strip() == str(os.getpid()):
                lock.unlink()


def _run_dir(root: Path, seed: int, started_wall: float) -> str | None:
    try:
        from swarm_watch import find_run_dir
        d = find_run_dir(root, seed, started_wall)
        return str(d) if d else None
    except Exception:
        return None


def hand_over(sup) -> bool:
    """Old side. False = request not readable yet (try next tick). Otherwise: merge exited agents once, record the live
    ones, transfer the lock, leave them running; the caller exits its loop without kill_all."""
    req = _read_json(sup.handoff_file)
    if not req or not isinstance(req.get("pid"), int):
        return False
    sup.stopping = sup.handed_over = True
    agents = []
    for s in sup.slots:
        if s.handle is None:
            continue
        rc = s.handle.poll()
        if rc is not None:
            sup._finish(s, rc)  # exited since the last tick: merge it here, exactly once (the new side never sees it)
            continue
        cfg = {k: (str(v) if isinstance(v, Path) else v) for k, v in s.cfg.items()}
        wall = cfg.get("started_wall", time.time())
        created = sup.ident.created(s.handle.pid)
        agents.append({"slot": s.idx, "pid": s.handle.pid, "seed": cfg["seed"], "role": s.role, "own": cfg["own"],
                       "hash": cfg.get("hash"), "started_wall": wall, "run_dir": _run_dir(sup.root, cfg["seed"], wall),
                       "ident": {"created": created, "sig": SIGNATURE} if created is not None else {"sig": SIGNATURE},
                       "cfg": cfg})
    moved = transfer_lock(sup.root, req["pid"])
    _write_atomic(adopt_path(sup.swarm_dir, req["pid"]),
                  {"from_pid": os.getpid(), "to_pid": req["pid"], "next_seq": sup.seq, "agents": agents})
    sup.handoff_file.unlink(missing_ok=True)  # the acknowledgement: the adoption exists, the request is served
    sup.log(f"handoff to pid {req['pid']}: {len(agents)} running agents left running, lock "
            f"{'transferred' if moved else 'NOT ours to transfer'}; old supervisor exiting")
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
    for _ in range(2):
        if _create_exclusive(req, {"pid": pid, "at": time.time()}):
            break
        other = _read_json(req)
        if other is None or alive(int(other.get("pid", 0))):
            return None  # someone else is mid-request: no concurrent handoffs
        req.unlink(missing_ok=True)  # its requester died
    else:
        return None
    end = clock() + wait_s
    while clock() < end:
        data = read_adopt(mine.parent, pid)
        if data is not None:
            return data
        sleep(1.0)
    data = read_adopt(mine.parent, pid)  # a late answer still counts: the old supervisor already gave up its agents
    if data is None and (_read_json(req) or {}).get("pid") == pid:
        req.unlink(missing_ok=True)
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
