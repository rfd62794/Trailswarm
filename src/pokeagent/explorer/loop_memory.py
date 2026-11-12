"""Loop memory: an in-run ledger of (situation, action) -> fruitless repeats, plus the shared "loops" table.

One mechanism for every loop kind: NPC bumping (same tile, same direction, blocked, no text), repeated dialog
(same text, A again), a repeated menu path (the screen returns to itself) and a repeated blocked walk are all
``(Situation, button)`` repeats with no progress. The ledger vetoes the action after LOOP_NO_PROGRESS_N
consecutive fruitless repeats; the veto holds LOOP_VETO_STEPS, then one retry is allowed.

The on-screen text is part of the situation on purpose: a box still printing, or a dialog that advances page
by page, shows DIFFERENT text every press, so it is a different situation and never a loop. Only the SAME
text (a restarting dialog, a menu that returns to itself, a wall that prints nothing) can repeat a situation.

The shared table (``mem.data["loops"]``) carries recurrence candidates across runs: a veto here is keyed
``"{map},{x},{y},{button}"`` (no text or facing: a new agent should skip a dead action on sight at that tile).
It activates only after LOOP_PROMOTE_RUNS distinct runs saw it, decays after LOOP_TTL_DAYS, and is probed
rather than believed forever (loop_veto owns the probe rhythm). All shared state is DATA: malformed entries
are ignored, never trusted and never raised over.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

# --- the in-run veto (all untuned first values) ---
LOOP_NO_PROGRESS_N = 3         # the same (situation, action) with no progress this many times -> veto
LOOP_VETO_STEPS = 60           # how long the veto holds in that situation (steps); then the action is allowed once more
MAX_RECHOOSE = 3               # times the engine asks the selector for another behaviour before giving up on the veto
LEDGER_MAX = 2000              # situations kept in the in-run ledger (oldest dropped)
ENTRY_IDLE_DROP = LOOP_VETO_STEPS * 4  # an entry with no new press this long is forgotten (bounded memory)
# behaviours whose repeated presses are legitimate (battle menus, party management, waiting out a busy screen)
NEVER_VETO = frozenset({"battle", "battle_moves", "battle_text_wait", "catch", "switch_out", "party_order", "settle_wait"})

# --- cross-run persistence (all untuned first values) ---
PROMOTE_FLUSH_STEPS = 500      # steps between folds of this run's veto keys into the shared memory (and at run end)
LOOP_RUNS_KEPT = 10            # run ids kept per shared entry (newest last)
LOOP_PROMOTE_RUNS = 3          # distinct runs that must report a dead action before it vetoes on sight (K)
LOOP_TTL_DAYS = 7              # a shared entry this old is dropped: a fixed bug must not stay vetoed
PROBE_EVERY = 200              # steps between probes of an active shared entry (one probe per key per window)


@dataclass(frozen=True)
class Situation:
    """Where an action was tried. ``text`` = stable hash of the normalised on-screen lines; ``battle`` keeps
    battle presses out of the loop memory entirely (battle loops belong to the battle code)."""
    map: int
    x: int
    y: int
    facing: str
    text: int
    battle: bool


def text_hash(lines: list[str]) -> int:
    """Normalise (lower, collapse whitespace), join with "|", hash with hashlib and truncate to 8 bytes.
    sha256, not Python's salted hash(): the value must be identical across runs and processes."""
    norm = "|".join(" ".join(line.lower().split()) for line in lines)
    return int.from_bytes(hashlib.sha256(norm.encode("utf-8")).digest()[:8], "big")


def situation_of(ctx) -> Situation:
    v = ctx.view
    return Situation(v.m, v.x, v.y, ctx.facing, text_hash(v.lines), v.battling)


@dataclass
class LoopEvent:
    """Returned by LoopLedger.record the moment a (situation, action) crosses LOOP_NO_PROGRESS_N."""
    sit: Situation
    button: str
    no_progress: int
    veto_until: int


@dataclass
class _Entry:
    count: int = 0          # consecutive fruitless repeats
    veto_until: int = 0     # vetoed while step < this
    last: int = 0           # step of the last press recorded here
    vetoes: int = 0         # veto events produced this run (promotion and the ledger row count these)


class LoopLedger:
    """(Situation, button) -> consecutive fruitless presses. A progress press clears that entry."""

    def __init__(self) -> None:
        self.e: dict[tuple[Situation, str], _Entry] = {}

    def record(self, sit: Situation, action: str, progressed: bool, step: int) -> LoopEvent | None:
        self._prune(step)
        e = self.e.get((sit, action))
        if progressed:
            if e is not None:  # the action turned out useful: the streak and any veto are cleared
                e.count, e.veto_until, e.last = 0, 0, step
            return None
        if e is None:
            if len(self.e) >= LEDGER_MAX:
                oldest = min(self.e, key=lambda k: self.e[k].last)
                del self.e[oldest]
            e = self.e[(sit, action)] = _Entry()
        e.count += 1
        e.last = step
        if e.count >= LOOP_NO_PROGRESS_N and step >= e.veto_until:
            e.veto_until = step + LOOP_VETO_STEPS
            e.vetoes += 1
            return LoopEvent(sit, action, e.count, e.veto_until)
        return None

    def vetoed(self, sit: Situation, action: str, step: int) -> bool:
        e = self.e.get((sit, action))
        return e is not None and step < e.veto_until

    def count(self, sit: Situation, action: str) -> int:
        e = self.e.get((sit, action))
        return e.count if e is not None else 0

    def veto_until(self, sit: Situation, action: str) -> int:
        e = self.e.get((sit, action))
        return e.veto_until if e is not None else 0

    def veto_keys(self) -> list[str]:
        """Shared-table keys (``"{map},{x},{y},{button}"``) for every entry that produced a veto this run."""
        return [shared_key(sit.map, sit.x, sit.y, action) for (sit, action), e in self.e.items() if e.vetoes > 0]

    def top(self, n: int = 5) -> list[dict]:
        """The n most-vetoed entries (for the shutdown 'ledger' row in loops.jsonl)."""
        rows = [(e, sit, action) for (sit, action), e in self.e.items() if e.vetoes > 0]  # _Entry has no order
        rows.sort(key=lambda t: (-t[0].vetoes, -t[0].last))
        return [{"map": sit.map, "x": sit.x, "y": sit.y, "facing": sit.facing, "text": sit.text, "battle": sit.battle,
                 "button": action, "vetoes": e.vetoes, "no_progress": e.count, "veto_until": e.veto_until}
                for e, sit, action in rows[:n]]

    def _prune(self, step: int) -> None:
        for k, e in list(self.e.items()):
            if step - e.last > ENTRY_IDLE_DROP:
                del self.e[k]


# --- the shared "loops" table (mem.data["loops"]): key -> {"runs": [...], "last": epoch, "clear": epoch|0} ---

def shared_key(map_id: int, x: int, y: int, button: str) -> str:
    """A dead action by tile and button only: a new agent should skip it on sight, whatever the screen says."""
    return f"{map_id},{x},{y},{button}"


def valid_entry(e) -> bool:
    """Shared memory is data, not instructions: only this exact shape is read or applied."""
    return (isinstance(e, dict) and isinstance(e.get("runs"), list) and all(isinstance(r, str) for r in e["runs"])
            and isinstance(e.get("last"), (int, float)) and not isinstance(e.get("last"), bool)
            and isinstance(e.get("clear"), (int, float)) and not isinstance(e.get("clear"), bool))


def clean_table(loops) -> dict:
    """The valid entries of a raw ``data["loops"]`` value ({} for anything malformed). References, not copies:
    a successful probe mutates ``clear`` in place."""
    return {k: v for k, v in loops.items() if valid_entry(v)} if isinstance(loops, dict) else {}


def active(e: dict, now: float) -> bool:
    """An entry is applied to new runs only after K distinct runs reported it, while it is not cleared and
    not stale. ``last > clear``: a successful probe revives the action until someone fails it again."""
    return (len(e["runs"]) >= LOOP_PROMOTE_RUNS and e["last"] > e["clear"]
            and now - e["last"] < LOOP_TTL_DAYS * 86400)


def fold_shared(data: dict, keys: list[str], run_id: str, now: float) -> list[str]:
    """Fold this run's veto keys into ``data["loops"]`` (each run id recorded once, ``last`` refreshed) and
    drop stale/malformed entries. Returns the dropped keys so the caller can log 'expire' rows."""
    loops = data.get("loops")
    if not isinstance(loops, dict):
        loops = data["loops"] = {}
    for key in keys:
        e = loops.get(key)
        if not valid_entry(e):
            e = loops[key] = {"runs": [], "last": 0, "clear": 0}
        if run_id not in e["runs"]:
            e["runs"].append(run_id)
            del e["runs"][:-LOOP_RUNS_KEPT]
        e["last"] = now
    dropped = [k for k in list(loops) if not valid_entry(loops[k]) or now - loops[k]["last"] >= LOOP_TTL_DAYS * 86400]
    for k in dropped:
        del loops[k]
    return dropped
