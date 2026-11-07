"""Join mined candidates with ram_map.json labels: 'confirms label', 'labelled' (label found, relation not expected)
or 'new finding' (no label, or an unused/unknown region)."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# What each event type is expected to touch, by label name: a hit on one of these 'confirms' the label.
HINTS: dict[str, str] = {
    "battle_start": r"IsInBattle|CurOpponent|BattleType|EnemyMon|EnemyBattle|BattleMon|TrainerClass|TrainerNo|Opponent|PlayerMonNumber|Channel|Audio|Music|Sound|Sfx|Pitch|Duty|Vibrato|Frequency|Volume",
    "battle_end": r"IsInBattle|CurOpponent|BattleType|BattleResult|EnemyMon|BattleMon|Channel|Audio|Music|Sound|Sfx|Pitch|Duty|Vibrato|Frequency|Volume",
    "map_change": r"CurMap|Coord|LastMap|Tileset|MapHeight|MapWidth|MapConn|Warp|DestinationMap|CurMapScript|BlockMap|ViewPointer|Sprite|NumSprites|Overworld|Channel|Audio|Music|Sound|Sfx|Pitch|Duty|Vibrato|Frequency|Volume",
    "item_gain": r"NumBagItems|BagItems|ItemQuantity|CurItem",
    "item_use": r"NumBagItems|BagItems|ItemQuantity|CurItem",
    "money": r"PlayerMoney|CurOpponent",  # trainer battles pay out, and clear the trainer id, on the same press
    "party_change": r"PartyCount|PartySpecies|PartyMon|PartyMons",
    "text_open": r"TextBox|TileMap|FontLoaded|JoyIgnore|Text|Letter|d730|StatusFlags|Menu",
    "text_close": r"CurOpponent|TextBox|TileMap|FontLoaded|JoyIgnore|Text|Letter|d730|StatusFlags|Menu",
    "menu_open": r"Menu|ListScroll|ListCount|TopMenu|MaxMenu|CurrentMenu|ItemList|Cursor",
    "story_flag": r"EventFlags|Flags|Obtained|Beat",
    "heal": r"PartyMon\d*(HP|Status)|BattleMonHP|Status",
    "pc_shop": r"BoxCount|NumBoxItems|BoxItems|NumBagItems|PlayerMoney|BoxNum|Pc|PC",
    "step": r"Coord|WalkCounter|PlayerDirection|PlayerMoving|SpritePlayer|Facing|StepCounter|Block",
    "goal": r".",
}
STACK_LO = 0xDF00
UNKNOWN_NAME = re.compile(r"Unused|Unknown|Filler|Padding|Buffer|Scratch|Temp|Tmp|^w?d[0-9a-f]{3}$", re.IGNORECASE)


@dataclass
class Label:
    name: str
    addr: int
    size: int
    verified: bool
    region: str

    def contains(self, addr: int) -> bool:
        return self.addr <= addr < self.addr + max(1, self.size)


class LabelIndex:
    def __init__(self, entries: list[dict]) -> None:
        self.labels = sorted((Label(e["name"], int(e["addr"], 16), e["size"], bool(e.get("verified")), e["region"])
                              for e in entries), key=lambda lb: (lb.addr, lb.size))
        self._starts = [lb.addr for lb in self.labels]

    def at(self, addr: int) -> Label | None:
        """The smallest label containing ``addr`` (the most specific one)."""
        i = bisect.bisect_right(self._starts, addr)
        best = None
        for lb in reversed(self.labels[max(0, i - 64):i]):
            if lb.contains(addr) and (best is None or lb.size < best.size):
                best = lb
        return best

    def join(self, event: str, addr: int) -> tuple[str, Label | None]:
        """('confirms' | 'labelled' | 'new' | 'stack', label)."""
        lb = self.at(addr)
        if STACK_LO <= addr <= 0xDFFF and (lb is None or lb.name == "wStack"):
            return "stack", lb                                 # the call stack: churns with execution, names nothing
        if lb is None or UNKNOWN_NAME.search(lb.name):
            return "new", lb
        if re.search(HINTS.get(event, r"$^"), lb.name):
            return "confirms", lb
        return "labelled", lb


def load_entries(path: Path | None = None) -> list[dict]:
    import json
    return json.loads((path or DATA / "ram_map.json").read_text(encoding="utf-8"))
