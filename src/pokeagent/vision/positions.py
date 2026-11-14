"""The per-sampled-frame position log: one JSON line per frame, capped by bytes."""
from __future__ import annotations

import json
from pathlib import Path

MAX_BYTES = 50_000_000


class PositionLog:
    """Appends {"f","run","area","player":[x,y],"ents":[[ident,label,x,y,move],...]} to
    positions.jsonl. Entity positions are map tile coordinates; a stationary entity is logged
    on every sampled frame, not only on change. One line-buffered handle, closed by close()."""

    def __init__(self, root, *, max_bytes: int = MAX_BYTES) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "positions.jsonl"
        self._bytes = self._path.stat().st_size if self._path.is_file() else 0
        self._fh = self._path.open("a", encoding="utf-8", buffering=1)
        self.capped = self._bytes >= self.max_bytes

    def append(self, frame: int, run: str, area: str, player, ents) -> None:
        """One line for one sampled frame; silently stops once the byte cap is reached."""
        if self.capped:
            return
        line = json.dumps({"f": frame, "run": run, "area": area,
                           "player": list(player) if player is not None else None,
                           "ents": [list(e) for e in ents]}, separators=(",", ":")) + "\n"
        self._fh.write(line)
        self._bytes += len(line.encode("utf-8"))
        if self._bytes >= self.max_bytes:
            self.capped = True

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()
