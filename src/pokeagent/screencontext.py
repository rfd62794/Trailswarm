from dataclasses import dataclass
from enum import IntEnum

from pokeagent.screentext import CHARMAP


class ScreenType(IntEnum):
    UNKNOWN = 0
    OVERWORLD = 1
    DIALOG = 2
    MENU = 3
    BATTLE = 4


class MenuKind(IntEnum):
    UNKNOWN = 0
    START = 1
    ITEMS = 2
    PARTY = 3
    POKEDEX = 4
    SAVE = 5
    OPTIONS = 6
    PC = 7
    SHOP = 8
    BATTLE_COMMAND = 9
    BATTLE_MOVES = 10


@dataclass(frozen=True)
class ScreenContext:
    screen: ScreenType
    menu: MenuKind = MenuKind.UNKNOWN
    confidence: float = 0.0
    cursor: tuple[int, int] = (-1, -1)

    def observation(self) -> tuple[int, ...]:
        return (int(self.screen), int(self.menu), round(self.confidence * 10), *self.cursor)


def classify_screen(tilemap: bytes, battle_kind: int = 0) -> ScreenContext:
    if len(tilemap) != 360:
        return ScreenContext(ScreenType.UNKNOWN)
    cursors = [(i // 20, i % 20) for i, b in enumerate(tilemap) if b == 0xED]
    cursor = cursors[0] if len(cursors) == 1 else (-1, -1)
    framed = b'\x79\x7a' in tilemap
    lines = []
    for r in range(18):
        row = tilemap[r * 20:(r + 1) * 20]
        if row.count(0x7C) >= 2:
            inner = row[row.index(0x7C) + 1:row.rindex(0x7C)]
            lines.append(''.join(CHARMAP.get(b, ' ') for b in inner).upper())
    text = ' '.join(lines).replace('É', 'E')
    kind = MenuKind.UNKNOWN
    if 'FIGHT' in text and 'RUN' in text:
        kind = MenuKind.BATTLE_COMMAND
    elif 'TYPE/' in text and 'PP' in text:
        kind = MenuKind.BATTLE_MOVES
    elif all(word in text for word in ('SAVE', 'OPTION')) and ('POKEDEX' in text or ('ITEM' in text and 'EXIT' in text)):
        kind = MenuKind.START
    elif all(word in text for word in ('TEXT SPEED', 'BATTLE ANIMATION', 'BATTLE STYLE')):
        kind = MenuKind.OPTIONS
    elif 'WITHDRAW' in text and ('DEPOSIT' in text or 'ITEM' in text):
        kind = MenuKind.PC
    elif all(word in text for word in ('BUY', 'SELL', 'QUIT')):
        kind = MenuKind.SHOP
    if battle_kind in (1, 2):
        return ScreenContext(ScreenType.BATTLE, kind, 1.0, cursor)
    if kind != MenuKind.UNKNOWN:
        return ScreenContext(ScreenType.MENU, kind, 0.9, cursor)
    if framed:
        return ScreenContext(ScreenType.MENU if cursors else ScreenType.DIALOG,
                             confidence=0.6, cursor=cursor)
    return ScreenContext(ScreenType.UNKNOWN)
