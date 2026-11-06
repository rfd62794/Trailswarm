"""What a macro sees: one read of the screen and the few RAM cells the battle menus need (pure helpers over an emulator)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pokeagent.explorer.party_menu import MENU_ITEM, is_party_screen, screen_lines
from pokeagent.explorer.perceive import BATTLE_FLAG, TILEMAP, TILEMAP_LEN, box_open, frame_lines, is_menu
from pokeagent.intervene.names import norm, species_name
from pokeagent.knowledge.kb import ROM_KB
from pokeagent.ramstructs import read_bag, read_party

PLAYER_MON = 0xCC2F    # wPlayerMonNumber: the party slot in the fight
BATTLE_MOVES = 0xD01C  # wBattleMonMoves
GRID = {"FIGHT": (0, 0), "PKMN": (1, 0), "ITEM": (0, 1), "RUN": (1, 1)}  # the battle menu: FIGHT PKMN / ITEM RUN


@dataclass
class ScreenRead:
    in_battle: bool = False
    box: bool = False             # a framed box (text, battle menu, list) is open
    menu: bool = False            # the menu cursor tile is on screen
    frames: list[str] = field(default_factory=list)   # framed rows only ('>' marks the cursor)
    screen: list[str] = field(default_factory=list)   # every readable row (party list, unframed text)
    cur: int = 0                  # wCurrentMenuItem

    @property
    def text(self) -> str:
        return " | ".join(self.screen)

    @property
    def busy(self) -> bool:
        """Anything but the bare map: a box, a menu cursor, or a party screen."""
        return self.box or self.menu or is_party_screen(self.text)

    @property
    def mode(self) -> str:
        if self.in_battle:
            return "battle"
        if self.menu or is_party_screen(self.text):
            return "menu"
        return "text" if self.box else "overworld"

    def brief(self, n: int = 10) -> dict:
        return {"mode": self.mode, "in_battle": self.in_battle, "cursor": self.cur,
                "lines": (self.frames or self.screen)[:n]}


def read_screen(emu) -> ScreenRead:
    tm = emu.read_range(TILEMAP, TILEMAP_LEN)
    box = box_open(tm)
    frames = frame_lines(tm) if box else []
    return ScreenRead(in_battle=emu.read(BATTLE_FLAG) != 0 or any("FIGHT" in ln for ln in frames), box=box,
                      menu=is_menu(tm), frames=frames, screen=screen_lines(tm), cur=emu.read(MENU_ITEM))


def main_menu(frames: list[str]) -> bool:
    j = " ".join(frames)
    return all(w in j for w in ("FIGHT", "PKMN", "RUN"))


def main_cursor(frames: list[str]) -> str | None:
    m = re.search(r">\s*(FIGHT|PKMN|ITEM|RUN)", " ".join(frames))
    return m.group(1) if m else None


def toward_main(cur: str, want: str) -> str:
    """Next button of the 2x2 battle menu from `cur` to `want` ('A' once there): sideways first, then up/down."""
    (cx, cy), (wx, wy) = GRID[cur], GRID[want]
    if cx != wx:
        return "RIGHT" if wx > cx else "LEFT"
    return "A" if cy == wy else ("DOWN" if wy > cy else "UP")


def battle_moves(emu) -> list[str]:
    """Names of our battler's moves in menu order (empty slots dropped)."""
    moves = (ROM_KB or {}).get("moves") or {}
    return [moves.get(str(i), {}).get("name", f"move {i}") for i in emu.read_range(BATTLE_MOVES, 4) if i]


def party_names(emu) -> list[str]:
    return [species_name(m.species) for m in read_party(emu)]


def bag_qty(emu, item_id: int) -> int:
    return next((q for i, q in read_bag(emu) if i == item_id), 0)


def party_slot(emu, on) -> int | None:
    """0-based party slot for `on` (a 1-based slot number or a species name); None when not in the party."""
    names = party_names(emu)
    if str(on).isdigit():
        return int(on) - 1 if 1 <= int(on) <= len(names) else None
    return next((i for i, n in enumerate(names) if norm(n) == norm(on)), None)
