"""Self-refilling swarm: keep N headless agents running; when one exits, merge ITS memory, then start a replacement.

    uv run python tools/swarm.py --continuous --agents 4 --steps 400 [--duration 6] [--stop-now]

Stop with Ctrl+C or by creating runs/swarm.stop: running agents finish (or are killed with --stop-now), their
memories are merged, nothing new starts. A second Ctrl+C kills what is left. A slot whose agent exits non-zero
within FAST_S seconds twice in a row pauses refilling for PAUSE_S and says why (no respawn storm).

Rolling upgrade (swarm_handoff.py): `--upgrade` / `--adopt` takes over a live supervisor's agents with no drain.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import swarm_handoff  # noqa: E402
from swarm_slot import Slot  # noqa: E402

STARTERS = ["bulbasaur", "charmander", "squirtle"]
BOX_PACES = [8, 16, 30]
FAST_S = 60.0
PAUSE_S = 300.0
POLL_S = 1.0
SOLVED_FAST_S = 20.0   # a segment run this quick was already trivially solved
SOLVED_HOLD_S = 600.0  # ...so --segment auto must not pick it again for 10 minutes
MIN_S_PER_STEP = 0.05  # a clean exit faster than this per step cannot have used its step budget


class Supervisor:
    def __init__(self, root: Path, shared: Path, n: int, launch: Callable[[dict], Any], merge: Callable[[Path, Path], Any],
                 limit: Callable[[], int], steps: int = 400, starter: str | None = None, roles: list[str] | None = None,
                 segment: Callable[[int], str | None] | None = None, stop_file: Path | None = None,
                 deadline: float | None = None, stop_now: bool = False, firsts: Callable[[], dict] | None = None,
                 heartbeat: Callable[[], None] | None = None, segment_ok: Callable[[str], bool] | None = None,
                 watch: Callable[[dict], Any] | None = None, watch_s: float = 15.0,
                 on_stall: Callable[..., None] | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = lambda m: print(m, flush=True), fast_s: float = FAST_S, pause_s: float = PAUSE_S):
        self.root, self.shared, self.launch, self.merge, self.limit = Path(root), Path(shared), launch, merge, limit
        self.steps, self.starter, self.segment, self.stop_now = steps, starter, segment, stop_now
        self.stop_file = Path(stop_file) if stop_file else self.root / "runs" / "swarm.stop"
        self.deadline, self.firsts, self.clock, self.sleep, self.log = deadline, firsts, clock, sleep, log
        self.fast_s, self.pause_s = fast_s, pause_s
        self.heartbeat, self.segment_ok, self.watch_factory, self.watch_s = heartbeat, segment_ok, watch, watch_s
        self.on_stall = on_stall
        self.watchers: dict[int, Any] = {}
        self.next_watch = 0.0
        self.solved: dict[str, float] = {}
        roles = self.roles = roles or ["exploiter", "explorer"]
        self.handed_over = False
        self.handoff_file = self.root / "runs" / "swarm.handoff"
        self.ident = swarm_handoff.Ident()
        self.state, self.kill_pid = swarm_handoff.default_state()  # liveness / tree-kill of adopted agents (by pid)
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

    @staticmethod
    def _digest(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _pick_segment(self, n: int) -> str | None:
        if not self.segment:
            return None
        for k in range(3):  # the picker rotates through the weak goals; skip ones just seen to be trivial
            seg = self.segment(n + k)
            if seg is None or self.clock() - self.solved.get(seg, float("-inf")) > SOLVED_HOLD_S:
                return seg
            self.log(f"segment {seg}: solved trivially {self.clock() - self.solved[seg]:.0f}s ago, not re-picking")
        return None

    # --- launching ---------------------------------------------------------------------------------------
    def _config(self, slot: Slot) -> dict:
        n = self.seq
        self.seq += 1
        return {"slot": slot.idx, "seq": n, "seed": 1000 + n, "role": slot.role, "box_pace": BOX_PACES[n % 3],
                "starter": self.starter or STARTERS[n % 3], "steps": self.steps,
                "segment": self._pick_segment(n),
                "own": self.swarm_dir / f"agent{slot.idx}-{n}.json"}

    def _start(self, slot: Slot) -> None:
        cfg = self._config(slot)
        self.swarm_dir.mkdir(parents=True, exist_ok=True)
        if self.shared.exists():
            shutil.copy(self.shared, cfg["own"])  # the freshest merged memory: learning compounds
        cfg["hash"], cfg["started_wall"] = self._digest(cfg["own"]), time.time()
        slot.cfg, slot.started = cfg, self.clock()
        if cfg["segment"] and self.segment_ok and not self.segment_ok(cfg["segment"]):
            self.log(f"WARNING segment {cfg['segment']}: no checkpoint, running a full agent")
        try:
            slot.handle = self.launch(cfg)
            if self.watch_factory:
                self.watchers[slot.idx] = self.watch_factory(cfg)
        except Exception as e:  # no free port, Popen failure: a failed start feeds the backoff, never crashes us
            cfg["own"].unlink(missing_ok=True)
            self.log(f"slot {slot.idx} failed to start: {e!r}; {self.status()}")
            self._note_failure(slot, f"launch error {e!r}")
            return
        seg = f", segment {cfg['segment']}" if cfg["segment"] else ""
        self.log(f"slot {slot.idx} refilled: seed {cfg['seed']}, starter {cfg['starter']}, {cfg['role']}{seg}; {self.status()}")

    def _note_failure(self, slot: Slot, why: str) -> None:
        slot.streak += 1
        if slot.streak >= 2:
            slot.paused_until = self.clock() + self.pause_s
            self.log(f"slot {slot.idx} paused {self.pause_s:.0f}s: {slot.streak} fast failures in a row "
                     f"({why}, role {slot.role}); see runs/swarm/agent{slot.idx}.log")

    def _refill(self) -> None:
        if self.stopping:
            return
        now = self.clock()
        for s in self.slots:
            if s.handle is not None or s.retire or now < s.paused_until:
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
        self.watchers.pop(slot.idx, None)
        if rc == 0 and cfg["segment"] and ran < SOLVED_FAST_S:
            self.solved[cfg["segment"]] = self.clock()
            self.log(f"segment {cfg['segment']} finished in {ran:.0f}s (already solved); "
                     f"not re-picking for {SOLVED_HOLD_S:.0f}s")
        self.finished += 1
        keep = False
        try:
            if not cfg["own"].exists():
                raise FileNotFoundError("no memory file")
            if self._digest(cfg["own"]) == cfg.get("hash"):
                note = "memory untouched, skipped"  # crashed before saving: nothing to learn from
            else:
                try:
                    self.merge(self.shared, cfg["own"])
                except Exception:
                    keep = True
                    raise
                self.merged += 1
                note = "merged"
        except Exception as e:  # a crashed agent may leave nothing or a torn file; the swarm carries on
            note = f"not merged ({e!r})"
            if keep:
                note += f", kept in {self._keep(cfg['own'])} for --merge-only"
        cfg["own"].unlink(missing_ok=True)  # merged (or unusable); never merged twice
        self.log(f"slot {slot.idx} finished rc={rc} after {ran:.0f}s, {note}; {self.status()}{self._firsts()}")
        too_fast = ran < self.fast_s if rc != 0 else (not cfg["segment"] and ran < min(self.fast_s, cfg["steps"] * MIN_S_PER_STEP))
        if too_fast and not self.stopping:
            self._note_failure(slot, f"rc={rc}, {ran:.0f}s, budget {cfg['steps']} steps")
        else:
            slot.streak = 0

    def _keep(self, own: Path) -> Path:
        dest = self.swarm_dir / "unmerged"
        dest.mkdir(parents=True, exist_ok=True)
        return Path(shutil.move(str(own), str(dest / own.name)))

    def tick(self) -> None:
        if not self.stopping and self.handoff_file.exists() and swarm_handoff.hand_over(self):
            return  # a new supervisor took the agents over; they keep running
        self._watch_progress()
        if self.heartbeat:
            self.heartbeat()  # keeps runs/spawn.lock fresh: a live swarm's lock must never look 6 h old
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
        self.slots = [s for s in self.slots if not (s.retire and s.handle is None)]
        self._refill()

    def adopt(self, data: dict) -> int:
        return swarm_handoff.adopt(self, data)

    def _watch_progress(self) -> None:
        """Every watch_s: stop agents that are alive but stuck, merge what they learned; _refill replaces them."""
        if not self.watch_factory or self.clock() < self.next_watch:
            return
        self.next_watch = self.clock() + self.watch_s
        for s in self.slots:
            w = self.watchers.get(s.idx)
            if s.handle is None or w is None or s.handle.poll() is not None:
                continue
            reason = w.check()
            if reason:
                self.log(f"slot {s.idx} stalled: {reason} (last position {w.last_pos})")
                if self.on_stall:
                    self.on_stall(self.swarm_dir, s.idx, s.cfg["seed"], reason, w)
                s.handle.kill()  # the whole process tree we launched
                self._finish(s, "stalled")

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
        if not self.running():
            self.handoff_file.unlink(missing_ok=True)  # fresh start: an old unanswered request is not ours
        interrupted = False
        try:
            while True:
                try:
                    self.tick()
                    if self.handed_over:
                        return
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
            if self.handed_over:
                return  # the agents belong to the new supervisor now
            self.kill_all()  # never leave agents holding ports
            for s in self.slots:
                if s.handle is not None:
                    self._finish(s, "killed")
            self.stop_file.unlink(missing_ok=True)
        self.log(f"swarm done: {self.status()}")


def goal_firsts(root: Path) -> dict:
    hist = json.loads((Path(root) / "runs" / "milestones.json").read_text())
    return {g: min(e["step"] for e in v) for g, v in hist.items()}
