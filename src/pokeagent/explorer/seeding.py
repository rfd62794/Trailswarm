"""seeding: make ``--seed`` produce genuinely different games.

The emulator is deterministic from a saved state: the same inputs at the same frames give the same encounters, so every seed replayed
the same game (the early milestones repeated step for step). The game's RNG is driven by the free-running DIV timer, so the number of
idle frames before the first input shifts every later random draw. Seed 0 or None keeps today's behaviour (no idle frames)."""
from __future__ import annotations

IDLE_RANGE = 256  # idle frames are 0..255


def idle_frames(seed: int | None) -> int:
    """Frames to idle after loading the state, derived from the seed (0 for seed None/0)."""
    if not seed:
        return 0
    return ((seed * 2654435761) >> 12) % IDLE_RANGE
