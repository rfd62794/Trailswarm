"""Self-refilling swarm: keep N headless agents running; when one exits, merge ITS memory, then start a replacement.

    uv run python tools/swarm.py --continuous --agents 4 --steps 400 [--duration 6] [--stop-now]

Stop with Ctrl+C or by creating runs/swarm.stop: running agents finish (or are killed with --stop-now), their
memories are merged, nothing new starts. A second Ctrl+C kills what is left. A slot whose agent exits non-zero
within FAST_S seconds twice in a row pauses refilling for PAUSE_S and says why (no respawn storm).
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

STARTERS = ["bulbasaur", "charmander", "squirtle"]
BOX_PACES = [8, 16, 30]
FAST_S = 60.0
PAUSE_S = 300.0
POLL_S = 1.0


@dataclass
class Slot:
    idx: int
    role: str
    handle: Any = None
    cfg: dict = field(default_factory=dict)
    started: float = 0.0
    streak: int = 0           # consecutive fast non-zero exits
    paused_until: float = 0.0


class Supervisor:
    def __init__(self, root: Path, shared: Path, n: int, launch: Callable[[dict], Any], merge: Callable[[Path, Path], Any],
                 limit: Callable[[], int], steps: int = 400, starter: str | None = None, roles: list[str] | None = None,
                 segment: Callable[[int], str | None] | None = None, stop_file: Path | None = None,
                 deadline: float | None = None, stop_now: bool = False, firsts: Callable[[], dict] | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = lambda m: print(m, flush=True), fast_s: float = FAST_S, pause_s: float = PAUSE_S):
        self.root, self.shared, self.launch, self.merge, self.limit = Path(root), Path(shared), launch, merge, limit
        self.steps, self.starter, self.segment, self.stop_now = steps, starter, segment, stop_now
        self.stop_file = Path(stop_file) if stop_file else self.root / "runs" / "swarm.stop"
        self.deadline, self.firsts, self.clock, self.sleep, self.log = deadline, firsts, clock, sleep, log
        self.fast_s, self.pause_s = fast_s, pause_s
        roles = roles or ["exploiter", "explorer"]
        self.slots = [Slot(i, roles[i % len(roles)]) for i in range(n)]
        self.seq = self.finished = self.merged = 0
        self.stopping = False
        self.swarm_dir = self.root / "runs" / "swarm"

    # --- bookkeeping -------------------------------------------------------------------------------------
    def running(self) -> int:
        return sum(1 for s in self.slots if s.handle is not None)

    def status(self) -> str:
        return f"{self.running()}/{len(self.slots)} running, {self.finished} finished, {self.merged} merged"

    def _firsts(self) -> str:
        try:
            f = self.firsts() if self.firsts else {}
        except Exception:
            f = {}
        return f"; goal firsts {f}" if f else ""

    # --- launching ---------------------------------------------------------------------------------------
    def _config(self, slot: Slot) -> dict:
        n = self.seq
        self.seq += 1
        return {"slot": slot.idx, "seq": n, "seed": 1000 + n, "role": slot.role, "box_pace": BOX_PACES[n % 3],
                "starter": self.starter or STARTERS[n % 3], "steps": self.steps,
                "segment": self.segment(n) if self.segment else None,
                "own": self.swarm_dir / f"agent{slot.idx}-{n}.json"}

    def _start(self, slot: Slot) -> None:
        cfg = self._config(slot)
        self.swarm_dir.mkdir(parents=True, exist_ok=True)
        if self.shared.exists():
            shutil.copy(self.shared, cfg["own"])  # the freshest merged memory: learning compounds
        slot.cfg, slot.started = cfg, self.clock()
        slot.handle = self.launch(cfg)
        seg = f", segment {cfg['segment']}" if cfg["segment"] else ""
        self.log(f"slot {slot.idx} refilled: seed {cfg['seed']}, starter {cfg['starter']}, {cfg['role']}{seg}; {self.status()}")

    def _refill(self) -> None:
        if self.stopping:
            return
        now = self.clock()
        for s in self.slots:
            if s.handle is not None or now < s.paused_until:
                continue
            if self.running() >= min(len(self.slots), self.limit()):
                return  # cap / headroom: never exceed it
            if s.streak >= 2:
                s.streak = 0  # pause served: allow a fresh try
            self._start(s)

    # --- finishing ---------------------------------------------------------------------------------------
    def _finish(self, slot: Slot, rc: Any) -> None:
        ran = self.clock() - slot.started
        cfg, slot.handle = slot.cfg, None
        self.finished += 1
        try:
            if not cfg["own"].exists():
                raise FileNotFoundError("no memory file")
            self.merge(self.shared, cfg["own"])
            self.merged += 1
            note = "merged"
        except Exception as e:  # a crashed agent may leave nothing or a torn file; the swarm carries on
            note = f"not merged ({e!r})"
        cfg["own"].unlink(missing_ok=True)  # merged (or unusable); never merged twice
        self.log(f"slot {slot.idx} finished rc={rc} after {ran:.0f}s, {note}; {self.status()}{self._firsts()}")
        if rc != 0 and ran < self.fast_s and not self.stopping:
            slot.streak += 1
            if slot.streak >= 2:
                slot.paused_until = self.clock() + self.pause_s
                self.log(f"slot {slot.idx} paused {self.pause_s:.0f}s: {slot.streak} fast failures in a row "
                         f"(rc={rc}, <{self.fast_s:.0f}s each, role {slot.role}); see runs/swarm/agent{slot.idx}.log")
        else:
            slot.streak = 0

    def tick(self) -> None:
        for s in self.slots:
            if s.handle is None:
                continue
            rc = s.handle.poll()
            if rc is None and self.clock() - s.started > max(240, self.steps * 1.2):
                s.handle.kill()
                rc = "killed (timeout)"
            if rc is not None:
                self._finish(s, rc)
        if not self.stopping:
            if self.stop_file.exists():
                self.request_stop("stop file")
            elif self.deadline is not None and self.clock() >= self.deadline:
                self.request_stop("duration reached")
        self._refill()

    def kill_all(self) -> None:
        for s in self.slots:
            if s.handle is not None and s.handle.poll() is None:
                s.handle.kill()

    def request_stop(self, why: str) -> None:
        if not self.stopping:
            self.stopping = True
            self.log(f"stopping ({why}): {self.running()} running agents will "
                     f"{'be killed now' if self.stop_now else 'finish first'}")
        if self.stop_now:
            self.kill_all()

    def run(self) -> None:
        self.stop_file.unlink(missing_ok=True)  # a stale stop file from last time must not stop this swarm
        interrupted = False
        try:
            while True:
                try:
                    self.tick()
                    if self.stopping and self.running() == 0:
                        break
                    self.sleep(POLL_S)
                except KeyboardInterrupt:
                    if interrupted:
                        self.kill_all()
                        self.tick()
                        break
                    interrupted = True
                    self.request_stop("Ctrl+C; press again to kill")
        finally:
            self.kill_all()  # never leave agents holding ports
            for s in self.slots:
                if s.handle is not None:
                    self._finish(s, "killed")
            self.stop_file.unlink(missing_ok=True)
        self.log(f"swarm done: {self.status()}")


def goal_firsts(root: Path) -> dict:
    hist = json.loads((Path(root) / "runs" / "milestones.json").read_text())
    return {g: min(e["step"] for e in v) for g, v in hist.items()}
