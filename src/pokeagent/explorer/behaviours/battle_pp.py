"""battle_pp: the PP guard's pure logic - which menu moves can be pressed, and when the cursor walk ends."""
from __future__ import annotations


def _norm(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def usable_moves(moves: list[str], pp_bytes: tuple[int, ...] | None, no_pp: set[str]) -> list[str]:
    """Moves of the menu list (slot order) that can be pressed: PP (byte & 0x3F) above 0 and not in no_pp.
    pp_bytes None = a stale battle struct (no PP data at all): every move not in no_pp counts as usable."""
    if pp_bytes is None:
        return [mv for mv in moves if mv not in no_pp]
    return [mv for i, mv in enumerate(moves)
            if i < len(pp_bytes) and (pp_bytes[i] & 0x3F) > 0 and mv not in no_pp]


def walk_direction(moves: list[str], cursor_mv: str, target: str) -> str:
    """"up" when the target slot is above the cursor slot, else "down" (also when either is not in the list)."""
    norm = [_norm(m) for m in moves]
    try:
        return "up" if norm.index(_norm(target)) < norm.index(_norm(cursor_mv)) else "down"
    except ValueError:
        return "down"


def cursor_step(cursor_mv: str, target: str, usable: list[str], nav: int,
                moves: list[str] | None = None) -> tuple[str, str | None]:
    """("press_a", move) when the move under the cursor is the target, or (nav > 5, the walk has gone on too
    long) when it is any usable move; otherwise ("up" | "down", None) - the way to the target in the menu's slot
    order `moves` (plain "down" without it). Never ("press_a", m) for an m not in usable."""
    if _norm(cursor_mv) == _norm(target) and target in usable:
        return "press_a", target
    if nav > 5 and cursor_mv in usable:
        return "press_a", cursor_mv
    return (walk_direction(moves, cursor_mv, target) if moves else "down"), None


def off_disabled_step(rows: list[str], cursor_mv: str | None, usable: list[str], last_dir: str = "") -> str:
    """Button for the disabled screen, from the on-screen rows (slot order): "UP"/"DOWN" toward the nearest usable
    row (ties: the way the walk was going; never a no-op at a menu edge on a no-wrap cursor), or "B" when no
    other usable row exists (the game then falls back, ending in STRUGGLE when every move is out)."""
    idx = next((i for i, r in enumerate(rows) if cursor_mv and _norm(r) == _norm(cursor_mv)), None)
    free = [i for i, r in enumerate(rows) if i != idx and r in usable]
    if not free or len(rows) < 2:
        return "B"
    if idx is None:  # cursor row not readable: keep walking the way we were going
        return last_dir or "DOWN"
    if idx == 0:
        return "DOWN"
    if idx == len(rows) - 1:
        return "UP"
    best = min(free, key=lambda i: (abs(i - idx), 0 if (i > idx) == (last_dir == "DOWN") else 1))
    return "DOWN" if best > idx else "UP"
