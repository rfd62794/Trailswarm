"""WRAM snapshot/diff: find which bytes changed, and which changed on cue.

The calibration idea: press RIGHT three times and keep only the bytes that
went +1 on every press - that is how an address gets promoted from guess to
registry entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from pokeagent.emulator import Emulator
from pokeagent.names import Registry

WRAM_START = 0xC000
WRAM_LEN = 0x2000


def snapshot(emu: Emulator) -> bytes:
    """One 8 KiB copy of work RAM (0xC000-0xDFFF)."""
    return emu.read_range(WRAM_START, WRAM_LEN)


@dataclass(frozen=True)
class Change:
    """One byte that differed between two snapshots."""

    addr: int
    old: int
    new: int


def diff(before: bytes, after: bytes, base: int = WRAM_START) -> list[Change]:
    """Every byte that changed between two equal-length snapshots."""
    if len(before) != len(after):
        raise ValueError("snapshots must be the same length")
    return [
        Change(base + i, b, a)
        for i, (b, a) in enumerate(zip(before, after))
        if b != a
    ]


def find_consistent(
    snaps: list[bytes], *, delta: int | None = None, base: int = WRAM_START
) -> list[int]:
    """Addresses that changed between every consecutive pair of snaps.

    With ``delta`` set, only addresses whose change equals delta every time
    (walking RIGHT with delta=1 isolates the X coordinate).
    """
    if len(snaps) < 2:
        return []
    n = min(len(s) for s in snaps)
    out: list[int] = []
    for i in range(n):
        deltas = [snaps[j + 1][i] - snaps[j][i] for j in range(len(snaps) - 1)]
        if delta is None:
            if all(d != 0 for d in deltas):
                out.append(base + i)
        elif all(d == delta for d in deltas):
            out.append(base + i)
    return out


def exclude_noisy(snaps_idle: list[bytes], base: int = WRAM_START) -> set[int]:
    """Addresses that changed while idle (timers, RNG) - subtract these."""
    noisy: set[int] = set()
    for a, b in zip(snaps_idle, snaps_idle[1:]):
        noisy.update(c.addr for c in diff(a, b, base))
    return noisy


def annotate(changes: list[Change], registry: Registry) -> list[str]:
    """Human-readable lines: ``D362 wXCoord 03 -> 04 (3 -> 4)``."""
    lines: list[str] = []
    for c in changes:
        name = registry.name_at(c.addr) or "-"
        lines.append(
            f"{c.addr:04X} {name} {c.old:02X} -> {c.new:02X} ({c.old} -> {c.new})"
        )
    return lines
