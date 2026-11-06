"""File protocol helpers for the supervisor handoff: atomic JSON files and the exclusive runs/swarm.handoff claim.

A claim is {"pid": requester}. It is published fully written (hard link), so nobody reads it half-written. A dead claim
(requester gone, or an empty/torn file older than STALE_CLAIM_S) is replaced under a dedicated O_EXCL replacer lock, so
two replacers can never delete each other's fresh claim.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Callable

STALE_CLAIM_S = 10.0
STALE_REPLACER_S = 30.0


def write_atomic(path: Path, data: dict | str, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data if isinstance(data, str) else json.dumps(data, indent=indent))
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def create_exclusive(path: Path, data: dict) -> bool:
    """Publish a fully written file at path only if nobody has it (hard link = atomic, never seen half-written)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.new")
    tmp.write_text(json.dumps(data))
    try:
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    except OSError:  # no hard links here: plain exclusive create
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data))
        return True
    finally:
        tmp.unlink(missing_ok=True)


def claim_is_live(req: Path, alive: Callable[[int], bool]) -> bool:
    cur = read_json(req)
    if cur is None:  # empty/torn: dead only once old enough that its writer cannot still be writing
        try:
            return time.time() - req.stat().st_mtime <= STALE_CLAIM_S
        except OSError:
            return False
    return alive(int(cur.get("pid") or 0))


@contextlib.contextmanager
def replacer_lock(req: Path):
    """Yields True if we hold the (O_EXCL) replacer lock for this claim, False if another replacer does."""
    path = req.with_name(req.name + ".replace")
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > STALE_REPLACER_S:
                    tomb = path.with_name(f"{path.name}.stale.{os.getpid()}")
                    os.rename(path, tomb)  # atomic: exactly one breaker wins; never delete a fresh lock by name
                    tomb.unlink(missing_ok=True)
                    continue
            except OSError:
                continue  # vanished or lost the break race: look again
            yield False
            return
        os.close(fd)
        try:
            yield True
        finally:
            path.unlink(missing_ok=True)
        return
    yield False


def claim(req: Path, pid: int, alive: Callable[[int], bool]) -> bool:
    """Take runs/swarm.handoff for pid. False = a live requester has it, or another replacer is busy: back off."""
    if create_exclusive(req, {"pid": pid, "at": time.time()}):
        return True
    with replacer_lock(req) as held:
        if not held or claim_is_live(req, alive):
            return False
        req.unlink(missing_ok=True)  # dead claim; we are the only replacer
        return create_exclusive(req, {"pid": pid, "at": time.time()})


def withdraw(req: Path, pid: int) -> None:
    """Remove our claim by atomic rename (a late old supervisor then sees it gone); never someone else's."""
    if (read_json(req) or {}).get("pid") != pid:
        return
    aside = req.with_name(f"{req.name}.withdrawn.{pid}")
    try:
        os.rename(req, aside)
    except OSError:
        return
    if (read_json(aside) or {}).get("pid") != pid:  # replaced between our check and the rename: put it back
        with contextlib.suppress(OSError):
            os.link(aside, req)
    aside.unlink(missing_ok=True)
