"""Agent event stream: typed, schema-versioned, one small dataclass per event, in a bounded ring buffer.

The bus is append-only and lock-light: the emulator thread only appends; the HTTP thread copies out under the same lock and
serialises outside it. ``seq`` rises monotonically per agent (never reused) so a client polls ``since=<last seq>``.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar

EVENT_SCHEMA = 1
DEFAULT_CAPACITY = 4000


@dataclass
class Event:
    TYPE: ClassVar[str] = "event"
    seq: int = 0
    t: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"v": EVENT_SCHEMA, "type": self.TYPE, **asdict(self)}


@dataclass
class Move(Event):
    TYPE: ClassVar[str] = "move"
    map: int = 0
    x: int = 0
    y: int = 0
    facing: str = "DOWN"
    step: int = 0


@dataclass
class MapChange(Event):
    TYPE: ClassVar[str] = "map_change"
    map: int = 0
    x: int = 0
    y: int = 0
    prev_map: int = -1


@dataclass
class Decision(Event):
    TYPE: ClassVar[str] = "decision"
    behaviour: str = ""
    rule: str = ""
    button: str = ""
    outcome: str = ""
    driver: str = ""


@dataclass
class BattleStart(Event):
    TYPE: ClassVar[str] = "battle_start"
    species: str = ""          # enemy species (name when known, else "#<id>")
    enemy_level: int = 0
    own_species: str = ""
    own_level: int = 0
    hp: int = 0
    max_hp: int = 0
    enemy_hp: int = 0
    enemy_max_hp: int = 0


@dataclass
class BattleTurn(Event):
    TYPE: ClassVar[str] = "battle_turn"
    turn: int = 0
    hp: int = 0
    max_hp: int = 0
    enemy_hp: int = 0
    enemy_max_hp: int = 0
    move: str = ""
    effect: str = ""           # e.g. "x2 super effective"
    plan: str = ""             # the counter planner's pick, when present


@dataclass
class BattleEnd(Event):
    TYPE: ClassVar[str] = "battle_end"
    result: str = ""           # won | lost | fled | ended
    turns: int = 0


@dataclass
class Item(Event):
    TYPE: ClassVar[str] = "item"
    name: str = ""
    action: str = "gained"     # gained | used
    count: int = 1


@dataclass
class Goal(Event):
    TYPE: ClassVar[str] = "goal"
    name: str = ""
    status: str = "current"    # current | done


@dataclass
class Learn(Event):
    TYPE: ClassVar[str] = "learn"
    kind: str = ""             # wall | warp | jump | encounter | interaction
    map: int = 0
    x: int = 0
    y: int = 0
    dir: str = ""
    dest: list[int] | None = None


@dataclass
class Stall(Event):
    TYPE: ClassVar[str] = "stall"
    reason: str = ""
    steps: int = 0


@dataclass
class HumanHold(Event):
    TYPE: ClassVar[str] = "human_hold"
    on: bool = False


TYPES: dict[str, type[Event]] = {c.TYPE: c for c in
                                 (Move, MapChange, Decision, BattleStart, BattleTurn, BattleEnd, Item, Goal, Learn,
                                  Stall, HumanHold)}


def from_dict(d: dict[str, Any]) -> Event | None:
    """Rebuild an event; unknown types, newer schemas and non-dicts give None (a viewer must survive any agent)."""
    if not isinstance(d, dict):
        return None
    cls = TYPES.get(d.get("type", ""))
    if cls is None or not isinstance(d.get("v", EVENT_SCHEMA), int) or d.get("v", EVENT_SCHEMA) > EVENT_SCHEMA:
        return None
    try:
        return cls(**{f.name: d[f.name] for f in fields(cls) if f.name in d})
    except TypeError:
        return None


class EventBus:
    """Bounded ring of events with a monotonically increasing ``seq`` (first event is 1)."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY, clock=time.time) -> None:
        self._buf: deque[Event] = deque(maxlen=max(1, capacity))
        self._seq = 0
        self._clock = clock
        self._lock = threading.Lock()

    def emit(self, ev: Event) -> int:
        with self._lock:
            self._seq += 1
            ev.seq, ev.t = self._seq, self._clock()
            self._buf.append(ev)
            return self._seq

    @property
    def seq(self) -> int:
        return self._seq

    def since(self, seq: int = 0, limit: int = DEFAULT_CAPACITY) -> list[dict[str, Any]]:
        """Events with seq > ``seq`` (oldest first, at most ``limit``), as dicts. A cursor older than the ring gets what remains."""
        with self._lock:
            items = [e for e in self._buf if e.seq > seq][:limit]
        return [e.to_dict() for e in items]
