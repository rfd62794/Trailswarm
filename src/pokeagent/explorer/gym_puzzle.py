"""gym_puzzle: Lt. Surge's trash-can locks (Vermilion Gym, map 0x5C) - pure logic, no emulator, no atlas.

Two modes (Robert, 2026-11-16, explore BOTH in one module): SEARCH (default: the agent finds the cans
by trying them) and ORACLE (reads the game's own lock values and goes straight to them). In SEARCH the
RAM lock values may be read ONLY to log and score - a referee, never a choice (``next_can`` takes no
RAM argument); the referee judges a press already made, from the lock event byte's diff - never the
pair itself (referee_result). ORACLE reads D743/D744 and the lock byte (0xD773) live each step
(``set_locks``): D743's can while the 1st-lock bit is clear, D744's once it reads set.

Ground truth (pokered vermilion_gym_trash.asm + data/text/text_2.asm, cited by the controller round 5):
- 15 cans, id = col*3 + row with col = (x-1)/2, row = (y-7)/2; the can tile in cell_tiles is 0x1B.
- The 1st lock is one random can (D743 = Random & $0E); D744 names the 2nd once it opens and is NEVER
  cleared on a reset - a stale D744 equal to the pressed can is NOT a hit. While the 1st lock is open
  ANY press but D744's can resets (bit1 drops, D743 re-randomizes) - an armed press never answers
  "nothing", so the armed search gets exactly one guess among the 2-4 neighbours per arming.
- The can texts: "Nope, there's only trash" = nothing; "Nope! ... locks were reset!" = reset;
  "switch under the trash ... 1st electric lock opened!" = first; "2nd electric lock opened!" = second.
- Barrier cells x 4-5, y 4-5: stepping tiles read 48/17 closed, all 17 open, only after the 2nd lock.
UNVERIFIED: the lock event BYTE 0xD773's base is inferred (live read: 0x1E -> 0x1F on the 2nd-lock
press; bit0 = the 2nd lock, bit1 = the 1st).
"""
from __future__ import annotations

GYM = 0x5C
GOAL = "beat_surge"
CAN_TILE = 0x1B
BARRIER = ((4, 4), (5, 4), (4, 5), (5, 5))  # probe: the closed electric barrier's cells
BARRIER_OPEN_TILE = 17                      # closed cells read 48/17; open all 17, only post-2nd-lock
MODES = ("search", "oracle")
ENV_MODE = "POKEAGENT_GYM_PUZZLE_MODE"
LOCK_ADDRS = (0xD743, 0xD744)   # wFirstLockTrashCanIndex, wSecondLockTrashCanIndex (ram_map.json, unverified)
LOCK_FLAGS = 0xD773           # the event-flag byte with the two lock bits (UNVERIFIED base)
FLAG_2ND, FLAG_1ST = 0x01, 0x02  # bit0 = EVENT_2ND_LOCK_OPENED, bit1 = EVENT_1ST_LOCK_OPENED
GYM_CAN_ADDR = 0xCD5B           # wGymTrashCanIndex
MAX_PER_ATTEMPT = 15            # cans in one pass over the can order (there are only 15)
MAX_TOTAL = 250                 # can presses per run -> give up (round 4: near-certain, not lucky)


def resolve_mode(cli_mode: str | None, env_mode: str | None) -> str:
    """The solving mode: the CLI flag wins over the env var; anything else is a clear error."""
    mode = cli_mode or env_mode or "search"
    if mode not in MODES:
        raise ValueError(f"gym puzzle mode must be one of {MODES}, got {mode!r}")
    return mode


def can_id(cell: tuple[int, int]) -> int:
    """id = col*3 + row, col = (x-1)/2, row = (y-7)/2 (the game's own numbering, per the probe)."""
    x, y = cell
    return ((x - 1) // 2) * 3 + (y - 7) // 2


def can_cell(idx: int) -> tuple[int, int]:
    """Inverse of can_id: the (x, y) cell a lock index names."""
    return 1 + 2 * (idx // 3), 7 + 2 * (idx % 3)


def can_cells(plan, map_id: int = GYM) -> list[tuple[int, int]]:
    """The can cells, sorted (can-id order = column order), from the planner's ROM tile grid. The tile
    also marks non-can cells (e.g. (6,1) by Surge), so keep only cells that invert through can_id."""
    cells = plan.cells_with_tile(map_id, CAN_TILE) if plan is not None else ()
    return sorted((int(x), int(y)) for x, y in cells
                  if can_cell(can_id((x, y))) == (x, y))


def neighbours(can_set, cell: tuple[int, int]) -> list[tuple[int, int]]:
    """The can's orthogonal neighbours in the can grid (no diagonals), restricted to real cans."""
    x, y = cell
    return sorted(c for c in ((x, y - 2), (x, y + 2), (x - 2, y), (x + 2, y)) if c in can_set)


def stand_tile(cell: tuple[int, int], walkable, blocked) -> tuple[int, int, str] | None:
    """(x, y, facing) to press the can from: the tile above (facing DOWN) first, else below (facing UP) -
    whichever is walkable and not a trainer/NPC tile. None when neither side can be stood on."""
    x, y = cell
    for (sx, sy), facing in (((x, y - 1), "DOWN"), ((x, y + 1), "UP")):
        if (sx, sy) in walkable and (sx, sy) not in blocked:
            return sx, sy, facing
    return None


def is_can_text(text: str) -> bool:
    """The box text is a trash-can's (loose lower-case match on the pokered can lines - the 2nd-lock
    text says only "electric"/"lock" and never "trash")."""
    t = text.lower()
    return any(w in t for w in ("trash", "electric", "nope"))


def classify(text: str) -> str:
    """The result a can's box text reports: "first" / "second" / "reset" / "nothing".

    The four pokered lines (data/text/text_2.asm:714-748, cited by the controller), matched loosely on
    the lower-cased words - a --fast-text flash can leave only a fragment, and the reset Fail text
    still keeps its "Nope!" prefix (comma "Nope," is the plain miss)."""
    t = text.lower()
    if "2nd electric" in t:
        return "second"
    if "1st electric" in t or "switch under" in t:
        return "first"
    if "locks were reset" in t or t.lstrip().startswith("nope!"):
        return "reset"
    return "nothing"  # "nope, there...", "only trash", silence, anything else


def _can_cell_of(value, can_set) -> tuple[int, int] | None:
    """The can cell a RAM lock index names (0 is can 0, a real index - no sentinel). None for a
    non-int or a non-can index; the armed/stale leg is gated on the flag bit, not the value."""
    if isinstance(value, int) and not isinstance(value, bool):
        cell = can_cell(value)
        if cell in can_set:
            return cell
    return None


def referee_result(before: int, after: int) -> str | None:
    """What the lock event byte's diff says one can press did - a REFEREE: it scores a made press,
    never picks the next can (SEARCH stays RAM-free). UNVERIFIED base (live read 0x1E -> 0x1F on the
    2nd-lock press): bit1 = 1st lock, bit0 = 2nd. bit1 0->1 = "first"; bit1 1->0 = "reset" (the only
    way it drops - a wrong press while armed); bit0 0->1 = "second". The RAM pair is never judged:
    D744 is never cleared, so a stale index matching the pressed can means nothing. None = the press
    moved no lock bit."""
    if after & FLAG_1ST and not before & FLAG_1ST:
        return "first"
    if before & FLAG_1ST and not after & FLAG_1ST:
        return "reset"
    if after & FLAG_2ND and not before & FLAG_2ND:
        return "second"
    return None


def barrier_stepping_tiles(tm: bytes, px: int, py: int) -> dict | None:
    """Stepping tile id of each barrier cell read off the live 20x18 tile map (player's cell at screen
    block (4,4), the stepping tile is a block's bottom-left); None unless all four cells are on screen."""
    out = {}
    for bx, by in BARRIER:
        c, r = bx - px + 4, by - py + 4
        if not (0 <= c <= 9 and 0 <= r <= 8):
            return None
        out[(bx, by)] = tm[(2 * r + 1) * 20 + 2 * c]
    return out


def watch_barrier(st: dict, tm: bytes, px: int, py: int) -> str | None:
    """Track the barrier cells' tile ids (baseline = first time all four are on screen); a DIFFERENCE
    is logged once. The ids are known now (48/17 closed, all 17 open after the 2nd lock) -
    ``barrier_is_open`` is the gate; this just narrates the change."""
    seen = barrier_stepping_tiles(tm, px, py)
    if seen is None:
        return None
    base = st.get("barrier_tiles")
    if base is None:
        st["barrier_tiles"] = seen
        return None
    if seen != base:
        st["barrier_tiles"] = seen      # re-baseline: each further change reports once
        return f"barrier cells changed {base} -> {seen}"
    return None


def barrier_is_open(tm: bytes, px: int, py: int) -> bool:
    """All four barrier stepping tiles read the open id 17 (round-5 read: closed shows 48/17, open
    all 17, only after the 2nd lock). False unless all four cells are on screen."""
    seen = barrier_stepping_tiles(tm, px, py)
    return seen is not None and all(t == BARRIER_OPEN_TILE for t in seen.values())


class Search:
    """The try-order state machine (the controller's round-5 rules, pokered-grounded). No first lock
    yet: cans in a fixed order (can id), skipping ones that answered "nothing" since the last reset
    (``tried``). After a first-lock hit the game is ARMED and any press but the second lock's can
    resets - exactly ONE guess among that can's orthogonal neighbours per arming. A "reset" clears
    the answer memory (D743 re-randomized). A pass out of candidates starts the next (``attempts``);
    the only bound is MAX_TOTAL presses. ``skipped`` holds unpressable cans, so an unreachable puzzle
    still ends in "gave up". ``record`` gets only the result word - never the referee RAM values."""

    def __init__(self, cans: list[tuple[int, int]]) -> None:
        self.cans = list(cans)
        self.can_set = frozenset(cans)
        self.tried: set = set()           # "nothing" answers since the last reset
        self.spent: set = set()           # neighbours already guessed THIS arming (one is normal)
        self.skipped: set = set()         # cans the behaviour could never press: out for the run
        self.first: tuple | None = None   # the can that opened the first lock this arming
        self.pending: tuple | None = None # the can ``next_can`` last returned, awaiting record()
        self.total = 0                    # can presses this run
        self.attempts = 1                 # the pass over the can order this run is on
        self.resets = 0
        self.hits = 0
        self.done = False                 # the second lock opened
        self.gave_up = False

    def next_can(self) -> tuple[int, int] | None:
        if self.done or self.gave_up:
            return None
        if self.total >= MAX_TOTAL:
            self.gave_up = True
            return None
        can = self._pick()
        if can is None:                     # this pass ran out of candidates: start the next one
            self.attempts += 1
            self.tried.clear()              # the locks re-randomize anyway; a lost answer is retried
            self.spent.clear()
            self.first = None
            can = self._pick()
            if can is None:                 # every can is out of candidacy: nothing left to press
                self.gave_up = True
        self.pending = can
        return can

    def _pick(self) -> tuple[int, int] | None:
        if self.first is not None:
            cand = [c for c in neighbours(self.can_set, self.first)
                    if c not in self.spent and c not in self.skipped]
            if cand:
                return cand[0]              # the one armed guess: hit -> second, miss -> reset
            self.first = None               # every neighbour guessed: this arming is spent
        return next((c for c in self.cans if c not in self.tried and c not in self.skipped), None)

    def record(self, result: str) -> None:
        """Fold one can's result into the state machine ("first" / "second" / "reset" / "nothing")."""
        can, self.pending = self.pending, None
        if can is None or self.done or self.gave_up:
            return
        self.total += 1
        if result == "first":
            self.first, self.hits = can, self.hits + 1
            self.tried.add(can)
            self.spent.clear()              # a fresh arming: no neighbour guessed yet
        elif result == "second":
            self.done, self.hits = True, self.hits + 1
        elif result == "reset":
            self.resets, self.first = self.resets + 1, None
            self.tried.clear()              # the locks re-randomized: old answers no longer hold
            self.spent.clear()
        else:                               # "nothing": no first lock here; an armed can cannot answer
            self.tried.add(can)             # "nothing" in pokered - a lost verdict just spends the guess
            self.spent.add(can)

    def skip(self, can: tuple[int, int]) -> None:
        """A can we could not reach or press: out of this run's candidacy entirely."""
        self.skipped.add(can)
        self.tried.add(can)
        if self.pending == can:
            self.pending = None

    def score(self) -> dict:
        """The end-of-puzzle score line: cans tried, resets, lock hits, passes run."""
        return {"tried": self.total, "resets": self.resets, "hits": self.hits, "attempts": self.attempts}


class Oracle(Search):
    """The game's own lock values (read, never written) steer the walk - live, leg by leg: while the
    1st-lock bit is clear the target is D743's can; once it reads set, D744's (D744 is never cleared,
    so the bit - not a 0 or non-can value - says when it means something; 0 is can 0, a real index).
    The behaviour re-reads the triple every step and calls ``set_locks``; a non-can value on the
    current leg falls back to the ordinary search pick for that step, never to a stale plan."""

    def __init__(self, cans: list[tuple[int, int]], lock_ids=None) -> None:
        super().__init__(cans)
        self.locks = (0, 0, 0)
        if lock_ids:
            self.set_locks(*lock_ids)

    def set_locks(self, first_idx, second_idx, flags: int = 0) -> None:
        """The triple the behaviour just read (D743, D744, the lock event byte)."""
        self.locks = (first_idx, second_idx, flags or 0)

    def _armed(self) -> bool:
        """The 1st lock reads open: our own verdict said so, or the event byte's bit1 is set."""
        return self.first is not None or bool(self.locks[2] & FLAG_1ST)

    def _lock_target(self) -> tuple[int, int] | None:
        idx = self.locks[1] if self._armed() else self.locks[0]
        return _can_cell_of(idx, self.can_set)

    def _pick(self) -> tuple[int, int] | None:
        target = self._lock_target()
        if target is not None and target not in self.skipped:
            return target
        return super()._pick()


def make_solver(mode: str, cans: list[tuple[int, int]], lock_ids=None) -> Search:
    """ORACLE -> an Oracle seeded with the triple just read (its per-pick fallback covers a non-can
    value); SEARCH -> a plain Search, which never sees a lock value."""
    if mode == "oracle":
        return Oracle(cans, lock_ids)
    return Search(cans)


def state(ctx) -> dict:
    """The run's puzzle state; ``open`` is goal_talk's only read (the beat_surge barrier guard)."""
    return ctx.__dict__.setdefault("gym_puzzle", {"open": False, "solver": None, "can": None, "stand": None,
                                                "await": None, "presses": 0, "tries": {}, "cooldown_until": 0,
                                                "gave_up": False, "summarised": False, "barrier_tiles": None,
                                                "locks_seen": None, "can_locks": None})


def is_open(ctx) -> bool:
    """The REQUIRES-style guard for the walk to Surge: the puzzle state says the barrier is open."""
    return bool(ctx.__dict__.get("gym_puzzle", {}).get("open"))
