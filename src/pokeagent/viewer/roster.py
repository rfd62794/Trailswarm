"""Roster rows for the world side panel (pure): one line per agent with swatch colour, goal/stage, HP, level and idle time."""
from __future__ import annotations

from typing import NamedTuple

from pokeagent.viewer.panels import steps
from pokeagent.world.palette import agent_colour


class Row(NamedTuple):
    agent_id: str
    colour: tuple[int, int, int]
    name: str
    stage: str
    hp: int
    max_hp: int
    level: int
    idle_s: float
    state: str

    @property
    def hp_frac(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 0.0

    def text(self) -> str:
        """The one-line form used by the hover/selected tooltip."""
        hp = f"  HP {self.hp}/{self.max_hp}  L{self.level}" if self.max_hp else ""
        return f"{self.name}  {self.stage or '-'}{hp}  idle {fmt_idle(self.idle_s)}"


def fmt_idle(s: float) -> str:
    s = max(0, int(s))
    return f"{s}s" if s < 120 else f"{s // 60}m" if s < 7200 else f"{s // 3600}h"


def fighter(snap) -> tuple[int, int, int]:
    """(hp, max_hp, level) of the lead party member, zeros when unknown."""
    party = snap.screen.party if snap is not None else []
    m = party[0] if party else None
    return (m.hp, m.max_hp, m.level) if m else (0, 0, 0)


def rows(tracks, snapshot_of, state_of, now: float) -> list[Row]:
    """``snapshot_of(id)`` -> AgentSnapshot | None, ``state_of(id)`` -> health state; idle is time since the last move (viewer clock)."""
    out = []
    for t in sorted(tracks, key=lambda t: t.id):
        snap = snapshot_of(t.id)
        hp, mx, lv = fighter(snap)
        stage = (steps.current(snap)[0] if snap is not None else "") or t.goal
        out.append(Row(t.id, agent_colour(t.id), t.id[-8:], stage, hp, mx, lv, now - t.moved_at if t.moved_at else 0.0, state_of(t.id)))
    return out
