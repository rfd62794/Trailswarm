"""RunView: an incremental, read-only parse of one explore run dir, for the marathon stall rules.

Byte-offset reads like tools/swarm_watch.py (whole lines only: a half-written tail waits for the
next refresh), so a live run can be judged while it keeps writing. Press count = transitions.jsonl
line count (one line per press; the ``step`` field and the console.log ``--- step N/M`` headers are
the same ordinal, so console events map back to presses). Never touches any process.
"""
from __future__ import annotations

import json
import re
from collections import Counter, deque
from pathlib import Path

from pokeagent import training_progress as tp
from pokeagent.goals import GOALS, is_unverified
from pokeagent.intervene.lease import lease_active

STEP_RE = re.compile(r"^--- step (\d+)/\d+\s+map=0x([0-9a-fA-F]+)")
STALL_RE = re.compile(r"STALL #(\d+)")
THINKING = "thinking:"
THINK_PRESSES = 400  # presses the `thinking:` tail covers for the bundle's repeated lines
STALL_KEPT = 512     # escalation events remembered (the in-run counter can reach 100+)


def _new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    """Whole lines appended since ``offset`` (a torn tail waits; a truncated file restarts)."""
    try:
        if path.stat().st_size < offset:
            offset = 0
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return [], offset
    end = chunk.rfind(b"\n") + 1
    if end == 0:
        return [], offset
    return [ln.decode("utf-8", "replace") for ln in chunk[:end].splitlines()], offset + end


def find_runs(runs_dir: Path, tag_prefix: str) -> list[Path]:
    """explore-* dirs under ``runs_dir`` whose meta.json tag starts with ``tag_prefix``, newest
    first (swarm_watch.find_run_dir's mtime order); unreadable metas are skipped."""
    out = []
    for d in sorted(Path(runs_dir).glob("explore-*"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(meta.get("tag") or "").startswith(tag_prefix):
            out.append(d)
    return out


class RunView:
    """One run dir, parsed lazily. Call ``refresh()`` before judging; each refresh folds only the
    bytes appended since the last one into the summary the rules read."""

    def __init__(self, run_dir) -> None:
        self.dir = Path(run_dir)
        self.name = self.dir.name
        self.presses = 0
        self.last_pos: list | None = None
        self.segments: list[list] = []              # [map, first_press, last_press]
        self.goal_steps: list[tuple[str, int]] = []  # (goal, press) in landing order
        self.train_at = 0                            # press of the last levels.jsonl XP/level gain
        self.stall_count = 0                         # last "STALL #N" number console.log printed
        self._stalls: deque = deque(maxlen=STALL_KEPT)  # (n, press) escalation events
        self._think: deque = deque()                 # (press, text) of `thinking:` lines
        self._console_step = 0
        self._lv_marks: tp.Marks | None = None
        self._off: dict[str, int] = {}
        self._meta: dict | None = None
        self._meta_mtime = -1.0

    # -- files -------------------------------------------------------------------

    @property
    def meta(self) -> dict:
        """meta.json, re-read only when it changed (the run appends initial_goals after it starts)."""
        try:
            p = self.dir / "meta.json"
            mt = p.stat().st_mtime
            if mt != self._meta_mtime:
                self._meta = json.loads(p.read_text(encoding="utf-8"))
                self._meta_mtime = mt
        except (OSError, ValueError):
            if self._meta is None:
                self._meta = {}
        return self._meta or {}

    def _read(self, name: str) -> list[str]:
        lines, self._off[name] = _new_lines(self.dir / name, self._off.get(name, 0))
        return lines

    def refresh(self) -> "RunView":
        for line in self._read("transitions.jsonl"):
            try:
                to = json.loads(line)["to"]
                m = to[0]
            except (ValueError, KeyError, TypeError, IndexError):
                continue
            self.presses += 1
            self.last_pos = to
            if self.segments and self.segments[-1][0] == m:
                self.segments[-1][2] = self.presses
            else:
                self.segments.append([m, self.presses, self.presses])
        for line in self._read("goal_frames.jsonl"):
            try:
                row = json.loads(line)
                self.goal_steps.append((row["goal"], int(row.get("step") or 0)))
            except (ValueError, KeyError, TypeError):
                continue
        for line in self._read("levels.jsonl"):
            try:
                row = json.loads(line)
                cur = tp.marks(row.get("party"))
            except (ValueError, AttributeError):
                continue
            if self._lv_marks is not None and tp.gained(self._lv_marks, cur):
                self.train_at = int(row.get("step") or self.presses)
            self._lv_marks = cur
        for line in self._read("console.log"):
            self._console_line(line)
        return self

    def _console_line(self, line: str) -> None:
        m = STEP_RE.match(line)
        if m:
            self._console_step = int(m.group(1))
            return
        s = STALL_RE.search(line)
        if s:  # 'thinking: STALL #N detected here - escalating with X': counted, never a thinking row
            n = int(s.group(1))
            self.stall_count = n
            self._stalls.append((n, self._console_step))
            return
        if line.startswith(THINKING):
            self._think.append((self._console_step, line[len(THINKING):].strip()))
            while self._think and self._think[0][0] <= self._console_step - THINK_PRESSES:
                self._think.popleft()

    # -- derived state ------------------------------------------------------------

    def held(self) -> bool:
        """A fresh claude_hold.json lease: never judge (swarm_watch's rule, imported not copied)."""
        return lease_active(self.dir)

    @property
    def last_goal_press(self) -> int:
        return self.goal_steps[-1][1] if self.goal_steps else 0

    @property
    def last_goal_name(self) -> str:
        return self.goal_steps[-1][0] if self.goal_steps else ""

    @property
    def pending_goals(self) -> list[str]:
        """Ladder goals still ahead: GOALS minus goal_frames rows minus the goals the run's own
        start state settled (meta initial_goals, else the ``start`` checkpoint's prefix). Unverified
        goals never produce a goal_frames row, so they cannot count as pending."""
        done = {g for g, _ in self.goal_steps} | set(self.meta.get("initial_goals") or [])
        landed = [GOALS.index(g) for g in done if g in GOALS]
        if landed:  # the ladder is a chain: a landed goal settles every goal before it
            done |= set(GOALS[: max(landed) + 1])
        start = self.meta.get("start")
        if start in GOALS:
            done |= set(GOALS[: GOALS.index(start) + 1])
        return [g for g in GOALS if g not in done and not is_unverified(g)]

    @property
    def current_goal(self) -> str:
        """The first pending goal (what the bundle names as the run's aim), "" when the ladder is done."""
        return self.pending_goals[0] if self.pending_goals else ""

    def stalls_since(self, press: int) -> int:
        """Distinct ``STALL #`` escalations after ``press`` (the same burst's dupes count once)."""
        return len({(n, p) for n, p in self._stalls if p > press})

    @property
    def stall_burst_at(self) -> int:
        """Press of the first escalation after the last goal (0 = the current burst hasn't started)."""
        after = [p for _, p in self._stalls if p > self.last_goal_press]
        return min(after) if after else 0

    def thinking_counts(self) -> Counter:
        """`thinking:` lines of the last THINK_PRESSES presses, counted for the bundle."""
        return Counter(t for _, t in self._think)

    @property
    def current_map(self) -> int | None:
        return self.segments[-1][0] if self.segments else None
