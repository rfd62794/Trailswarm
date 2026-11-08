"""runs/spawn.lock during a supervisor handoff: the old supervisor re-points it at the new pid (never free in between)."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Callable

from swarm_claims import write_atomic


def lock_path(root: Path) -> Path:
    return Path(root) / "runs" / "spawn.lock"


def lock_holder(root: Path) -> str | None:
    """The holder's pid as text. Lock content is 'pid:uuid' since the takeover-race fix; the part before ':'
    is the pid, and old pid-only files still parse."""
    try:
        return lock_path(root).read_text().strip().split(":", 1)[0]
    except OSError:
        return None


def transfer_lock(root: Path, new_pid: int, expect: int | None = None) -> bool:
    """Point the lock at new_pid, only if it currently names expect (default: this process)."""
    if lock_holder(root) != str(os.getpid() if expect is None else expect):
        return False
    try:
        write_atomic(lock_path(root), str(new_pid))
        return True
    except OSError:
        return False


@contextlib.contextmanager
def adopt_lock(root: Path):
    """New side: take over the lock the old supervisor already pointed at us; refuse if it is not ours."""
    from pokeagent import resources
    if lock_holder(root) != str(os.getpid()):
        raise resources.LockBusy(f"{lock_path(root)} was not transferred to pid {os.getpid()}")
    try:
        yield
    finally:
        if lock_holder(root) == str(os.getpid()):
            with contextlib.suppress(OSError):
                lock_path(root).unlink()


def acquire_after_handoff(stack: contextlib.ExitStack, root: Path, pids: list[int], say: Callable[[str], None],
                          tries: int = 3, wait_s: float = 30.0) -> bool:
    """The old supervisor already gave its agents up, so we must supervise them whatever happens to the lock.
    Take the transferred lock, else a normal one (bounded retries); if all fail, carry on LOUDLY without it."""
    from pokeagent import resources
    try:
        stack.enter_context(adopt_lock(root))
        return True
    except resources.LockBusy:
        pass
    for _ in range(tries):
        try:
            stack.enter_context(resources.spawn_lock(root, wait_s=wait_s))
            return True
        except resources.LockBusy:
            continue
    say(f"WARNING: could not get runs/spawn.lock after the handoff; supervising adopted agents (pids {pids}) WITHOUT it. "
        f"Another process may hold it: check for a second supervisor.")
    return False
