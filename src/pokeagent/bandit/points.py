"""The three decision points: arms, context keys and when each applies. Pure reads of the context; no presses."""
from __future__ import annotations

from pokeagent.explorer.perceive import lead_level

ARMS = {"wild_battle": ("fight", "flee"), "heal": ("heal_now", "push_on"), "train": ("grind", "skip")}
HEAL_BELOW = 0.5


def hp_bucket(hp: int, mx: int) -> int:
    """0: <25%, 1: 25-50%, 2: 50-75%, 3: 75-100%."""
    frac = hp / mx if mx else 1.0
    return min(3, int(frac * 4))


def gap_bucket(gap: int) -> str:
    """Level gap: <=-3, -2..0, 1..3, >3."""
    return "le-3" if gap <= -3 else "m2_0" if gap <= 0 else "p1_3" if gap <= 3 else "gt3"


def context_key(point: str, stage: str, map_id: int, hp: int, mx: int, gap: int) -> str:
    return f"{point}|{stage}|{map_id}|{hp_bucket(hp, mx)}|{gap_bucket(gap)}"


def wild_gap(ctx) -> int:
    """Lead level minus the wild enemy's level."""
    return lead_level(ctx.emu) - ctx.emu.read(0xCFF3)


def train_gap(ctx, need: int) -> int:
    """Lead level minus the training target."""
    return lead_level(ctx.emu) - need


def heal_eligible(ctx, hp: int, mx: int) -> bool:
    """Below 50% outside battle with a Pokecenter map already known to the learned world."""
    from pokeagent.explorer.world import POKECENTER_MAPS
    if ctx.view.battling or not mx or hp / mx >= HEAL_BELOW:
        return False
    maps = ctx.mem.data.get("maps", {})
    return any(str(m) in maps for m in POKECENTER_MAPS)


def train_eligible(ctx, need: int) -> bool:
    """Outside battle, with a training target above the lead's level."""
    level = lead_level(ctx.emu)
    return not ctx.view.battling and 0 < level < need
