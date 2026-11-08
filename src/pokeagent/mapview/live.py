"""The live-position contract: ``<source>/live/<agent>.json``, one per displayed agent.

A display window publishes where its emulator is right now (about 10 Hz, atomically via a
``.tmp`` sibling + ``os.replace``); the viewer re-reads the files on its refresh clock.
``x``/``y`` use the ghost-point convention so the live agent lands on the same stitched
space; ``screen_x``/``screen_y`` are the sprite's top-left in the live frame, or None.
A record older than ``STALE_S`` counts as absent, so a stopped writer leaves no frozen mark.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pokeagent.mapview.live_schema import SCHEMA, safe_name, valid as _valid

STALE_S = 5.0                  # a record this old counts as gone (the writer stopped)


@dataclass(frozen=True)
class LivePos:
    agent: str
    run: str                     # the recorded attempt being replayed, "" when unknown
    area: str
    x: float
    y: float
    screen_x: int | None
    screen_y: int | None
    updated_at: float
    screen_w: int | None = None   # the sprite's own tile box, when the writer knows it
    screen_h: int | None = None


def write_live(source: Path, record: dict) -> None:
    """Validate and atomically write one schema-1 record; a viewer file must never kill
    the writer, so any failure here (bad record, I/O error) returns quietly."""
    if not _valid(record):
        return
    live = Path(source) / "live"
    stem = safe_name(record["agent"])
    path, tmp = live / f"{stem}.json", live / f"{stem}.json.tmp"
    try:
        live.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)


def read_live(path) -> LivePos | None:
    """Parse one live file tolerantly: None for unreadable, invalid JSON, wrong schema,
    missing keys or non-finite numbers. Never raises."""
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not _valid(rec):
        return None
    sx, sy = rec["screen_x"], rec["screen_y"]
    return LivePos(rec["agent"], rec["run"], rec["area"], float(rec["x"]), float(rec["y"]),
                   None if sx is None else int(sx), None if sy is None else int(sy),
                   float(rec["updated_at"]), rec.get("screen_w"), rec.get("screen_h"))


class LiveStore:
    """Every readable record under ``<source>/live``, fresh or stale: refresh re-parses
    only files whose (mtime, size) stamp changed, forgets vanished ones, and hides the
    stale ones from ``positions`` (they stay cached - an unchanged file is never re-parsed)."""

    def __init__(self) -> None:
        self._files: dict[str, tuple[tuple[int, int], LivePos]] = {}
        self._bad: dict[str, tuple[int, int]] = {}
        self._fresh: set[str] = set()
        self.parsed = 0                       # total parses (tests count re-parses)

    def positions(self) -> dict[str, LivePos]:
        return {p.agent: p for f, (_s, p) in self._files.items() if f in self._fresh}

    def refresh(self, source: Path, now: float) -> bool:
        """One stat per file plus a parse of new/changed ones only. True on any change."""
        try:
            files = {p.name: p for p in (Path(source) / "live").glob("*.json") if p.is_file()}
        except OSError:
            files = {}
        live: dict[str, tuple[tuple[int, int], LivePos]] = {}
        fresh: set[str] = set()
        for fname, path in files.items():
            try:
                s = path.stat()
            except OSError:
                if fname in self._files:                  # transient: keep the last good record
                    live[fname] = self._files[fname]
                    if fname in self._fresh and now - live[fname][1].updated_at <= STALE_S:
                        fresh.add(fname)
                continue
            stamp = (s.st_mtime_ns, s.st_size)
            rec = self._files.get(fname)
            if rec is not None and rec[0] == stamp:
                pos = rec[1]
            elif self._bad.get(fname) == stamp:
                pos = None
            else:
                pos, self.parsed = read_live(path), self.parsed + 1
                if pos is None:
                    self._bad[fname] = stamp
                else:
                    self._bad.pop(fname, None)
            if pos is None and rec is not None:
                pos = rec[1]                              # transient read failure: keep the last good one
            if pos is None:
                continue
            live[fname] = (stamp, pos)
            if now - pos.updated_at <= STALE_S:
                fresh.add(fname)
        self._bad = {f: st for f, st in self._bad.items() if f in files}
        old = {f: p for f, (_s, p) in self._files.items() if f in self._fresh}
        new = {f: p for f, (_s, p) in live.items() if f in fresh}
        self._files, self._fresh = live, fresh
        return new != old
