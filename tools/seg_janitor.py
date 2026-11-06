"""Disk janitor for the curriculum's kept files (runs/segments/inputs/ job dirs, runs/segments/states/ candidates).

A job dir (map-memory snapshot + exact start state) and a candidate end state exist only so a new best can be replayed.
Anything whose NEWEST file is older than MAX_AGE_S and that no best in runs/segments.json points at is deleted (a job
that is still running keeps touching its dir). Only paths inside runs/segments are ever touched; failures are logged.
``dry_run=True`` returns what would be deleted and deletes nothing.
"""
from __future__ import annotations

from pathlib import Path

from seg_store import remove_tree

MAX_AGE_S = 24 * 3600


def newest_mtime(path: Path) -> float:
    """Newest mtime of a file, or of anything inside a directory (the dir's own mtime only changes on add/remove)."""
    if path.is_file():
        return path.stat().st_mtime
    times = [p.stat().st_mtime for p in path.rglob("*") if p.exists()]
    return max(times, default=path.stat().st_mtime)


def sweep(root: Path, doc: dict, now: float, max_age_s: float = MAX_AGE_S, dry_run: bool = False, log=print) -> list[str]:
    """Delete (or with dry_run only list) stale kept files; returns their names."""
    held_dirs, held_states = set(), set()
    for st in doc["stats"].values():
        for b in (st.get("best"), st.get("confirmed")):
            if b:
                if b.get("input"):
                    held_dirs.add(str(Path(b["input"]).parent))
                if b.get("state"):
                    held_states.add(str(Path(b["state"])))
    base = Path(root) / "runs" / "segments"
    stale: list[Path] = []
    inputs, states = base / "inputs", base / "states"
    for d in sorted(inputs.glob("*")) if inputs.is_dir() else []:
        if str(d) not in held_dirs and now - newest_mtime(d) > max_age_s:
            stale.append(d)
    for f in sorted(states.glob("*.cand.state")) if states.is_dir() else []:
        if str(f) not in held_states and now - newest_mtime(f) > max_age_s:
            stale.append(f)
    removed = []
    for p in stale:
        if dry_run:
            removed.append(p.name)
        elif p.is_dir():
            if remove_tree(root, p, log):
                removed.append(p.name)
        else:
            try:
                p.unlink(missing_ok=True)
                removed.append(p.name)
            except OSError as e:
                log(f"curriculum: could not delete {p}: {e!r}")
    return removed
