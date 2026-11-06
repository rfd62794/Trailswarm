"""Deterministic headless replay of a recorded run: the press trace (ram_trace.jsonl) is a frame-exact script.

``pre_states`` walks a run once and saves the emulator state just before chosen presses; ``branches`` then
re-runs one press from such a state twice: WITH the press (the event) and WITHOUT it (a control that only lets
time pass), sampling the watched bytes along the way. A byte is causally tied to the event when the predicted
change appears with the press and not without it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pokeagent.emulator import Button, PyBoyEmulator

LEAD_TICKS = 30        # tools/explore_demo.py and ramlab.headless tick this many frames after loading the start state
SAMPLE_EVERY = 8


class Unreplayable(Exception):
    pass


def load_trace(run_dir: Path) -> tuple[dict, list[tuple[int, str, int, int]]]:
    path = Path(run_dir) / "ram_trace.jsonl"
    if not path.is_file():
        raise Unreplayable(f"{run_dir}: no ram_trace.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])
    presses = []
    for ln in lines[1:]:
        try:
            f, b, hold, settle = json.loads(ln)
        except ValueError:
            continue
        presses.append((f, b, hold, settle))
    return meta, presses


def start_state(meta: dict, states: Path, run_dir: Path | None = None) -> Path:
    own = Path(run_dir) / "ram_start.state" if run_dir else None
    if own is not None and own.is_file():          # the run kept its own copy of the start state
        return own
    p = Path(states) / f"{meta.get('start', '')}.state"
    if not p.is_file():
        raise Unreplayable(f"start state {p.name} not found")
    sha = meta.get("state_sha1")
    if sha and hashlib.sha1(p.read_bytes()).hexdigest() != sha:
        raise Unreplayable(f"start state {p.name} changed since the run (sha mismatch)")
    return p


class Replayer:
    def __init__(self, rom: Path, states: Path, tmp: Path) -> None:
        self.emu = PyBoyEmulator(Path(rom), headless=True)
        self.states, self.tmp = Path(states), Path(tmp)
        self.tmp.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.emu.close()

    def pre_states(self, run_dir: Path, steps: list[int]) -> dict[int, Path]:
        """Save the state just before press ``step`` (1-based, = ctx.step) for each wanted step, in one pass."""
        meta, presses = load_trace(run_dir)
        emu = self.emu
        emu.tick(60); emu.load_state(start_state(meta, self.states, run_dir)); emu.tick(meta.get("lead_ticks", LEAD_TICKS))
        base, wanted, out = emu.frames, set(steps), {}
        for i, (f, btn, hold, settle) in enumerate(presses):
            if f > emu.frames - base:
                emu.tick(f - (emu.frames - base))
            if i + 1 in wanted:
                out[i + 1] = self.tmp / f"{Path(run_dir).name}_{i + 1}.state"
                emu.save_state(out[i + 1])
                if len(out) == len(wanted):
                    break
            emu.press(Button(btn), hold, settle)
        return out

    def branches(self, pre: Path, press: tuple, gap: int, addrs: list[int]) -> tuple[dict, dict]:
        """({addr: [pre, samples...]} with the press, {addr: [pre, samples...]} control without it)."""
        f, btn, hold, settle = press
        emu = self.emu
        emu.load_state(pre)
        ev = {a: [emu.read(a)] for a in addrs}
        emu.press(Button(btn), hold, settle)
        left = gap - settle
        self._sample(ev, addrs)
        while left > 0:
            step = min(SAMPLE_EVERY, left)
            emu.tick(step); left -= step
            self._sample(ev, addrs)
        emu.load_state(pre)
        ct = {a: [emu.read(a)] for a in addrs}
        left = gap
        while left > 0:
            step = min(SAMPLE_EVERY, left)
            emu.tick(step); left -= step
            self._sample(ct, addrs)
        return ev, ct

    def _sample(self, series: dict, addrs: list[int]) -> None:
        for a in addrs:
            series[a].append(self.emu.read(a))
