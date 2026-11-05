"""Command helpers: key map, speed cycling, and which agents a command targets."""
from __future__ import annotations

KEYMAP = {"Up": "UP", "Down": "DOWN", "Left": "LEFT", "Right": "RIGHT", "a": "A", "s": "B",
          "Return": "START", "Shift_L": "SELECT", "Shift_R": "SELECT"}
SPEEDS = (1, 2, 4, 8)


def press_for_key(key: str, steer_on: bool) -> str | None:
    """Game button for a key name, or None when steering is off or the key is unmapped."""
    return KEYMAP.get(key) if steer_on else None


def targets(selected: str | None, all_ids: list[str], scope: str) -> list[str]:
    """Agent ids a command applies to: ``scope`` is "selected" or "all"."""
    if scope == "all":
        return list(all_ids)
    return [selected] if selected is not None and selected in all_ids else []


def next_speed(cur: int) -> int:
    """Next speed in the cycle 1, 2, 4, 8, then back to 1 (unknown values reset to 1)."""
    return SPEEDS[(SPEEDS.index(cur) + 1) % len(SPEEDS)] if cur in SPEEDS else SPEEDS[0]
