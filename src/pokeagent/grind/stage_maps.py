"""Where a stage may grind: the maps a story stage's grind point must be on (None = no restriction).

Before Brock only Route 1, Route 2, Route 22 and Viridian Forest are sensible: Route 3 / Mt. Moon lie beyond the gym
being held for (2026-11-12 real-ROM check: a grind episode picked Mt. Moon B1F, 0x3C, for a L4 trainee at Pewter).
"""
from __future__ import annotations

PRE_BROCK = frozenset({0x0C, 0x0D, 0x21, 0x33})
BY_STAGE = {"beat_brock": PRE_BROCK}
# Stages with no allow-list above: the area ladder's candidate maps (train_target.stage_target only;
# BY_STAGE alone stays the episode gate). Mt Moon stage -> Routes 3/4, Misty stage -> Routes 24/25.
LADDER_BY_STAGE = {"to_mt_moon": frozenset({0x0E, 0x0F}), "beat_misty": frozenset({0x23, 0x24})}


def allowed(stage: str | None) -> frozenset | None:
    return BY_STAGE.get(stage) if stage else None
