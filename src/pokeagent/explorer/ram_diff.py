"""Event RAM diffs: what changed in WRAM+HRAM across a meaningful event, minus the bytes that always change.

Opt-in (``--ram-diff``). The Presser snapshots RAM before and after each press; ``end`` classifies the press
(ram_event_kinds), diffs the snapshots, drops the learned 'noisy' set and appends a compact record to
``runs/<run>/ram_events.jsonl``. A replay trace (``ram_trace.jsonl``: frame offset + button of every emulator
press) is written alongside so ramlab can re-run the same run headlessly to verify a finding.

Recording is fail-soft (any internal error just switches it off) and bounded (after ``max_records`` records it
stops snapshotting and detaches the press hook). Noise is learned from the first ``warm`` presses, so no idle
frames are emulated and game timing/RNG are exactly what they would be without recording.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pokeagent.explorer.ram_event_kinds import HRAM_LEN, HRAM_START, WRAM_LEN, WRAM_START, addr_of, classify, first_line

START_COPY = "ram_start.state"
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
                 noise_rate: float = 0.9, noise_min: int = 40, warm: int = 40, max_trace: int = 60000) -> None:
        self.path, self.max_changed, self.max_records, self.step_every = Path(path), max_changed, max_records, step_every
        self.noise_rate, self.noise_min, self.warm, self.max_trace = noise_rate, noise_min, warm, max_trace
        self.noisy: set[int] = set()          # snapshot offsets that change almost every press
        self.records = 0
        self.spent = 0.0                      # seconds spent in begin/end (overhead accounting)
        self.plain = 0                        # presses with no event seen so far
        self.presses = 0
        self.off = False                      # True once capped or failed: no more snapshots, no more trace
        self._warm_done = warm <= 0
        self._warm_hits: Counter = Counter()
        self._buffer: list = []
        self._plain_hits: Counter = Counter()
        self._freq: Counter = Counter()       # how often each offset changed over all presses (rare bytes win truncation)
        self._pre: bytes = b""
        self._goals = 0
        self._armed = False
        self._traced = 0
        self._emu: Any = None
        self._t0 = 0
        self._f = self.path.open("a", encoding="utf-8")
        self._trace = (self.path.parent / "ram_trace.jsonl").open("a", encoding="utf-8")

    # --- startup / shutdown ---------------------------------------------------------------------------------
    def attach(self, emu: Any, meta: dict | None = None) -> None:
        """Start the replay trace at the emulator's current frame (call right after loading the start state)."""
        self._emu, self._t0 = emu, getattr(emu, "frames", 0)
        self._trace.write(json.dumps({"t0": 0, **(meta or {})}) + "\n")
        if hasattr(emu, "on_press"):
            emu.on_press = self._note_press

    def _note_press(self, button: Any, hold: int, settle: int) -> None:
        if self.off:
            return
        try:
            self._trace.write(json.dumps([self._emu.frames - self._t0, str(button.value), hold, settle]) + "\n")
            self._traced += 1
            if self._traced >= self.max_trace:
                self.stop()
        except Exception:
            self.stop()

    def stop(self) -> None:
        """Stop recording for good (cap reached or an error): detach the press hook and write what is buffered."""
        if self.off:
            return
        self.off = True
        try:
            if self._emu is not None and getattr(self._emu, "on_press", None) == self._note_press:
                self._emu.on_press = None
            self._finish_warmup()
            self.flush()
        except Exception:
            pass

    # --- per press -----------------------------------------------------------------------------------------
    def begin(self, ctx: Any) -> None:
        self._armed = False
        if self.off:
            return
        t = time.perf_counter()
        try:
            self._pre = snapshot(ctx.emu)
            self._goals = len(ctx.goal_steps)
            self._armed = True
        except Exception:
            self.stop()
        self.spent += time.perf_counter() - t

    def end(self, ctx: Any, fr: Any) -> None:
        if self.off or not self._armed:
            return
        t = time.perf_counter()
        try:
            self._end(ctx, fr)
        except Exception:
            self.stop()
        finally:
            self.spent += time.perf_counter() - t

    def _end(self, ctx: Any, fr: Any) -> None:
        post = snapshot(ctx.emu)
        events, vals = classify(self._pre, post, fr, len(ctx.goal_steps) - self._goals, ctx.last_text)
        offs = changed_offsets(self._pre, post)
        self._freq.update(offs)
        self.presses += 1
        if not self._warm_done:
            self._warm_hits.update(offs)
        if not events:
            self._learn_from_plain(offs)
            self.plain += 1
            if self.plain % self.step_every:
                self._maybe_finish_warmup()
                return
            events = ["step"]
        base = {"step": ctx.step, "ev": events, "map": fr.after[0], "x": fr.after[1], "y": fr.after[2],
                "text": first_line(fr.text or ctx.last_text), "vals": vals}
        triples = [(o, self._pre[o], post[o]) for o in offs]
        if self._warm_done:
            self._emit(base, triples)
        else:
            self._buffer.append((base, triples))
        self._maybe_finish_warmup()
        if self.records >= self.max_records:
            self.stop()

    def _maybe_finish_warmup(self) -> None:
        if self.presses >= self.warm:
            self._finish_warmup()

    def _finish_warmup(self) -> None:
        if self._warm_done:
            return
        self._warm_done = True
        n = min(self.presses, self.warm)
        self.noisy |= {o for o, c in self._warm_hits.items() if n and c >= self.noise_rate * n}
        self._warm_hits.clear()
        buffered, self._buffer = self._buffer, []
        for base, triples in buffered:
            self._emit(base, triples)

    def _learn_from_plain(self, offs: list[int]) -> None:
        self._plain_hits.update(offs)
        n = self.plain + 1
        if n >= self.noise_min and n % 20 == 0:
            self.noisy |= {o for o, c in self._plain_hits.items() if c >= self.noise_rate * n}

    def _emit(self, base: dict, triples: list) -> None:
        if self.records >= self.max_records:
            return
        keep = [t for t in triples if t[0] not in self.noisy]
        n = len(keep)
        if n > self.max_changed:
            keep = sorted(sorted(keep, key=lambda t: (self._freq[t[0]], t[0]))[: self.max_changed])
        rec = {**base, "d": [[addr_of(o), b, a] for o, b, a in keep]}
        if n > len(keep):
            rec["n"] = n
        self._f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.records += 1
        if self.records % 25 == 0:
            self.flush()

    def flush(self) -> None:
        self._f.flush(); self._trace.flush()

    def close(self) -> None:
        self.stop()
        for f in (self._f, self._trace):
            try:
                f.close()
            except Exception:
                pass


def start_ram_diff(ctx: Any, emu: Any, run_dir: Path, state: str | None, rom: str) -> RamDiffer | None:
    """Wire a RamDiffer into ``ctx``: call right after the start state is loaded, before the first press.
    Never raises: on any failure the agent simply runs without recording (returns None)."""
    try:
        rd = RamDiffer(Path(run_dir) / "ram_events.jsonl")
        sha = ""
        if state and Path(state).is_file():       # keep a private copy: goal checkpoints overwrite runs/checkpoints/*.state
            shutil.copyfile(state, Path(run_dir) / START_COPY)
            sha = hashlib.sha1(Path(state).read_bytes()).hexdigest()
        rd.attach(emu, {"start": Path(state).stem if state else "baseline", "state_sha1": sha, "lead_ticks": 30,
                        "rom": Path(rom).name})
        ctx.ram_diff = rd
        return rd
    except Exception:
        ctx.ram_diff = None
        return None


def add_cli_flag(ap: Any) -> None:
    ap.add_argument("--ram-diff", action="store_true", help="record event RAM diffs for tools/ram_discover.py")
