"""Shared table runs/bandit.json and per-run deltas. Merging is idempotent: a delta carries its run id and the
shared file remembers which ids it has absorbed, so a retried or concurrent merge never double-counts."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from pokeagent.bandit.table import Cells, absorb
from pokeagent.qmodels import atomic_json

MAX_MERGED_IDS = 5000
MAX_RECENT = 200  # runs whose cells are kept so a re-flushed delta can replace its earlier share


def load_cells(path: Path | str) -> Cells:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("cells", {})
    except (OSError, ValueError):
        return {}


def write_delta(path: Path | str, run_id: str, cells: Cells) -> None:
    atomic_json(path, {"run_id": run_id, "cells": cells})


def delta_path_for(own: Path) -> Path:
    """The bandit delta a swarm agent writes beside its memory file (agent3-7.json -> agent3-7.bandit.json)."""
    return own.with_name(own.stem + ".bandit.json")


def _acquire(path: Path) -> bool:
    """O_EXCL create; on Windows a lock that is mid-delete answers PermissionError, which just means busy."""
    from pokeagent import resources
    try:
        return resources._try_acquire(path)
    except PermissionError:
        return False


def _release(path: Path, tries: int = 50) -> None:
    """Windows refuses to unlink a file another process is probing with open(): back off and retry."""
    for i in range(tries):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.02)


@contextmanager
def _lock(shared: Path, wait_s: float = 30.0):
    from pokeagent import resources
    path = shared.with_suffix(".lock")
    end = time.monotonic() + wait_s
    while not _acquire(path):
        if resources._stale(path):
            resources._take_over(path)
        elif time.monotonic() >= end:
            raise resources.LockBusy(f"bandit merge lock busy: {path}")
        else:
            time.sleep(0.05)
    try:
        yield
    finally:
        _release(path)


def merge_delta(shared: Path | str, delta: Path | str, remove: bool = True) -> bool:
    """Fold one run's cumulative delta into the shared table under a lock.

    A delta is the run's running total, so it may be flushed (and merged) more than once. The shared file keeps the
    last MAX_RECENT runs' contributions: a repeat replaces that run's earlier share (subtract old, add new), never
    adds it twice. A run older than the window is only recognised by id and skipped. True when the table changed."""
    shared, delta = Path(shared), Path(delta)
    try:
        d = json.loads(delta.read_text(encoding="utf-8"))
        run_id, cells = d["run_id"], d["cells"]
    except (OSError, ValueError, KeyError):
        return False
    with _lock(shared):
        try:
            cur = json.loads(shared.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cur = {}
        merged, recent = cur.get("merged", []), cur.get("recent", {})
        table = cur.get("cells", {})
        changed = False
        if run_id in recent:
            if recent[run_id] != cells:
                absorb(table, recent[run_id], sign=-1)
                absorb(table, cells)
                changed = True
        elif run_id not in merged:
            absorb(table, cells)
            changed = True
        if changed:
            recent[run_id] = cells
            for old in list(recent)[:-MAX_RECENT]:
                del recent[old]
            ids = merged if run_id in merged else merged + [run_id]
            atomic_json(shared, {"cells": table, "merged": ids[-MAX_MERGED_IDS:], "recent": recent})
    if remove:
        delta.unlink(missing_ok=True)
    return changed
