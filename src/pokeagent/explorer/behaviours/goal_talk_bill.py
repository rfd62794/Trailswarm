"""goal_talk, ss_ticket: Bill's house is a three-stage goal, and the stage is read from the RAM sprite table (never from vision).

ROM probe (Red, map 0x58, 2026-11-15; see docs/KNOWLEDGE.md): the monster-Bill stands at (6,5). Talk from (6,6) facing UP; the text ends
in a YES/NO box ("Help me out here!"), the cursor starts on YES and dialog.py's default answers YES; he then walks into the teleporter and
his sprite leaves the table. The console is at (1,4): A from (1,5) facing UP runs the Cell Separator ("BCN initiated TELEPORTER Cell
Separator!"). Human Bill then walks out and settles at (4,4); talk from (4,5) facing UP hands over the S.S.TICKET (bag item 0x3F, the
campaign detector). Sprites: monster at (6,5) -> stage 1; none -> stage 2 (console); any other sprite -> stage 3 (Bill walking or settled).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours import goal_talk_alt as alt

BILL_MAP = 0x58
MONSTER_TILE = (6, 5)
STAGES = {"monster": (BILL_MAP, 6, 6, "UP", "Bill (the monster)"),
          "console": (BILL_MAP, 1, 5, "UP", "the Cell Separator console"),
          "human": (BILL_MAP, 4, 5, "UP", "Bill")}
STAND_TILES = {spec[:3] for spec in STAGES.values()}
TALK_CAP = 14  # A presses across all three stages per run (each stage needs one or two; the dialog behaviours do the rest)


def _sprite_tiles(ctx) -> set[tuple[int, int]] | None:
    """Tiles live sprites stand on, or None when there is no emulator to ask (then the first stage is assumed)."""
    emu = getattr(ctx, "emu", None)
    if emu is None:
        return None
    try:
        from pokeagent.explorer.anomaly_sprites import read_sprites
        return {(x, y) for _, x, y in read_sprites(emu).values()}
    except Exception:
        return None


def stage(ctx) -> str:
    tiles = _sprite_tiles(ctx)
    if tiles is None or MONSTER_TILE in tiles:
        return "monster"
    return "console" if not tiles else "human"


def spec(ctx) -> tuple:
    return STAGES[stage(ctx)]


def occupied(ctx, st: str) -> set[tuple[int, int]]:
    return alt.occupied(ctx, alt.npc_tile(*STAGES[st][1:4]))
