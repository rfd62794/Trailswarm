"""Moments: the steps of a finished run worth jumping to.

``map_change`` - a transitions row whose ``from`` map differs from its ``to`` map.
``battle_start`` / ``battle_end`` - the battle flag going 0 -> nonzero / nonzero -> 0 between
consecutive frames. ``goal`` - a decisions row with ``outcome == "goal"``. ``level_up`` - a species
whose highest level rose between two consecutive levels rows (matched by species id, not slot: the
party is reordered often). Labels carry ids only - names are a later slice.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.review.load import RunData
from pokeagent.rewind.frames import Rewind


@dataclass(frozen=True)
class Moment:
    step: int
    kind: str
    label: str


def _level_ups(rows: list[dict]) -> list[Moment]:
    out = []
    for prev, cur in zip(rows, rows[1:]):
        def hi(row: dict) -> dict[int, int]:  # species -> highest level in this row's party
            h: dict[int, int] = {}
            for e in row.get("party") or []:
                if len(e) >= 2:
                    h[e[0]] = max(h.get(e[0], 0), e[1])
            return h
        before = hi(prev)
        for sp, lv in hi(cur).items():
            if sp in before and lv > before[sp]:
                out.append(Moment(cur.get("step", 0), "level_up",
                                  f"species {sp}: L{before[sp]} -> L{lv}"))
    return out


def moments(rw: Rewind, data: RunData) -> list[Moment]:
    """Every detected moment of the run, sorted by step."""
    out: list[Moment] = []
    for t in data.transitions:
        fr, to = t.get("from") or [], t.get("to") or []
        if fr and to and fr[0] != to[0]:
            out.append(Moment(t.get("step", 0), "map_change", f"map {fr[0]} -> {to[0]}"))
    prev = False
    for step in range(rw.first_step, rw.last_step + 1):
        cur = rw.frame(step).in_battle
        if cur != prev:
            out.append(Moment(step, "battle_start" if cur else "battle_end", ""))
        prev = cur
    out += [Moment(d.get("step", 0), "goal", d.get("goal_stage", ""))
            for d in data.decisions if d.get("outcome") == "goal"]
    out += _level_ups(data.levels)
    out.sort(key=lambda m: m.step)
    return out
