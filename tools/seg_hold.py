"""Curriculum hold list: runs/curriculum_hold.json names segments the scheduler must not pick until a deadline.

Use it when a segment cannot complete yet (a stall whose fix is still being built) and would otherwise eat slots.
A hold matches a candidate whose key equals the hold's segment, or whose stem (the part before "@") does. A missing
or malformed file means no holds; a malformed entry is skipped on its own. Writes are atomic (temp file + os.replace).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

FILE = Path("runs") / "curriculum_hold.json"


@dataclass(frozen=True)
class Hold:
    segment: str
    until_text: str          # as written in the file, logged as-is
    until: datetime          # aware; a naive timestamp is read as local time
    reason: str

    def covers(self, key: str) -> bool:
        return self.segment in (key, key.split("@", 1)[0])


def parse_until(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def path(root: Path) -> Path:
    return Path(root) / FILE


def read_file(p: Path) -> list[Hold]:
    """Every valid hold in the file; [] if the file is missing or malformed."""
    try:
        rows = json.loads(Path(p).read_text(encoding="utf-8"))["holds"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    out: list[Hold] = []
    for r in rows:
        try:
            seg, text = r["segment"], r["until"]
        except (KeyError, TypeError):
            continue
        until = parse_until(text)
        if isinstance(seg, str) and seg and until is not None:
            out.append(Hold(seg, text, until, str(r.get("reason", ""))))
    return out


def write_file(p: Path, holds: list[Hold]) -> None:
    """Atomic replace, so a supervisor re-reading the file never sees a half-written list."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"segment": h.segment, "until": h.until_text, "reason": h.reason} for h in holds]
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"holds": rows}, indent=1), encoding="utf-8")
    os.replace(tmp, p)


class HoldFile:
    """Holds for one root, re-read only when the file's (mtime, size) changes."""

    def __init__(self, root: Path):
        self.path = path(root)
        self._sig: tuple[int, int] | None = None
        self._holds: list[Hold] = []

    def current(self) -> list[Hold]:
        try:
            st = self.path.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        if sig != self._sig:
            self._sig = sig
            self._holds = read_file(self.path) if sig else []
        return self._holds
