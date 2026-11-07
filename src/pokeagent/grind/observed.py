"""Sufficient statistics of the battle log per (starter, level band, map, goal): they fold in new battles without a re-read.

battles.jsonl has no lead species (``you``[0] reads 0): the starter comes from newer ``party_before``, else the run's
meta.json. Real XP comes from ``exp_gained`` (feat/xp-level-logging), else runs/xp_estimates.jsonl, else None.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

BAND = 4
FIELDS = ("n", "wins", "blackouts", "presses", "hp_lost", "xp_sum", "xp_n")


def band(level: int) -> int:
    return level // BAND * BAND


@dataclass
class Obs:
    n: int = 0
    wins: int = 0
    blackouts: int = 0
    presses: int = 0
    hp_lost: float = 0.0   # summed fraction of max HP
    xp_sum: float = 0.0    # real or estimated XP, over xp_n battles that have it
    xp_n: int = 0

    def add(self, rec: dict, xp: float | None = None) -> None:
        self.n += 1
        won = bool(rec.get("won"))
        self.wins += won
        self.blackouts += (not won) and not rec.get("fled")  # lost and not standing: a warp home
        self.presses += int(rec.get("presses") or 0)
        hp_end = rec.get("hp_end") or [0, 1]
        first = (rec.get("turns") or [{}])[0].get("hp_you")
        if first is not None and hp_end[1]:
            self.hp_lost += max(0, first - hp_end[0]) / hp_end[1]
        if xp is not None:
            self.xp_sum += xp
            self.xp_n += 1

    def merge(self, o: "Obs") -> "Obs":
        return Obs(*(getattr(self, f) + getattr(o, f) for f in FIELDS))

    def to_list(self) -> list:
        return [getattr(self, f.name) for f in fields(self)]


def key_str(k: tuple) -> str:
    return "|".join("" if x is None else str(x) for x in k)


def key_of(s: str) -> tuple:
    sp, b, m, goal = s.split("|")
    return (sp or None, int(b), int(m), goal)


def lead_of(rec: dict, run_meta: dict, name_of: dict | None = None) -> tuple[str | None, int]:
    """(lead species name or None, lead level) of a battle record."""
    pb = rec.get("party_before")
    if pb:
        sp = (name_of or {}).get(str(pb[0][0]))
        return (sp or run_meta.get("starter") or "").upper() or None, int(pb[0][1])
    return (run_meta.get("starter") or "").upper() or None, int((rec.get("you") or [0, 0])[1])


def fold(stats: dict, rec: dict, run_meta: dict, name_of=None, estimates: dict | None = None) -> None:
    """Add one battle to ``stats`` ({(starter, band, map, goal): Obs}), plus its pooled (starter None) twin. Wild only."""
    if rec.get("kind") != 1 or "map" not in rec:
        return
    sp, lvl = lead_of(rec, run_meta, name_of)
    if lvl < 2:
        return
    xp = rec.get("exp_gained")
    if isinstance(xp, (list, tuple)):  # party_log writes one gain per member: the lead is slot 0
        xp = xp[0] if xp else None
    if xp is None and estimates:
        xp = estimates.get((rec.get("run"), rec.get("start")))
    goal = str(run_meta.get("stop_at_goal") or "")
    for s in {sp, None}:
        stats.setdefault((s, band(lvl), int(rec["map"]), goal), Obs()).add(rec, xp)


def pooled(stats: dict, starter: str | None, lvl: int, m: int) -> Obs:
    """All goals merged for (starter, band(lvl), map)."""
    out = Obs()
    for (s, b, mm, _g), o in stats.items():
        if s == starter and b == band(lvl) and mm == m:
            out = out.merge(o)
    return out


def load_estimates(path: Path) -> dict:
    """{(run, start): xp} from runs/xp_estimates.jsonl (fields: run, start, exp_estimate, falling back to exp_gained|xp_estimate); {} if absent."""
    out: dict = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                v = next((r[k] for k in ("exp_estimate", "exp_gained", "xp_estimate") if r.get(k) is not None), None)
                if v is not None:
                    out[(r.get("run"), r.get("start"))] = float(v)
            except (ValueError, AttributeError):
                continue
    except OSError:
        pass
    return out
