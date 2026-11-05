"""Agent snapshot contract v1: what every agent publishes and every viewer reads.

Stdlib dataclasses with ``to_dict`` / ``from_dict``. ``from_dict`` ignores unknown keys, fills
missing keys with defaults, and raises ``ValueError`` only for a missing ``agent_id`` or a newer
schema version than this module understands.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field, fields
from typing import Any

SCHEMA_VERSION = 1
DRIVERS = ("explorer", "rl", "human", "claude")
MAX_RECENT = 20


@dataclass
class Thinking:
    want: str = ""
    plan: str = ""
    blocker: str = ""
    driver: str = ""
    rule: str = ""
    button: str = ""
    result: str = ""
    confidence: float | None = None


@dataclass
class Goal:
    id: str = ""
    name: str = ""
    status: str = "ahead"  # "done" | "current" | "ahead"
    steps: int | None = None


@dataclass
class Segment:
    id: str = ""
    name: str = ""
    steps: int = 0
    record: int | None = None


@dataclass
class Sees:
    rows: list[str] = field(default_factory=list)
    mode: str = "overworld"  # | "battle" | "menu"


@dataclass
class PartyMon:
    species: str = ""
    level: int = 0
    hp: int = 0
    max_hp: int = 0


@dataclass
class Screen:
    box_text: str = ""
    in_battle: bool = False
    party: list[PartyMon] = field(default_factory=list)
    money: int | None = None
    bag_summary: str = ""


@dataclass
class Event:
    step: int = 0
    driver: str = ""
    text: str = ""


@dataclass
class AgentSnapshot:
    agent_id: str
    kind: str = ""  # "explorer" | "rl" | "hybrid" | other free text
    v: int = SCHEMA_VERSION
    state: str = "running"  # running | paused | stopped | done
    stop_reason: str = ""
    step: int = 0
    segment: Segment = field(default_factory=Segment)
    goals: list[Goal] = field(default_factory=list)
    thinking: Thinking = field(default_factory=Thinking)
    drivers: dict[str, int] = field(default_factory=lambda: {d: 0 for d in DRIVERS})
    drivers_available: list[str] = field(default_factory=list)
    recent: list[Event] = field(default_factory=list)  # newest last
    sees: Sees = field(default_factory=Sees)
    screen: Screen = field(default_factory=Screen)
    human_hold: bool = False
    frame_slot: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recent"] = d["recent"][-MAX_RECENT:]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSnapshot":
        if not isinstance(data, dict) or not data.get("agent_id"):
            raise ValueError("snapshot missing agent_id")
        v = data.get("v", SCHEMA_VERSION)
        if not isinstance(v, int) or v > SCHEMA_VERSION:
            raise ValueError(f"unsupported snapshot version {v!r}")
        kw: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            val = data[f.name]
            if f.name in _NESTED:
                val = _build(_NESTED[f.name], val)
            elif f.name in _LISTS:
                val = [_build(_LISTS[f.name], x) for x in (val or [])]
            kw[f.name] = val
        snap = cls(**kw)
        snap.recent = snap.recent[-MAX_RECENT:]
        snap.drivers = {**{d: 0 for d in DRIVERS}, **(snap.drivers or {})}
        return snap


def _build(klass, data):
    """Build a dataclass from a dict, ignoring unknown keys (Screen.party handled specially)."""
    if not isinstance(data, dict):
        return klass()
    kw = {f.name: data[f.name] for f in fields(klass) if f.name in data}
    if klass is Screen and "party" in kw:
        kw["party"] = [_build(PartyMon, p) for p in (kw["party"] or [])]
    return klass(**kw)


_NESTED = {"segment": Segment, "thinking": Thinking, "sees": Sees, "screen": Screen}
_LISTS = {"goals": Goal, "recent": Event}


class DriverWindow:
    """Rolling count of which driver made each of the last ``maxlen`` presses."""

    def __init__(self, maxlen: int = 100) -> None:
        self._win: deque[str] = deque(maxlen=maxlen)

    def add(self, driver: str) -> None:
        self._win.append(driver)

    def counts(self) -> dict[str, int]:
        out = {d: 0 for d in DRIVERS}
        for d in self._win:
            out[d] = out.get(d, 0) + 1
        return out
