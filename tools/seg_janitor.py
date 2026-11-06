"""Disk janitor for the curriculum's kept files (runs/segments/inputs/ job dirs, runs/segments/states/ candidates).

A job dir (map-memory snapshot + exact start state) and a candidate end state exist only so a new best can be replayed.
Anything older than MAX_AGE_S that no best in runs/segments.json points at is deleted; a newer one may belong to a job
that is still running.
"""
from __future__ import annotations

import shutil
from pathlib import Path

MAX_AGE_S = 24 * 3600


def sweep(root: Path, doc: dict, now: float, max_age_s: float = MAX_AGE_S) -> list[str]:
    """Delete stale kept files; returns what was removed (names)."""
    held_dirs, held_states = set(), set()
    for st in doc["stats"].values():
        for b in (st.get("best"), st.get("confirmed")):
            if b:
                if b.get("input"):
                    held_dirs.add(str(Path(b["input"]).parent))
                if b.get("state"):
                    held_states.add(str(Path(b["state"])))
    removed = []
    base = root / "runs" / "segments"
    for d in (base / "inputs").glob("*") if (base / "inputs").is_dir() else []:
        if str(d) not in held_dirs and now - d.stat().st_mtime > max_age_s:
            shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
            removed.append(d.name)
    for f in (base / "states").glob("*.cand.state") if (base / "states").is_dir() else []:
        if str(f) not in held_states and now - f.stat().st_mtime > max_age_s:
            f.unlink(missing_ok=True)
            removed.append(f.name)
    return removed
