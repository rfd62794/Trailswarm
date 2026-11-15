"""Rewind frames: the state of a finished run at any step, joined from its own logs.

A run writes one ``transitions.jsonl`` row per press (where the player ended up, facing, text box,
battle flag), one ``decisions.jsonl`` row per pressing decision (behaviour, rule, goal stage) and a
``levels.jsonl`` party snapshot each time the party changed. ``Rewind`` joins them: ``frame(N)`` is
the run at step N, ``track(N)`` the same state in the ``world.model.Track`` shape the World view
draws. Pure code: no emulator, no ROM, no window. Every lookup is by the ``step`` field with a
carry-forward (the row AT the step or the nearest earlier one), never by list position - a run with
transitions but no decisions or levels still plays, with empty strings and an empty party.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass

from pokeagent.review.load import RunData
from pokeagent.world.model import TRAIL, Track


@dataclass(frozen=True)
class PartyRow:
    """One party member; from a ``levels.jsonl`` entry [species, level, exp, hp, max_hp] (party_log.rows)."""

    species: int
    level: int
    hp: int
    max_hp: int


@dataclass(frozen=True)
class Frame:
    """The joined state of the run at one step."""

    step: int
    map: int
    x: int
    y: int
    facing: str
    button: str
    behaviour: str
    rule: str
    outcome: str
    goal_stage: str
    in_battle: bool
    battle_turn: int
    textbox: str
    text: str
    moved: bool
    source: str
    party: tuple[PartyRow, ...]


def _sort(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r.get("step", 0))


def _before(steps: list[int], rows: list[dict], step: int) -> dict | None:
    i = bisect_right(steps, step) - 1
    return rows[i] if i >= 0 else None


def _party(row: dict | None) -> tuple[PartyRow, ...]:
    return tuple(PartyRow(e[0], e[1], e[3], e[4])
                 for e in (row or {}).get("party") or [] if len(e) >= 5)


class Rewind:
    """Step-indexed playback over one run's rows. ``from_run`` builds sorted step arrays once;
    ``frame``/``track`` are bisects, never scans (an 8,000-step run must not scan per call)."""

    def __init__(self, transitions: list[dict], decisions: list[dict], levels: list[dict]) -> None:
        self._t, self._d, self._l = _sort(transitions), _sort(decisions), _sort(levels)
        self._ts = [r.get("step", 0) for r in self._t]
        self._ds = [r.get("step", 0) for r in self._d]
        self._ls = [r.get("step", 0) for r in self._l]
        self._steps = sorted(set(self._ts))
        # (step, from, to) per press that moved the player - track()'s trail comes from these
        self._moves = [(r.get("step", 0), tuple(r.get("from") or ()), tuple(r.get("to") or ()))
                       for r in self._t if r.get("moved")]
        self._move_steps = [m[0] for m in self._moves]

    @classmethod
    def from_run(cls, data: RunData) -> "Rewind":
        """Index a loaded run's three row lists by their ``step`` field, once."""
        return cls(data.transitions, data.decisions, data.levels)

    @property
    def first_step(self) -> int:
        return self._steps[0] if self._steps else 0

    @property
    def last_step(self) -> int:
        return self._steps[-1] if self._steps else 0

    def __len__(self) -> int:
        """Distinct steps that have a transitions row."""
        return len(self._steps)

    def frame(self, step: int) -> Frame:
        """The run at ``step``; below ``first_step``/above ``last_step`` clamps to the ends."""
        s = min(max(step, self.first_step), self.last_step) if self._steps else step
        t = _before(self._ts, self._t, s) or {}
        d = _before(self._ds, self._d, s) or {}
        to = t.get("to") or (-1, 0, 0)
        return Frame(
            step=s, map=to[0], x=to[1], y=to[2],
            facing=t.get("facing", "DOWN"), button=t.get("button", ""),
            behaviour=d.get("behaviour", ""), rule=d.get("rule", ""),
            outcome=d.get("outcome", ""), goal_stage=d.get("goal_stage", ""),
            in_battle=bool(t.get("battle_flag", 0)), battle_turn=t.get("battle_turn", 0),
            textbox=t.get("textbox", ""), text=t.get("text", ""),
            moved=bool(t.get("moved")), source=t.get("source", ""),
            party=_party(_before(self._ls, self._l, s)),
        )

    def track(self, step: int, agent_id: str = "rewind", trail: int | None = None) -> Track:
        """The frame as a ``world.model.Track``: path is the positions of the moved presses up to
        the step (oldest first, capped at ``trail``/``TRAIL``), ``prev`` where the last move came
        from, ``goal`` the frame's goal stage. ``battle``/``hold``/``stalled`` stay at defaults."""
        f = self.frame(step)
        cap = trail or TRAIL
        end = bisect_right(self._move_steps, f.step)
        moves = self._moves[max(0, end - cap):end]
        tr = Track(agent_id, map=f.map, x=f.x, y=f.y, facing=f.facing, step=f.step,
                   prev=(moves[-1][1] or None) if moves else None, goal=f.goal_stage)
        tr.path = deque((m[2] for m in moves), maxlen=cap)
        return tr
