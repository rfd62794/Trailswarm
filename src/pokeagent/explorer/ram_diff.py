"""Event RAM diffs: what changed in WRAM+HRAM across a meaningful event, minus the bytes that always change.

Opt-in (``--ram-diff``). The Presser snapshots RAM before and after each press; ``end`` classifies the press
(ram_event_kinds), diffs the snapshots, drops the learned 'noisy' set and appends a compact record to
``runs/<run>/ram_events.jsonl``. A replay trace (``ram_trace.jsonl``: frame offset + button of every emulator
press) is written alongside so ramlab can re-run the same run headlessly to verify a finding.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pokeagent.explorer.ram_event_kinds import HRAM_LEN, HRAM_START, WRAM_LEN, WRAM_START, addr_of, classify, first_line

_NONZERO = re.compile(rb"[^\x00]")


def snapshot(emu: Any) -> bytes:
    return bytes(emu.read_range(WRAM_START, WRAM_LEN)) + bytes(emu.read_range(HRAM_START, HRAM_LEN))


def changed_offsets(pre: bytes, post: bytes) -> list[int]:
    """Offsets where the snapshots differ (xor + a C-level regex scan: cheap on 8 KB)."""
    if pre == post:
        return []
    x = (int.from_bytes(pre, "big") ^ int.from_bytes(post, "big")).to_bytes(len(pre), "big")
    return [m.start() for m in _NONZERO.finditer(x)]


class RamDiffer:
    def __init__(self, path: Path, *, max_changed: int = 96, max_records: int = 4000, step_every: int = 8,
                 noise_rate: float = 0.9, noise_min: int = 40) -> None:
        self.path, self.max_changed, self.max_records, self.step_every = Path(path), max_changed, max_records, step_every
        self.noise_rate, self.noise_min = noise_rate, noise_min
        self.noisy: set[int] = set()          # snapshot offsets that change almost every frame / press
        self.records = 0
        self.spent = 0.0                      # seconds spent in begin/end (overhead accounting)
        self.plain = 0                        # presses with no event seen so far
        self._plain_hits: Counter = Counter()
        self._freq: Counter = Counter()      # how often each offset changed over all presses (rare bytes win truncation)
        self._pre: bytes = b""
        self._goals = 0
        self._emu: Any = None
        self._t0 = 0
        self._f = self.path.open("a", encoding="utf-8")
        self._trace = (self.path.parent / "ram_trace.jsonl").open("a", encoding="utf-8")

    # --- startup -------------------------------------------------------------------------------------------
    def attach(self, emu: Any, meta: dict | None = None) -> None:
        """Start the replay trace at the emulator's current frame (call right after loading the start state)."""
        self._emu, self._t0 = emu, getattr(emu, "frames", 0)
        self._trace.write(json.dumps({"t0": 0, **(meta or {})}) + "\n")
        if hasattr(emu, "on_press"):
            emu.on_press = self._note_press

    def _note_press(self, button: Any, hold: int, settle: int) -> None:
        self._trace.write(json.dumps([self._emu.frames - self._t0, str(button.value), hold, settle]) + "\n")

    def learn_noise(self, emu: Any, rounds: int = 48, gap: int = 2, thresh: float = 0.2) -> int:
        """Tick with no input and count which bytes change between frame pairs; the frequent ones are noise."""
        hits: Counter = Counter()
        prev = snapshot(emu)
        for _ in range(rounds):
            emu.tick(gap)
            cur = snapshot(emu)
            hits.update(changed_offsets(prev, cur))
            prev = cur
        self.noisy |= {o for o, n in hits.items() if n >= thresh * rounds}
        self._f.write(json.dumps({"meta": "noise", "n": len(self.noisy), "rounds": rounds}) + "\n")
        return len(self.noisy)

    # --- per press -----------------------------------------------------------------------------------------
    def begin(self, ctx: Any) -> None:
        t = time.perf_counter()
        self._pre = snapshot(ctx.emu)
        self._goals = len(ctx.goal_steps)
        self.spent += time.perf_counter() - t

    def end(self, ctx: Any, fr: Any) -> None:
        t = time.perf_counter()
        try:
            self._end(ctx, fr)
        finally:
            self.spent += time.perf_counter() - t

    def _end(self, ctx: Any, fr: Any) -> None:
        post = snapshot(ctx.emu)
        events, vals = classify(self._pre, post, fr, len(ctx.goal_steps) - self._goals, ctx.last_text)
        offs = changed_offsets(self._pre, post)
        self._freq.update(offs)
        if not events:
            self._learn_from_plain(offs)
            self.plain += 1
            if self.plain % self.step_every:
                return
            events = ["step"]
        self._write(ctx, fr, events, vals, [o for o in offs if o not in self.noisy], post)

    def _learn_from_plain(self, offs: list[int]) -> None:
        self._plain_hits.update(offs)
        n = self.plain + 1
        if n >= self.noise_min and n % 20 == 0:
            self.noisy |= {o for o, c in self._plain_hits.items() if c >= self.noise_rate * n}

    def diff(self, post: bytes, offs: list[int]) -> tuple[list[list[int]], int]:
        keep = offs if len(offs) <= self.max_changed else sorted(sorted(offs, key=lambda o: (self._freq[o], o))[: self.max_changed])
        return [[addr_of(o), self._pre[o], post[o]] for o in keep], len(offs)

    def _write(self, ctx: Any, fr: Any, events: list[str], vals: dict, offs: list[int], post: bytes) -> None:
        if self.records >= self.max_records:
            return
        d, n = self.diff(post, offs)
        rec = {"step": ctx.step, "ev": events, "map": fr.after[0], "x": fr.after[1], "y": fr.after[2],
               "text": first_line(fr.text or ctx.last_text), "vals": vals, "d": d}
        if n > len(d):
            rec["n"] = n
        self._f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.records += 1
        if self.records % 25 == 0:
            self.flush()

    def flush(self) -> None:
        self._f.flush(); self._trace.flush()

    def close(self) -> None:
        self.flush(); self._f.close(); self._trace.close()


def start_ram_diff(ctx: Any, emu: Any, run_dir: Path, state: str | None, rom: str) -> RamDiffer:
    """Wire a RamDiffer into ``ctx``: call right after the start state is loaded, before the first press."""
    rd = RamDiffer(Path(run_dir) / "ram_events.jsonl")
    sha = hashlib.sha1(Path(state).read_bytes()).hexdigest() if state and Path(state).is_file() else ""
    rd.attach(emu, {"start": Path(state).stem if state else "baseline", "state_sha1": sha, "lead_ticks": 30, "rom": Path(rom).name})
    rd.learn_noise(emu)
    ctx.ram_diff = rd
    return rd
