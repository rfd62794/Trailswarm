"""Curriculum slot scheduler for tools/swarm.py --continuous --plan curriculum.

Every refill the Supervisor asks ``Curriculum.next_job(n)`` what the free slot should run:
  1. a pending CONFIRM replay (a new best is only accepted once it re-solves from the same start, seed and memory);
  2. otherwise a segment chosen by NEED, by the named shares below (renormalised over the groups that have
     a candidate): UNSOLVED (weakest first), FRONTIER (the segment after the furthest checkpoint), POLISH (solved
     segments, slowest expected time first, run as explorers to look for tiny optimisations).
Each job starts from the PREVIOUS segment's best checkpoint (daisy chain), stops at its own end, and gets its own
step budget instead of one huge run.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import time
from pathlib import Path
from typing import Callable

import seg_ingest
import seg_janitor
import seg_split
import seg_store as ss

SHARE_UNSOLVED = 0.70
SHARE_FRONTIER = 0.20
SHARE_POLISH = 0.10
SHARES = {"unsolved": SHARE_UNSOLVED, "frontier": SHARE_FRONTIER, "polish": SHARE_POLISH}
WEAKEST_CYCLE = (0, 0, 0, 1, 1, 2)   # of the three weakest: the weakest 3 of 6 slots, the next 2, the third 1
BUDGET_MULT, BUDGET_MIN, BUDGET_MAX, BUDGET_DEFAULT = 3, 1500, 6000, 3000
POLISH_EXPLORE_RATE = 0.5
CONFIRM_TRIES = 2


def budget(st: dict) -> int:
    b = ss.accepted(st)
    return BUDGET_DEFAULT if not b else max(BUDGET_MIN, min(BUDGET_MAX, BUDGET_MULT * b["steps"]))


class Curriculum:
    def __init__(self, root: Path, clock: Callable[[], float] = time.time, log: Callable[[str], None] = print,
                 quiet_s: float = 30.0):
        self.root, self.clock, self.log, self.quiet_s = Path(root), clock, log, quiet_s
        self.doc = ss.load(self.root)
        self.picked = {k: 0 for k in SHARES}
        self.confirming: set[str] = set()
        self.session = int(clock())
        self._depth = 0
        with self.txn():
            seg_janitor.sweep(self.root, self.doc, clock(), log=log)

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
            for g in seg_split.maybe_split(self.doc):
                self.log(f"curriculum: split {g} at maps {[hex(m) for m in self.doc['splits'][g]]}")

    def groups(self) -> dict[str, list]:
        segs = [s for s in ss.layout(self.doc) if ss.ckpt(self.root, s.start)]
        st = lambda s: ss.stat(self.doc, s.key)  # noqa: E731
        unsolved = sorted((s for s in segs if not ss.is_solved(st(s))),
                          key=lambda s: (ss.rate(st(s)) or 0.0, st(s)["n"]))
        per = ss.fps(self.doc)
        polish = sorted((s for s in segs if ss.is_solved(st(s))), key=lambda s: -ss.potential_gain(st(s), per))  # most to win first
        all_ = ss.layout(self.doc)
        ends = [i for i, s in enumerate(all_) if ss.ckpt(self.root, s.end)]
        nxt = all_[ends[-1] + 1] if ends and ends[-1] + 1 < len(all_) else None
        frontier = [nxt] if nxt is not None and ss.ckpt(self.root, nxt.start) else []
        return {"unsolved": unsolved, "frontier": frontier, "polish": polish}

    def choose(self) -> tuple[str, object] | None:
        g = self.groups()
        avail = {k: v for k, v in g.items() if v}
        if not avail:
            return None
        norm = sum(SHARES[k] for k in avail)
        total = sum(self.picked.values())
        cat = max(avail, key=lambda k: (SHARES[k] / norm * (total + 1) - self.picked[k], SHARES[k]))
        cands = avail[cat]
        if cat == "unsolved":
            i = min(WEAKEST_CYCLE[self.picked[cat] % len(WEAKEST_CYCLE)], len(cands) - 1)
        elif cat == "polish":
            i = self.picked[cat] % min(3, len(cands))
        else:
            i = 0
        self.picked[cat] += 1
        return cat, cands[i]

    # --- jobs --------------------------------------------------------------------------------------------
    def _job(self, seg, kind: str, n: int, start: Path, st: dict) -> dict:
        tag = f"seg:{seg.key}:{self.session}-{n}"
        stop = ["--stop-at-goal", seg.stop_goal] if seg.stop_goal else ["--stop-at-map", str(seg.stop_map)]
        job = {"key": seg.key, "kind": kind, "start": str(start), "stop": stop, "steps": budget(st), "tag": tag,
               "seed": self.session % 100000 + n}
        if kind == "polish":
            job["explore_rate"] = POLISH_EXPLORE_RATE
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
        for seg in ss.layout(self.doc):
            st = ss.stat(self.doc, seg.key)
            b = st["best"]
            if (b and not b["confirmed"] and not b["rejected"] and ss.replayable(b)
                    and b["tries"] < CONFIRM_TRIES and seg.key not in self.confirming):
                return seg, st
        return None

    def next_job(self, n: int) -> dict | None:
        with self.txn():
            self.refresh()
            pc = self.pending_confirm()
            if pc:
                job = self._confirm(*pc)
            else:
                pick = self.choose()
                if pick is None:
                    return None
                kind, seg = pick
                st = ss.stat(self.doc, seg.key)
                job = self._job(seg, kind, n, ss.ckpt(self.root, seg.start), st)
                st["jobs"] = st.get("jobs", 0) + 1
        self.log(f"curriculum: {job['kind']} {job['key']} from {Path(job['start']).name}, {job['steps']} steps")
        return job

    # --- Supervisor hooks (kept here so swarm_continuous.py stays small) ------------------------------------
    def configure(self, cfg: dict, n: int) -> dict:
        """Apply the next job to a slot config: its segment, step budget and (for a replay) the old seed/starter/pace."""
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
        job["start"] = str(d / src.name)
        (d / "job.json").write_text(json.dumps({"start_name": src.name, "start_sha": ss.sha256(d / src.name)}), encoding="utf-8")

    def on_finish(self, cfg: dict, rc) -> None:
        job = cfg.get("job")
        if not job:
            return
        self.confirming.discard(job["key"])
        stalled = {job["tag"]} if rc == "stalled" else set()
        self.refresh({job["tag"]}, stalled)
        st = ss.stat(self.doc, job["key"])
        self.log(f"curriculum: {job['key']} ({job['kind']}) rc={rc}: {st['solves']}/{st['n']} solved, "
                 f"best {ss.best_frames(st)} frames{' confirmed' if st['confirmed'] else ''}")
