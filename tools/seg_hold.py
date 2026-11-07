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
    """An aware datetime, or None if the text is not a usable timestamp (including out-of-range years, which
    astimezone() rejects on Windows)."""
    if not isinstance(text, str):
        return None
    try:
        t = datetime.fromisoformat(text)
        return t if t.tzinfo else t.astimezone()
    except (ValueError, OverflowError, OSError):
        return None


def path(root: Path) -> Path:
    return Path(root) / FILE


def parse(text: str) -> list[Hold]:
    """Every valid hold in the JSON text; [] if it is malformed. A bad entry is skipped on its own."""
    try:
        rows = json.loads(text)["holds"]
    except (ValueError, KeyError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    out: list[Hold] = []
    for r in rows:
        try:
            seg, text_until = r["segment"], r["until"]
            until = parse_until(text_until)
            if isinstance(seg, str) and seg and until is not None:
                out.append(Hold(seg, text_until, until, str(r.get("reason", ""))))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
    return out


def read_file(p: Path) -> list[Hold]:
    """Every valid hold in the file; [] if the file is missing, unreadable or malformed."""
    try:
        return parse(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


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
        except FileNotFoundError:
            self._sig, self._holds = None, []
            return self._holds
        except OSError:
            return self._holds           # transient (e.g. a writer holds the file): keep the last good holds
        sig = (st.st_mtime_ns, st.st_size)
        if sig != self._sig:
            try:
                text = self.path.read_text(encoding="utf-8")
            except OSError:
                return self._holds       # not cached: the next call retries the read
            except ValueError:
                text = ""                # undecodable content counts as malformed
            self._sig, self._holds = sig, parse(text)
        return self._holds
