"""Go-Explore archive on disk (plan D4): ``runs/goexplore/<run-id>/`` layout.

``archive.json`` (written atomically, tmp + os.replace like statefp.write) plus ``cells/<cid>.state``
with ``.fp.json`` / ``.goals.json`` sidecars. Capped at 1,000 cells; eviction drops the lowest
``select.weight`` leaf - never a best-per-goals cell, never a protected one, never one with children.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath

from pokeagent import checkpoint_goals, statefp
from pokeagent.goexplore import select
from pokeagent.goexplore.archive import Archive, Entry

ARCHIVE_FILE = "archive.json"
VERSION = 1


def atomic_write(path: Path, text: str) -> None:
    """Write via a tmp file in the SAME directory then os.replace; a failure leaves the old file
    intact and no tmp behind."""
    tmp = Path(path).with_name(f"{Path(path).name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save(archive: Archive, root: Path) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    payload = {"v": VERSION, "cap": archive.cap,
               "entries": {cid: e.to_dict() for cid, e in archive.entries.items()}}
    atomic_write(root / ARCHIVE_FILE, json.dumps(payload, sort_keys=True))


def load(root: Path) -> Archive:
    """Empty Archive when no archive.json; a present but unreadable, invalid or other-version file
    raises ValueError - a killed driver must not "resume" into nothing."""
    path = Path(root) / ARCHIVE_FILE
    if not path.exists():
        return Archive()
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or d.get("v") != VERSION or not isinstance(d.get("entries"), dict):
            raise ValueError("bad shape or version")
        a = Archive(cap=d.get("cap", 1000))
        a.entries = {cid: Entry.from_dict(e) for cid, e in d["entries"].items()}
        for cid, e in a.entries.items():   # evict() unlinks root/state: a state path must stay inside cells/
            if PurePosixPath(e.state).parts[:1] != ("cells",) or ".." in PurePosixPath(e.state).parts:
                raise ValueError(f"cell {cid} state path {e.state!r} is outside cells/")
        return a
    except Exception as exc:
        raise ValueError(f"cannot load archive {path}: {exc}") from exc


def add_state(emu, root: Path, cid: str, source_run: str | None = None,
              inherit: Path | str | None = None) -> str:
    """Save the emulator state as ``cells/<cid>.state`` (tmp then os.replace), stamp its RAM
    fingerprint, return the relative name."""
    cells = Path(root) / "cells"
    cells.mkdir(parents=True, exist_ok=True)
    final = cells / f"{cid}.state"
    tmp = cells / f"{cid}.{os.getpid()}.tmp"
    emu.save_state(tmp)
    os.replace(tmp, final)
    statefp.stamp(emu, final, source_run, inherit=inherit)
    return f"cells/{cid}.state"


def evict(archive: Archive, root: Path, protected: frozenset[str] = frozenset(),
          on_route: frozenset[str] = frozenset()) -> list[str]:
    """Drop the lowest-weight leaf cells until ``len(archive) <= cap``.

    A candidate is not best-per-goals, not protected and has no children in the archive (recomputed
    each round: removing a leaf can free its parent). If no candidate exists, stop and return what
    was evicted even while still over cap - never drop a protected or best-per-goals cell to make
    room. The caller calls ``save`` afterwards."""
    evicted: list[str] = []
    while len(archive) > archive.cap:
        best = archive.best_per_goals()
        cands = [c for c in archive.entries
                 if c not in best and c not in protected and not archive.children_of(c)]
        if not cands:
            break
        cid = min(cands, key=lambda c: (select.weight(archive.entries[c], c in on_route), c))
        victim = archive.entries.pop(cid)
        state = Path(root) / victim.state
        for p in (state, statefp.sidecar(state), checkpoint_goals.sidecar(state)):
            p.unlink(missing_ok=True)
        evicted.append(cid)
    return evicted
