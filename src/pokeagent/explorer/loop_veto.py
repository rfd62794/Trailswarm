"""loop_veto: the engine seam for the loop memory (see loop_memory.py for the mechanism).

Called from Engine.step right after ``choose`` and BEFORE the retalk and toss vetoes: when the in-run
ledger (or an ACTIVE shared-memory entry) says this (situation, button) is already dead, the selector is
asked again with the vetoed behaviour skipped, up to MAX_RECHOOSE times. Every re-choose is checked against
the same veto; if all alternatives are dead too, the original press goes through ('veto_exhausted' - the
veto must never deadlock; the existing guards still own escalation).

``record`` (called after the press, once the progress signal is known) counts the fruitless repeats and
resolves a shared-entry probe: a probe press let through to test whether a dead action came back to life -
progress clears the entry, fruitlessness just confirms it.

``fold`` (every PROMOTE_FLUSH_STEPS and at run end) writes this run's veto keys into ``mem.data["loops"]``
so the NEXT agent skips them on sight. ``finish`` does that at shutdown plus the 'ledger' summary row.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.explorer.loop_memory import (
    LOOP_NO_PROGRESS_N, LOOP_VETO_STEPS, MAX_RECHOOSE, NEVER_VETO, PROBE_EVERY, PROMOTE_FLUSH_STEPS,
    LoopLedger, Situation, active, clean_table, fold_shared, shared_key, situation_of,
)


def _site(sit: Situation) -> dict:
    return {"map": sit.map, "x": sit.x, "y": sit.y, "facing": sit.facing, "text": sit.text, "battle": sit.battle}


class Loops:
    def __init__(self) -> None:
        self.ledger = LoopLedger()
        self.sit: Situation | None = None      # situation the press in flight was taken in
        self.probe_key: str | None = None      # shared entry the in-flight press is probing
        self.probes: dict[str, int] = {}       # shared key -> ctx.step of its last probe
        self.promoted: set[str] = set()        # shared keys already announced with a 'promote' row
        self._fh = None
        self._failed = False

    def row(self, ctx, row: dict) -> None:
        """One line in <run_dir>/loops.jsonl. A write failure is logged once and never stops a run."""
        if self._failed:
            return
        try:
            if self._fh is None:
                self._fh = Path(ctx.run_dir / "loops.jsonl").open("a", encoding="utf-8")
            self._fh.write(json.dumps(row) + "\n")
            self._fh.flush()
        except OSError as exc:
            self._failed = True
            ctx.log(f"[loops log off: {exc!r}]", "res")

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def of(ctx) -> Loops:
    if ctx.loops is None:
        ctx.loops = Loops()
    return ctx.loops


def _shared_entry(ctx, sit: Situation, button: str) -> dict | None:
    return clean_table(ctx.mem.data.get("loops")).get(shared_key(sit.map, sit.x, sit.y, button))


def _vetoed(loops: Loops, ctx, sit: Situation, button: str) -> bool:
    """Dead by the run's ledger OR by an active shared entry (candidate re-chooses never probe)."""
    if loops.ledger.vetoed(sit, button, ctx.step):
        return True
    entry = _shared_entry(ctx, sit, button)
    return entry is not None and active(entry, time.time())


def check(ctx, selector, decision):
    """The veto seam. Returns the decision to press: the original, or a re-chosen alternative."""
    loops = of(ctx)
    sit = situation_of(ctx)
    loops.sit = sit
    if not decision.button or decision.behaviour in NEVER_VETO or sit.battle:
        return decision
    source = None
    if loops.ledger.vetoed(sit, decision.button, ctx.step):
        source = "run"
    else:
        key = shared_key(sit.map, sit.x, sit.y, decision.button)
        entry = _shared_entry(ctx, sit, decision.button)
        if entry is not None and active(entry, time.time()):
            if ctx.step - loops.probes.get(key, -PROBE_EVERY) >= PROBE_EVERY:
                loops.probes[key] = ctx.step  # one probe per key per window lets the press through
                loops.probe_key = key
                return decision
            source = "shared"
            if key not in loops.promoted:
                loops.promoted.add(key)
                loops.row(ctx, {"step": ctx.step, "kind": "promote", "key": key, **_site(sit),
                                "button": decision.button, "rule": decision.rule, "behaviour": decision.behaviour,
                                "source": "shared"})
    if source is None:
        return decision
    no_prog = loops.ledger.count(sit, decision.button) or LOOP_NO_PROGRESS_N
    until = loops.ledger.veto_until(sit, decision.button) or ctx.step + LOOP_VETO_STEPS
    skip, chosen = {decision.behaviour}, None
    for _ in range(MAX_RECHOOSE):
        cand = selector.choose(ctx, skip=frozenset(skip))
        if cand is None:
            break
        if cand.button and cand.behaviour not in NEVER_VETO and _vetoed(loops, ctx, sit, cand.button):
            skip.add(cand.behaviour)  # the alternative is dead too: keep asking
            continue
        chosen = cand
        break
    row = {"step": ctx.step, **_site(sit), "button": decision.button, "rule": decision.rule,
           "behaviour": decision.behaviour, "no_progress": no_prog, "veto_until": until, "source": source}
    if chosen is None:
        loops.row(ctx, {**row, "kind": "veto_exhausted"})
        ctx.log(f"[loop_veto: {decision.button} at map {sit.map} ({sit.x},{sit.y}) facing {sit.facing}, same screen, "
                f"no progress x{no_prog} -> vetoed but every alternative is dead too: pressing it]", "res")
        return decision
    loops.row(ctx, {**row, "kind": "veto"})
    ctx.log(f"[loop_veto: {decision.button} at map {sit.map} ({sit.x},{sit.y}) facing {sit.facing}, same screen, "
            f"no progress x{no_prog} -> vetoed for {LOOP_VETO_STEPS} steps; rule {decision.rule} proposed it; "
            f"chose {chosen.button} by {chosen.behaviour}]", "res")
    return chosen


def record(ctx, decision, reasons: list[str]) -> None:
    """After the press: resolve a probe, count the fruitless repeat, periodically fold into shared memory."""
    loops = of(ctx)
    progressed = bool(reasons)
    sit, loops.sit = loops.sit, None
    if loops.probe_key is not None:
        key, loops.probe_key = loops.probe_key, None
        entry = clean_table(ctx.mem.data.get("loops")).get(key)
        if progressed and entry is not None:
            entry["clear"] = time.time()  # the dead action is alive again
        loops.row(ctx, {"step": ctx.step, "kind": "probe", "key": key, "ok": progressed,
                        **(_site(sit) if sit is not None else {}), "button": decision.button, "rule": decision.rule,
                        "behaviour": decision.behaviour, "source": "shared"})
    if sit is not None and decision.behaviour not in NEVER_VETO and not sit.battle:
        loops.ledger.record(sit, decision.button, progressed, ctx.step)
    if ctx.step % PROMOTE_FLUSH_STEPS == 0:
        fold(ctx, loops)


def fold(ctx, loops: Loops | None = None) -> None:
    """Write this run's veto keys into the shared 'loops' table; stale entries expire with a row each."""
    loops = loops or of(ctx)
    for key in fold_shared(ctx.mem.data, loops.ledger.veto_keys(), ctx.run_dir.name, time.time()):
        loops.row(ctx, {"step": ctx.step, "kind": "expire", "key": key, "source": "shared"})


def finish(ctx) -> None:
    """Run end: the final fold, the 'ledger' summary row, then close the file."""
    loops = of(ctx)
    fold(ctx, loops)
    loops.row(ctx, {"kind": "ledger", "top": loops.ledger.top()})
    loops.close()
