"""Per-run artifacts: a run directory holding log.jsonl, notes.txt, snapshots.

Each run gets ``runs/<YYYYMMDD-HHMMSS>/``. Every step is appended to
``log.jsonl``; the agent's own memory lives in ``notes.txt`` and is read back
verbatim each step; save-state snapshots land next to them; ``summary.json``
is written when the run ends.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

NOTES_LIMIT = 4000
RECENT_LIMIT = 10


class RunLog:
    """Owns the run directory and the files inside it.

    ``now`` may be a ``datetime`` or a callable returning one; tests inject a
    fixed value for deterministic directory names.
    """

    def __init__(
        self,
        root: Path = Path("runs"),
        now: datetime | Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        stamp = now() if callable(now) else (now or datetime.now())
        self.run_dir = self._fresh_dir(stamp.strftime("%Y%m%d-%H%M%S"))
        self.log_path = self.run_dir / "log.jsonl"
        self.notes_path = self.run_dir / "notes.txt"
        self._entries: list[dict] = []

    def _fresh_dir(self, stamp: str) -> Path:
        """First non-existing runs/<stamp>[-N]/ directory; creates and returns it."""
        candidate = self.root / stamp
        suffix = 1
        while candidate.exists():
            candidate = self.root / f"{stamp}-{suffix}"
            suffix += 1
        candidate.mkdir(parents=True)
        return candidate

    def append(self, entry: dict) -> None:
        """Write one JSON line to log.jsonl and keep it for recent()."""
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        self._entries.append(entry)

    def recent(self, n: int = RECENT_LIMIT) -> list[dict]:
        """The last n entries appended this run (kept in memory)."""
        return self._entries[-n:]

    def notes(self) -> str:
        """Contents of notes.txt, or "" if the agent has not written any yet."""
        if not self.notes_path.is_file():
            return ""
        return self.notes_path.read_text(encoding="utf-8")

    def add_note(self, text: str) -> None:
        """Append one line to notes.txt, trimming to the newest NOTES_LIMIT chars."""
        body = self.notes()
        if body and not body.endswith("\n"):
            body += "\n"
        body += str(text).rstrip("\n") + "\n"
        if len(body) > NOTES_LIMIT:
            body = self._trim(body)
        self.notes_path.write_text(body, encoding="utf-8")

    @staticmethod
    def _trim(body: str) -> str:
        """Newest NOTES_LIMIT chars of body, starting on a line boundary."""
        tail = body[-NOTES_LIMIT:]
        nl = tail.find("\n")
        if nl == -1 or nl == len(tail) - 1:
            return tail
        return tail[nl + 1 :]

    def state_path(self, step: int) -> Path:
        """Snapshot path for a step: ``state_<step:04d>.state``."""
        return self.run_dir / f"state_{step:04d}.state"

    def write_summary(self, result: Any) -> None:
        """Write summary.json from a result object (dataclass or mapping)."""
        data = asdict(result) if is_dataclass(result) else dict(result)
        (self.run_dir / "summary.json").write_text(
            json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8"
        )
