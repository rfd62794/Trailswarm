"""gym_puzzle: Lt. Surge's trash-can locks (Vermilion Gym, map 0x5C) - pure logic, no emulator, no atlas.

Two modes (Robert, 2026-11-16, explore BOTH in one module): SEARCH (default: the agent finds the cans by
trying them) and ORACLE (reads the game's own lock values and goes straight to them). In SEARCH mode the
RAM lock values may be read ONLY to log and score the attempt - a referee, never a choice: ``Search`` never
sees them (``next_can`` takes no RAM argument). ORACLE reads wFirstLockTrashCanIndex (0xD743) and
wSecondLockTrashCanIndex (0xD744, ram_map.json: verified=false); a 0 or non-can value falls back to SEARCH.

Facts from the read-only probe (grid, can tile); UNVERIFIED where marked - the controller's real-ROM check
confirms each one:
- 15 cans, id = col*3 + row with col = (x-1)/2, row = (y-7)/2; the can tile in cell_tiles is 0x1B.
- The first lock is one random can; the second is an orthogonal neighbour of it (UNVERIFIED); a wrong can
  after the first resets both locks, re-randomized (UNVERIFIED).
- Lock text (UNVERIFIED - not in the repo text tables, matched loosely): "The 1st/2nd electric lock
  opened!", "...the electric locks were reset!". Barrier cells x 4-5, y 4-5 change tile ids when open
  (UNVERIFIED; a secondary signal, logged, never the only one).
"""
from __future__ import annotations

GYM = 0x5C
GOAL = "beat_surge"
CAN_TILE = 0x1B
BARRIER = ((4, 4), (5, 4), (4, 5), (5, 5))  # probe: the closed electric barrier's cells
MODES = ("search", "oracle")
ENV_MODE = "POKEAGENT_GYM_PUZZLE_MODE"
LOCK_ADDRS = (0xD743, 0xD744)   # wFirstLockTrashCanIndex, wSecondLockTrashCanIndex (ram_map.json, unverified)
GYM_CAN_ADDR = 0xCD5B           # wGymTrashCanIndex
MAX_PER_ATTEMPT = 15            # cans tried with no first lock -> give up (there are only 15)
MAX_TOTAL = 60                  # can presses per run -> give up


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
    """The box text is a trash-can's (loose lower-case match - the exact strings are UNVERIFIED)."""
    t = text.lower()
    return "trash" in t or "electric lock" in t


def classify(text: str) -> str:
    """The result a can's box text reports: "first" / "second" / "reset" / "nothing".

    UNVERIFIED strings (the probe names them; the repo's text tables do not): matched loosely on the
    lower-cased words "electric lock", "opened", "reset", "only trash"."""
    t = text.lower()
    if "electric lock" in t:
        if "opened" in t:
            return "second" if ("2nd" in t or "second" in t) else "first"
        if "reset" in t:
            return "reset"
    return "nothing"  # "only trash", silence, anything else


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
    from the baseline is the open signal. UNVERIFIED: which ids mark 'open' is unknown, so this is a
    secondary signal next to the lock text - logged, never the only one."""
    seen = barrier_stepping_tiles(tm, px, py)
    if seen is None:
        return None
    base = st.get("barrier_tiles")
    if base is None:
        st["barrier_tiles"] = seen
        return None
    if seen != base:
        st["barrier_tiles"] = seen      # re-baseline: each further change reports once
        return f"barrier cells changed {base} -> {seen} (UNVERIFIED open read)"
    return None


class Search:
    """The try-order state machine. No first lock yet: cans in a fixed order (can id, skipping tried
    ones). After a first-lock hit: only that can's UNTRIED orthogonal neighbours (``tried2``: a can
    that answered "nothing" before the lock armed can still be the second). A "reset" clears both
    tried-sets (the game re-randomizes) and counts. ``record`` gets only the result word - never the
    referee RAM values (those go to log lines and the score)."""

    def __init__(self, cans: list[tuple[int, int]]) -> None:
        self.cans = list(cans)
        self.can_set = frozenset(cans)
        self.tried: set = set()           # first-lock hunt: cans pressed this attempt
        self.tried2: set = set()          # second-lock hunt: the first lock's neighbours already pressed
        self.first: tuple | None = None   # the can that opened the first lock this attempt
        self.pending: tuple | None = None # the can ``next_can`` last returned, awaiting record()
        self.total = 0                    # can presses this run
        self.resets = 0
        self.hits = 0
        self.done = False                 # the second lock opened
        self.gave_up = False

    def next_can(self) -> tuple[int, int] | None:
        if self.done or self.gave_up:
            return None
        if self.total >= MAX_TOTAL or (self.first is None and len(self.tried) >= MAX_PER_ATTEMPT):
            self.gave_up = True
            return None
        can = self._pick()
        if can is None:
            self.gave_up = True
        self.pending = can
        return can

    def _pick(self) -> tuple[int, int] | None:
        if self.first is not None:
            cand = [c for c in neighbours(self.can_set, self.first) if c not in self.tried2]
            if cand:
                return cand[0]
        return next((c for c in self.cans if c not in self.tried), None)

    def record(self, result: str) -> None:
        """Fold one can's result into the state machine ("first" / "second" / "reset" / "nothing")."""
        can, self.pending = self.pending, None
        if can is None or self.done or self.gave_up:
            return
        self.total += 1
        if result == "first":
            self.first, self.hits = can, self.hits + 1
            self.tried.add(can)
        elif result == "second":
            self.done, self.hits = True, self.hits + 1
        elif result == "reset":
            self.resets, self.first = self.resets + 1, None
            self.tried.clear()            # both tried-sets: the locks re-randomized, start over
            self.tried2.clear()
        elif self.first is not None:      # "nothing" while armed: not the second lock (a missed text)
            self.tried2.add(can)
        else:                             # "nothing": this can answered no first lock
            self.tried.add(can)

    def skip(self, can: tuple[int, int]) -> None:
        """A can we could not reach or press: out of this attempt's candidates without a result."""
        self.tried.add(can)
        self.tried2.add(can)
        if self.pending == can:
            self.pending = None

    def score(self) -> dict:
        """The end-of-puzzle score line: cans tried, resets, lock hits."""
        return {"tried": self.total, "resets": self.resets, "hits": self.hits}


class Oracle(Search):
    """The game's own lock values (read, never written) as can indices: the plan is [first, second];
    then the ordinary search continues if they were stale. An invalid pair never gets here - make_solver
    falls back to Search."""

    def __init__(self, cans: list[tuple[int, int]], plan_cans: list[tuple[int, int]]) -> None:
        super().__init__(cans)
        self.queue = list(plan_cans)

    def _pick(self) -> tuple[int, int] | None:
        while self.queue:
            can = self.queue.pop(0)
            if can not in self.tried:
                return can
        return super()._pick()


def make_solver(mode: str, cans: list[tuple[int, int]], lock_ids=None) -> Search:
    """ORACLE with two real can indices -> Oracle; a 0 or non-can value, or SEARCH mode -> Search."""
    if mode == "oracle" and lock_ids:
        cells = [can_cell(i) for i in lock_ids if isinstance(i, int) and not isinstance(i, bool) and i != 0]
        if len(cells) == 2 and all(c in cans for c in cells):
            return Oracle(cans, cells)
    return Search(cans)


def state(ctx) -> dict:
    """The run's puzzle state; ``open`` is goal_talk's only read (the beat_surge barrier guard)."""
    return ctx.__dict__.setdefault("gym_puzzle", {"open": False, "solver": None, "can": None, "stand": None,
                                                "await": None, "presses": 0, "tries": {}, "cooldown_until": 0,
                                                "gave_up": False, "summarised": False, "barrier_tiles": None})


def is_open(ctx) -> bool:
    """The REQUIRES-style guard for the walk to Surge: the puzzle state says the barrier is open."""
    return bool(ctx.__dict__.get("gym_puzzle", {}).get("open"))
