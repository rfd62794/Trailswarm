"""Leg drills: re-run ONE leg from its saved entry state until the player reaches the exit tile or leaves the map.

Spec ``<map>:<x>,<y>-><x>,<y>[:BUTTON]`` (entry -> exit). Budget = BUDGET_X * par frames, converted to steps at the measured
FRAMES_PER_STEP. Frames are scored with the same model as legs.json (split.press_frames), plus one walk for the leaving press
when the run stops on the exit tile, so a drill is comparable with a natural leg. A drill never starts from a discovery state.
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

from pokeagent.legs.grid import FRAME_WALK
from pokeagent.legs.split import press_frames

BUDGET_X = 3
FRAMES_PER_STEP = 10.5    # = tools/seg_store.FRAMES_PER_STEP (measured presses -> frames)
MIN_STEPS = 24
DRILLS_LOG = Path("runs/legs/drills.jsonl")
_SPEC = re.compile(r"^(\d+):(\d+),(\d+)->(\d+),(\d+)(?::([A-Z]+))?$")


@dataclass(frozen=True)
class DrillSpec:
    map: int
    entry: tuple
    exit: tuple
    button: str = ""

    @property
    def text(self) -> str:
        s = f"{self.map}:{self.entry[0]},{self.entry[1]}->{self.exit[0]},{self.exit[1]}"
        return s + (f":{self.button}" if self.button else "")

    @property
    def key_prefix(self) -> str:
        return f"{self.map}:{self.entry[0]},{self.entry[1]}>{self.exit[0]},{self.exit[1]}:"


def parse(s: str) -> DrillSpec:
    m = _SPEC.match(s.strip())
    if not m:
        raise ValueError(f"bad drill spec {s!r}; want <map>:<x>,<y>-><x>,<y>[:BUTTON]")
    a = [int(g) for g in m.groups()[:5]]
    return DrillSpec(a[0], (a[1], a[2]), (a[3], a[4]), m.group(6) or "")


def budget_steps(par_frames: float, mult: float = BUDGET_X, per_step: float = FRAMES_PER_STEP) -> int:
    return max(MIN_STEPS, math.ceil(mult * par_frames / per_step))


def par_frames_for(spec: DrillSpec, rom: str | Path | None = None) -> float | None:
    """Par of the leg incl. the leaving press, from the ROM grid; None when the ROM or the route is unknown."""
    from pokeagent.legs import grid as G
    from pokeagent.legs.par import map_par
    r = map_par(G.rom_grids(rom), spec.map, spec.entry, spec.exit)
    return None if r is None else r[0] + FRAME_WALK


def write_meta(run_dir: Path, update: dict) -> None:
    p = Path(run_dir) / "meta.json"
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    meta.update(update)
    p.write_text(json.dumps(meta), encoding="utf-8")


def append_log(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


class DrillMonitor:
    """Per-press hook. ``observe`` returns True once the drill ended (and has recorded drill_result)."""

    def __init__(self, spec: DrillSpec, par_frames: float, max_steps: int, run_dir: Path, log_path: Path | None = DRILLS_LOG,
                 now=time.time):
        self.spec, self.par, self.max_steps, self.run_dir, self.log_path, self.now = spec, par_frames, max_steps, Path(run_dir), log_path, now
        self.presses, self.model_frames, self.last_button, self.frames0 = 0, 0.0, "", None
        self.result: dict | None = None

    def observe(self, ctx, fr) -> bool:
        if self.result is not None:
            return True
        if self.frames0 is None:
            self.frames0 = getattr(ctx.emu, "frames", 0)
        b, a = tuple(fr.before), tuple(fr.after)
        self.presses += 1
        self.last_button = fr.name
        self.model_frames += press_frames({"from": b, "to": a, "moved": b != a})
        sp = self.spec
        if a[0] != sp.map:
            ok = b[0] == sp.map and (b[1], b[2]) == sp.exit
            return self._end(ctx, ok, "left_by_exit" if ok else "left_map")
        if (a[1], a[2]) == sp.exit and sp.exit != sp.entry:
            self.model_frames += FRAME_WALK   # the press that leaves is not made: price it as one walk, as par does
            return self._end(ctx, True, "reached_exit")
        if ctx.step >= self.max_steps:
            return self._end(ctx, False, "budget")
        return False

    def _end(self, ctx, solved: bool, reason: str) -> bool:
        frames = getattr(ctx.emu, "frames", 0) - (self.frames0 or 0)
        eff = self.par / self.model_frames if solved and self.model_frames > 0 else None
        self.result = {"source": "drill", "kind": "leg", "leg": self.spec.text, "map": self.spec.map, "entry": list(self.spec.entry),
                       "exit": list(self.spec.exit), "button": self.spec.button or (self.last_button if reason == "left_by_exit" else ""),
                       "solved": solved, "reason": reason, "steps": ctx.step, "frames": frames, "presses": self.presses,
                       "model_frames": self.model_frames, "par_frames": self.par, "efficiency": eff, "budget_steps": self.max_steps,
                       "run": self.run_dir.name, "t": self.now()}
        try:
            write_meta(self.run_dir, {"drill_result": self.result})
            self.log_path and append_log(self.log_path, self.result)
        except OSError as e:
            ctx.log(f"[drill result not written: {e!r}]", "res")
        ctx.done = True
        ctx.log(f"drill {self.spec.text}: {'SOLVED' if solved else 'failed'} ({reason}) in {ctx.step} steps", "hdr")
        return True


def fail_cost(d: dict) -> float:
    """Frames a drill counts as in legs.json: its model frames when solved, else at least the budget (3 x par)."""
    return d["model_frames"] if d.get("solved") else max(d["model_frames"], BUDGET_X * d["par_frames"])
