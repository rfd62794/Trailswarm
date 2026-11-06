"""The anomaly detectors: pure state machines over one Obs per press (no emulator, no files)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from pokeagent.explorer.perceive import DIRS

# --- named thresholds (presses unless stated) ---
DOORWAY_PRESSES = 15        # a wanderer sat on a door tile this many presses in a row
BLOCKING_PRESSES = 8        # the agent pressed into the same wanderer on its next tile this many times
PLAYER_BLOCK_PRESSES = 12   # the agent stood still next to a wanderer that could not leave, this many presses
FROZEN_PRESSES = 30         # nothing on screen/in the sprite table/position changed, with >= FROZEN_BUTTONS different buttons
FROZEN_BUTTONS = 3
BATTLE_MAX_PRESSES = 500    # a battle lasting longer
TEXT_MAX_PRESSES = 200      # a text box open longer
IMPOSSIBLE_DEBOUNCE = 2     # consecutive observations a broken invariant must persist (fades read garbage)
TELEPORT_MIN_JUMP = 2       # Manhattan tiles
FORCED_WALK_MAX = 10        # a straight jump this long on a spinner map is a forced walk, not a teleport
SPINNER_MAPS = frozenset({0x2D, 0xC7, 0xC8, 0xC9, 0xCA})  # Viridian Gym, Rocket Hideout B1F-B4F (arrow tiles)


@dataclass
class Obs:
    """What one finished press looked like."""
    step: int
    frame: int
    map: int
    x: int
    y: int
    button: str
    prev: tuple | None = None          # (map, x, y) before the press
    sprites: dict = field(default_factory=dict)   # slot -> (pic, x, y)
    wanderers: set = field(default_factory=set)   # slots seen on more than one tile
    doors: set = field(default_factory=set)       # doorway tiles of this map
    walkable: set = field(default_factory=set)    # tiles known standable on this map
    warps: dict = field(default_factory=dict)
    jumps: dict = field(default_factory=dict)
    box: bool = False
    box_before: bool = False
    battle: bool = False
    joy_ignore: int = 0
    screen_sig: int = 0                # hash(tilemap, sprite table)
    broken: list = field(default_factory=list)    # impossible_state invariant names


@dataclass
class Finding:
    type: str
    map: int
    x: int
    y: int
    tile: tuple                         # rate-limit tile
    details: dict = field(default_factory=dict)
    npc: tuple | None = None            # (slot, pic, x, y) of the NPC involved, for the cause hint


def _pos(o: Obs) -> tuple:
    return (o.map, o.x, o.y)


class Detectors:
    """Feed ``update(obs)`` once per press; it returns the findings that fired on that press."""

    def __init__(self) -> None:
        self.door: dict = {}       # slot -> (tile, count)
        self.block: dict = {}
        self.pblock: dict = {}
        self.still = 0             # consecutive presses the player stayed put
        self.battle_n = 0
        self.text_n = 0
        self.window: deque = deque(maxlen=FROZEN_PRESSES)
        self.broken_n: dict = {}
        self.pending_tp: Finding | None = None   # a teleport held one observation, until the screen proves it was no cutscene

    def reset(self) -> None:
        self.__init__()

    def update(self, o: Obs) -> list[Finding]:
        self.still = self.still + 1 if o.prev == _pos(o) and not o.box else 0
        return (self._doorway(o) + self._blocking(o) + self._player_blocking(o) + self._teleport(o)
                + self._impossible(o) + self._frozen(o) + self._endless(o))

    @staticmethod
    def _bump(table: dict, slot: int, tile: tuple) -> int:
        old = table.get(slot)
        n = old[1] + 1 if old and old[0] == tile else 1
        table[slot] = (tile, n)
        return n

    @staticmethod
    def _keep(table: dict, live: set) -> None:
        for slot in [s for s in table if s not in live]:
            del table[slot]

    @staticmethod
    def _npc_finding(kind: str, o: Obs, slot: int, sprite: tuple, n: int, **extra) -> Finding:
        pic, sx, sy = sprite
        return Finding(kind, o.map, sx, sy, (sx, sy), {"npc_slot": slot, "npc_pic": pic, "npc_at": [sx, sy],
                       "presses": n, "player": [o.x, o.y], **extra}, (slot, pic, sx, sy))

    def _doorway(self, o: Obs) -> list[Finding]:
        live, out = set(), []
        for slot, sprite in o.sprites.items():
            if slot in o.wanderers and sprite[1:] in o.doors:
                live.add(slot)
                n = self._bump(self.door, slot, (o.map, *sprite[1:]))
                if n >= DOORWAY_PRESSES:
                    out.append(self._npc_finding("npc_in_doorway", o, slot, sprite, n))
        self._keep(self.door, live)
        return out

    def _blocking(self, o: Obs) -> list[Finding]:
        live, out = set(), []
        if o.button in DIRS and o.prev == _pos(o) and not o.box:
            dx, dy = DIRS[o.button]
            for slot, sprite in o.sprites.items():
                if slot in o.wanderers and sprite[1:] == (o.x + dx, o.y + dy):
                    live.add(slot)
                    n = self._bump(self.block, slot, (o.map, *sprite[1:]))
                    if n >= BLOCKING_PRESSES:
                        out.append(self._npc_finding("npc_blocking_path", o, slot, sprite, n, button=o.button))
        self._keep(self.block, live)
        return out

    def _player_blocking(self, o: Obs) -> list[Finding]:
        live, out = set(), []
        if self.still >= 1:
            for slot, sprite in o.sprites.items():
                sx, sy = sprite[1:]
                if slot not in o.wanderers or abs(sx - o.x) + abs(sy - o.y) != 1:
                    continue
                taken = {p[1:] for s, p in o.sprites.items() if s != slot} | {(o.x, o.y)}
                if any((sx + dx, sy + dy) in o.walkable and (sx + dx, sy + dy) not in taken for dx, dy in DIRS.values()):
                    continue  # the NPC has somewhere else to go
                live.add(slot)
                n = self._bump(self.pblock, slot, (o.map, sx, sy))
                if n >= PLAYER_BLOCK_PRESSES:
                    out.append(self._npc_finding("player_blocking_npc", o, slot, sprite, n))
        self._keep(self.pblock, live)
        return out

    def _teleport(self, o: Obs) -> list[Finding]:
        out, self.pending_tp = ([self.pending_tp] if self.pending_tp and not (o.box or o.joy_ignore) else []), None
        if o.box or o.joy_ignore or o.box_before:
            return out  # forced walks, cutscenes, whiteouts: the game moved the player
        self.pending_tp = self._teleport_candidate(o)
        return out

    def _teleport_candidate(self, o: Obs) -> Finding | None:
        if o.prev is None or o.prev[0] != o.map:
            return None
        dx, dy = o.x - o.prev[1], o.y - o.prev[2]
        dist = abs(dx) + abs(dy)
        if dist < TELEPORT_MIN_JUMP:
            return None
        pk = f"{o.prev[1]},{o.prev[2]},"
        if any(k.startswith(pk) for k in o.warps) or any(k.startswith(pk) for k in o.jumps):
            return None  # a learned warp within the map, or a ledge hop
        straight = dx == 0 or dy == 0
        if straight and dist <= FORCED_WALK_MAX and o.map in SPINNER_MAPS:
            return None  # spinner arrows: a forced walk
        return Finding("teleport", o.map, o.x, o.y, (o.x, o.y), {"from": list(o.prev[1:]), "to": [o.x, o.y],
                        "jump": dist, "straight": straight, "button": o.button})

    def _impossible(self, o: Obs) -> list[Finding]:
        now = set(o.broken)
        for k in [k for k in self.broken_n if k not in now]:
            del self.broken_n[k]
        out = []
        for k in sorted(now):
            self.broken_n[k] = self.broken_n.get(k, 0) + 1
            if self.broken_n[k] >= IMPOSSIBLE_DEBOUNCE:
                out.append(Finding("impossible_state", o.map, o.x, o.y, (k.split(" ")[0],), {"invariant": k}))
        return out

    def _frozen(self, o: Obs) -> list[Finding]:
        if o.box or o.battle or o.joy_ignore:
            self.window.clear()
            return []
        self.window.append(((o.screen_sig, _pos(o)), o.button))
        if len(self.window) < FROZEN_PRESSES:
            return []
        if len({s for s, _ in self.window}) == 1 and len({b for _, b in self.window}) >= FROZEN_BUTTONS:
            return [Finding("frozen_screen", o.map, o.x, o.y, (o.x, o.y),
                            {"presses": len(self.window), "buttons": sorted({b for _, b in self.window})})]
        return []

    def _endless(self, o: Obs) -> list[Finding]:
        self.battle_n = self.battle_n + 1 if o.battle else 0
        self.text_n = self.text_n + 1 if o.box and not o.battle else 0
        out = []
        if self.battle_n >= BATTLE_MAX_PRESSES:
            out.append(Finding("endless_battle", o.map, o.x, o.y, (o.x, o.y), {"presses": self.battle_n}))
        if self.text_n >= TEXT_MAX_PRESSES:
            out.append(Finding("endless_text", o.map, o.x, o.y, (o.x, o.y), {"presses": self.text_n}))
        return out
