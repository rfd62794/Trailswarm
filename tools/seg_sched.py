"""Curriculum slot scheduler for tools/swarm.py --continuous --plan curriculum.

Every refill the Supervisor asks ``Curriculum.next_job(n)`` what the free slot should run:
  1. a pending CONFIRM replay (a new best is only accepted once it re-solves from the same start, seed and memory);
  2. otherwise a segment chosen by NEED, by the named shares below (renormalised over the groups that have
     a candidate): UNSOLVED (rotated across ALL unsolved segments: fewest picks this session first, ties weakest
     first, so early goals the swarm has long passed no longer eat the budget), FRONTIER (the segment after the furthest checkpoint), POLISH (solved
     segments, slowest expected time first, run as explorers to look for tiny optimisations).
Each job starts from the PREVIOUS segment's best checkpoint (daisy chain), stops at its own end, and gets its own
step budget instead of one huge run.
A curriculum hold (runs/curriculum_hold.json, see tools/curriculum_hold.py) removes a segment from every category until it expires.
"""
from __future__ import annotations

import contextlib
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import seg_hold
import seg_ingest
import seg_janitor
import seg_sched_grades as ssg
import seg_split
import seg_store as ss
from pokeagent import checkpoint_goals as cg
from pokeagent import segment_grades as sg

SHARE_UNSOLVED = 0.40
SHARE_FRONTIER = 0.45
SHARE_POLISH = 0.15
SHARES = {"unsolved": SHARE_UNSOLVED, "frontier": SHARE_FRONTIER, "polish": SHARE_POLISH}
BUDGET_MULT, BUDGET_MIN, BUDGET_MAX, BUDGET_DEFAULT = 3, 1500, 6000, 3000
POLISH_EXPLORE_RATE = 0.5
CONFIRM_TRIES = 2

_log = logging.getLogger(__name__)
_logged: set[str] = set()   # fallback messages already warned about: a frequent caller does not spam


def _warn_once(msg: str) -> None:
    """log.warning once per distinct message; a grade fallback keeps working but is never silent."""
    if msg not in _logged:
        _logged.add(msg)
        _log.warning(msg)


def budget(st: dict) -> int:
    b = ss.accepted(st)
    return BUDGET_DEFAULT if not b else max(BUDGET_MIN, min(BUDGET_MAX, BUDGET_MULT * b["steps"]))


class Curriculum:
    def __init__(self, root: Path, clock: Callable[[], float] = time.time, log: Callable[[str], None] = print,
                 quiet_s: float = 30.0, suite=None):
        self.root, self.clock, self.log, self.quiet_s = Path(root), clock, log, quiet_s
        self.refused: set[str] = set()
        self.doc = ss.load(self.root)
        self.picked = {k: 0 for k in SHARES}
        self.tries: dict[str, int] = {}   # per-segment UNSOLVED picks this session (rotation)
        self.confirming: set[str] = set()
        self.session = int(clock())
        self._depth = 0
        self._warned = False
        self._gm: dict[str, sg.Grade] = {}   # grades from the last groups() call
        self._grids = False                  # False = not tried; None = no ROM grids
        self.holds = seg_hold.HoldFile(self.root)   # runs/curriculum_hold.json, re-read only when it changes
        self._hold_seen: dict[tuple[str, str], seg_hold.Hold] = {}   # holds already logged (once each)
        self.suite = self._resolve_suite(suite)   # None = every segment; else {key: starter|None}
        with self._guard("start-up sweep"):
            with self.txn():
                seg_janitor.sweep(self.root, self.doc, clock(), log=log)

    # --- grades & suites ------------------------------------------------------------------------------------
    def _resolve_suite(self, suite):
        """None, a suite NAME resolved through seg_suites, or a ready {key: starter} member map."""
        return ssg.resolve_suite(suite, self.doc, self.root, self._grade_map().values(), self.log)

    def _par(self, seg, st) -> float | None:
        if self._grids is False:
            try:
                from pokeagent.legs.grid import rom_grids
                self._grids = rom_grids()
            except Exception as e:  # noqa: BLE001 - rom_grids() is opaque (ROM decode): no grids means no par, never a crash
                _warn_once(f"curriculum: no ROM grids ({type(e).__name__}: {e})")
                self._grids = None
        return sg.par_for_best(self.root, st, self._grids)

    def _grade_map(self) -> dict:
        """key -> Grade; empty on any failure (grading is advisory: scheduling must not die on it)."""
        try:
            return {g.key: g for g in sg.grade_all(self.doc, self.root, self.clock(),
                                                   par_fn=self._par, hold_file=self.holds)}
        except Exception as e:  # noqa: BLE001
            if not getattr(self, "_gm_warned", False):
                self.log(f"curriculum: grading skipped ({e!r})")
                self._gm_warned = True
            return {}

    @contextlib.contextmanager
    def _guard(self, what: str):
        """The supervisor must never die on curriculum bookkeeping: a segments.json lock held too long (another supervisor)
        is logged ONCE, that bookkeeping is skipped, and the next call retries."""
        try:
            yield
            self._warned = False
        except TimeoutError as e:
            if not self._warned:
                self.log(f"curriculum: {what} skipped, will retry ({e})")
            self._warned = True

    @contextlib.contextmanager
    def txn(self):
        """Every change to segments.json is read-modify-write under ss.locked: self.doc is re-read from disk on entry, so a
        second supervisor's ingest is never overwritten. Nested use joins the outer transaction."""
        if self._depth:
            yield self.doc
            return
        with ss.locked(self.root) as doc:
            self.doc, self._depth = doc, 1
            try:
                yield doc
            finally:
                self._depth = 0

    # --- bookkeeping -------------------------------------------------------------------------------------
    def refresh(self, finished: set[str] = frozenset(), failed: set[str] = frozenset()) -> None:
        with self.txn():
            seg_ingest.ingest(self.root, self.doc, finished, self.quiet_s, failed)
            for g in seg_split.maybe_split(self.doc, root=self.root, par_fn=self._par):
                self.log(f"curriculum: split {g} at maps {[hex(m) for m in self.doc['splits'][g]]}")
            if self.doc["splits"]:
                for goal in ssg.rejoin_goals(self.doc, list(self._grade_map().values())):
                    seg_split.reset(self.doc, [goal])
                    self.log(f"curriculum: rejoined {goal} (pieces solved+optimized, probes within tolerance)")

    def _log_refusals(self, segs) -> None:
        ssg.log_refusals(self.root, segs, self.refused, self.log)

    def _live_holds(self) -> list:
        """Unexpired holds from the hold file (read at most once per call); each new hold and each
        expiry is logged once."""
        now = datetime.fromtimestamp(self.clock()).astimezone()
        return ssg.live_holds(self.holds, self._hold_seen, now, self.log)

    def groups(self, gm=None) -> dict[str, list]:
        self._log_refusals(ss.layout(self.doc))
        self._gm = self._grade_map() if gm is None else gm   # a passed map = this call's cache
        return ssg.grade_groups(self.doc, self.root, self._gm, self.suite)

    def choose(self, gm=None) -> tuple[str, object] | None:
        self._log_refusals(ss.layout(self.doc))
        self._gm = self._grade_map() if gm is None else gm
        return ssg.choose(self.doc, self.root, self._gm, self._live_holds(), self.picked, self.tries,
                          self.suite, SHARES)

    # --- jobs --------------------------------------------------------------------------------------------
    def _job(self, seg, kind: str, n: int, start: Path, st: dict) -> dict:
        tag = f"seg:{seg.key}:rejoin{self.session}-{n}" if kind == "rejoin_probe" else f"seg:{seg.key}:{self.session}-{n}"
        stop = ["--stop-at-goal", seg.stop_goal] if seg.stop_goal else ["--stop-at-map", str(seg.stop_map)]
        job = {"key": seg.key, "kind": kind, "start": str(start), "stop": stop, "steps": budget(st), "tag": tag,
               "seed": self.session % 100000 + n}
        if kind == "polish":
            job["explore_rate"] = POLISH_EXPLORE_RATE
        elif kind in ("rejoin_probe", "repro"):
            job["explore_rate"] = 0.0
        if self.suite is not None and self.suite.get(seg.key):
            job["starter"] = self.suite[seg.key]   # a suite member pins its starter (per_starter suites)
        return job

    def _confirm(self, seg, st: dict) -> dict:
        b = st["best"]
        b["tries"] += 1
        self.confirming.add(seg.key)
        stop = ["--stop-at-goal", seg.stop_goal] if seg.stop_goal else ["--stop-at-map", str(seg.stop_map)]
        return {"key": seg.key, "kind": "confirm", "start": b["start"], "stop": stop,   # the kept copy, never re-resolved
                "steps": b.get("budget") or budget(st), "tag": f"confirm:{seg.key}:{b['run']}",
                "seed": b["seed"], "starter": b["starter"], "explore_rate": b["explore_rate"],
                "box_pace": b["box_pace"], "maps_in": b["input"]}

    def pending_confirm(self):
        return ssg.pending_confirm(self.doc, self.suite, self.confirming, CONFIRM_TRIES)

    def pending_broken_replay(self):
        """A BROKEN segment whose accepted best is still replayable earns a confirm-style regression
        replay right after pending confirms; at most one per segment per BROKEN_RECHECK_HOURS."""
        return ssg.pending_broken_replay(self.doc, self._gm, self.suite, self.confirming, self.clock())

    def pending_repro(self):
        """A synthetic_only hypothesis earns an organic-reproduction job just below the
        broken-replay priority, at most once per BROKEN_RECHECK_HOURS."""
        return ssg.pending_repro(self.doc, self._gm, self.root, self.suite, self.clock())

    def next_job(self, n: int) -> dict | None:
        with self.txn():
            self.refresh()
            self._gm = self._grade_map()
            job = None
            pc = self.pending_confirm()
            if pc:
                job = self._confirm(*pc)
            else:
                bp = self.pending_broken_replay()        # regression replay, right after a pending confirm
                if bp:
                    job = self._confirm(*bp)
            if job is None:
                rp = self.pending_repro()                # organic reproduction of a synthetic-only hypothesis
                if rp:
                    seg, st = rp
                    job = self._job(seg, "repro", n, ss.ckpt(self.root, seg.start), st)
                    st["jobs"] = st.get("jobs", 0) + 1
            if job is None:
                pick = self.choose(gm=self._gm)   # this call's grades, cached (no second grade_all)
                if pick is None:
                    return None
                kind, seg = pick
                st = ss.stat(self.doc, seg.key)
                kind = "rejoin_probe" if kind == "rejoin" else kind   # share group name -> job kind
                job = self._job(seg, kind, n, ss.ckpt(self.root, seg.start), st)
                st["jobs"] = st.get("jobs", 0) + 1
                if kind in ("unsolved", "frontier") and any(sg.grade_signal(g) for g in self._gm.values()):
                    f = ssg.frontier_seg(self.doc, self.root, self.suite)
                    fh = sg.frontier_health(self._gm.get(f.key) if f else None)
                    job["explore_rate"] = sg.explore_for_health(fh)   # a sick frontier scouts, a healthy one exploits
        self.log(f"curriculum: {job['kind']} {job['key']} from {Path(job['start']).name}, {job['steps']} steps")
        return job

    # --- Supervisor hooks (kept here so swarm_continuous.py stays small) ------------------------------------
    def configure(self, cfg: dict, n: int) -> dict:
        """Apply the next job to a slot config: its segment, step budget and (for a replay) the old seed/starter/pace."""
        job = None
        with self._guard("job pick (running a plain agent this slot)"):
            job = self.next_job(n)
        if job:
            cfg.update({k: job[k] for k in ("seed", "starter", "box_pace", "explore_rate") if job.get(k) is not None})
            cfg.update(steps=job["steps"], segment=job["key"], job=job)
        return cfg

    def maps_source(self, cfg: dict, shared: Path) -> Path:
        """A confirm replay starts from its ORIGINAL map memory; everything else from the freshest shared one."""
        job = cfg.get("job") or {}
        return Path(job["maps_in"]) if job.get("maps_in") else shared

    def adopted(self, cfg: dict) -> None:
        """A handed-over agent keeps running its job: a replay in flight must not be issued a second time."""
        job = cfg.get("job")
        if job and job.get("kind") == "confirm":
            self.confirming.add(job["key"])

    def on_start(self, cfg: dict) -> None:
        """Keep what a replay of this job's solve needs: its starting memory and the EXACT start-state file (the run is
        launched from that copy, so path + sha256 on record are what it really used)."""
        job = cfg.get("job")
        if not job:
            return
        if not Path(job["start"]).is_file():
            raise FileNotFoundError(f"curriculum job {job['tag']}: start state {job['start']} does not exist")
        if job["kind"] == "confirm":
            return
        d = ss.job_dir(self.root, job["tag"])
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(cfg["own"], ss.input_path(self.root, job["tag"]))
        src = Path(job["start"])
        shutil.copy(src, d / src.name)
        cg.copy_sidecar(src, d / src.name)   # the fingerprint travels with the copy (the synthetic gate reads it)
        job["start"] = str(d / src.name)
        (d / "job.json").write_text(json.dumps({"start_name": src.name, "start_sha": ss.sha256(d / src.name)}), encoding="utf-8")

    def on_finish(self, cfg: dict, rc) -> None:
        job = cfg.get("job")
        if not job:
            return
        self.confirming.discard(job["key"])
        stalled = {job["tag"]} if rc == "stalled" else set()
        with self._guard("ingest of a finished job"):   # not lost: the run is picked up by a later refresh
            self.refresh({job["tag"]}, stalled)
            st = ss.stat(self.doc, job["key"])
            self.log(f"curriculum: {job['key']} ({job['kind']}) rc={rc}: {st['solves']}/{st['n']} solved, "
                     f"best {ss.best_frames(st)} frames{' confirmed' if st['confirmed'] else ''}")
