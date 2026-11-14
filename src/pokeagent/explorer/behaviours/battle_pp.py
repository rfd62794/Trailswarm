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


def cursor_step(cursor_mv: str, target: str, usable: list[str], nav: int) -> tuple[str, str | None]:
    """("press_a", move) when the move under the cursor is the target, or (nav > 5, the walk has gone on too
    long) when it is any usable move; otherwise ("down", None). Never ("press_a", m) for an m not in usable."""
    if _norm(cursor_mv) == _norm(target) and target in usable:
        return "press_a", target
    if nav > 5 and cursor_mv in usable:
        return "press_a", cursor_mv
    return "down", None
