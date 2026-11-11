"""One buffered writer for a run's per-step ``.jsonl`` appends.

Every press used to hit the disk three times: ``transitions.jsonl``, ``decisions.jsonl`` and a
``flush()`` after each so a tailing process could read along. ``JsonlBuffer`` keeps one line buffer
per file and drains all of them every ``every`` steps and on close - a crash loses at most ``every``
steps (the accepted bound) and the hot path does one write syscall per 50 steps per file instead of
one per line.

A writer exposes the file-object subset the per-step callers use: ``write(str)`` queues a line,
``flush()`` is a no-op (the buffer owns the cadence), ``close()`` drains and closes.
"""
from __future__ import annotations

from pathlib import Path

FLUSH_EVERY = 50  # steps between drains; a crash loses at most this many logged steps


class _Lines:
    """One buffered file: ``write`` queues a line, ``drain`` writes the queue and flushes."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("a", encoding="utf-8")
        self._lines: list[str] = []

    def write(self, s: str) -> None:
        self._lines.append(s)

    def _drain(self, fh) -> None:
        if self._lines:
            fh.write("".join(self._lines))
            self._lines.clear()
        fh.flush()

    def drain(self) -> None:
        if self._fh is not None:
            self._drain(self._fh)

    def flush(self) -> None:
        """Deliberately a no-op: per-line flushes are the cost this exists to remove."""

    def close(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                self._drain(fh)
            finally:
                fh.close()


class JsonlBuffer:
    """The per-step append cadence for one run: every open file shares one ``every``-step flush."""

    def __init__(self, every: int = FLUSH_EVERY) -> None:
        self.every = every
        self._files: dict[Path, _Lines] = {}
        self._closed = False

    def open(self, path: Path | str) -> _Lines:
        """The buffered writer for ``path``; the same path always returns the same writer."""
        path = Path(path)
        w = self._files.get(path)
        if w is None:
            if self._closed:
                raise ValueError(f"JsonlBuffer is closed; cannot open {path}")
            w = self._files[path] = _Lines(path)
        return w

    def tick(self, step: int) -> None:
        """Called once per press (``write_transition``): drain every file on the cadence."""
        if self.every and step % self.every == 0:
            self.flush()

    def flush(self) -> None:
        for w in self._files.values():
            w.drain()

    def close(self) -> None:
        """Drain and close every file; registered on the run's exit paths before ``os._exit``."""
        self._closed = True
        for w in self._files.values():
            w.close()
        self._files.clear()
