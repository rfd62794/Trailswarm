"""Organic envelope: the per-stage maxima organic states actually reached, from their fingerprints.

A legality-clean state can still be unreachable (a L45 lead where no organic run got past L38). ``build`` scans the
``.fp.json`` sidecars of organic states (``statefp.lineage`` organic: no ``lineage`` key and no ``synthetic`` flag) in
the given state dirs and keeps, per stage, the maxima a fingerprint carries: lead (max level over the party rows),
party size, money, badges, bag_slots, heal_items, plus the set of respawn town ids seen. Stage key: the checkpoint's
stem when it is a ladder goal (goals.GOALS), else ``badges:<n>``. The fingerprint has no full bag, so "first-seen
items" is NOT buildable from it and is deliberately left out.
"""
from __future__ import annotations

import re
from pathlib import Path

from pokeagent import statefp
from pokeagent.goals import GOALS

_MAXIMA = ("lead", "party", "money", "badges", "bag_slots", "heal_items")


def stage_key(state_name: str, fp: dict) -> str:
    """The envelope stage a state belongs to: its stem when it is a ladder goal, else ``badges:<n>``."""
    stem = re.split(r"[.@]", Path(state_name).name)[0]
    return stem if stem in GOALS else f"badges:{fp.get('badges', 0)}"


def _organic(fp: dict | None) -> bool:
    return bool(fp) and statefp.lineage_of(fp) == "organic"


def _row(fp: dict) -> dict:
    party = fp.get("party") or []
    return {"lead": max((m[1] for m in party), default=0), "party": len(party),
            "money": fp.get("money", 0), "badges": fp.get("badges", 0),
            "bag_slots": fp.get("bag_slots", 0), "heal_items": fp.get("heal_items", 0)}


def build(dirs) -> dict:
    """``{stage: {lead, party, money, badges, bag_slots, heal_items, respawns}}`` over every organic ``*.state`` in
    ``dirs`` (pure JSON in, JSON out, deterministic)."""
    env: dict[str, dict] = {}
    for d in dirs:
        d = Path(d)
        for p in sorted(d.glob("*.state"), key=lambda p: p.name) if d.is_dir() else []:
            fp = statefp.read(p)
            if not _organic(fp):
                continue
            stage = env.setdefault(stage_key(p.name, fp), {k: 0 for k in _MAXIMA} | {"respawns": []})
            row = _row(fp)
            for k in _MAXIMA:
                stage[k] = max(stage[k], row[k])
            if isinstance(fp.get("respawn"), int) and fp["respawn"] not in stage["respawns"]:
                stage["respawns"] = sorted(stage["respawns"] + [fp["respawn"]])
    return env


def respawns_seen(env: dict) -> set[int]:
    """Respawn town ids any organic state in the envelope carries (edit_class: a respawn edit to a town an organic
    run actually respawned at can be organic_equivalent)."""
    return {r for stage in env.values() for r in stage.get("respawns", [])}


def within_envelope(fp: dict, stage: str, env: dict, slack_levels: int = 3,
                    slack_money: float = 0.20) -> tuple[bool, list[str]]:
    """Does the fingerprint fit inside what organic runs reached at this stage? An unknown stage cannot refuse."""
    e = env.get(stage)
    if e is None:
        return True, [f"no organic data for stage {stage}"]
    row = _row(fp)
    reasons = []
    if fp.get("party") is not None and row["lead"] > e["lead"] + slack_levels:
        reasons.append(f"lead L{row['lead']} > envelope max L{e['lead']} + {slack_levels}")
    if "money" in fp and row["money"] > e["money"] * (1 + slack_money):
        reasons.append(f"money {row['money']:,} > {e['money']:,} * {1 + slack_money:g}")
    for k, label in (("party", "party size"), ("badges", "badges"), ("bag_slots", "bag slots"),
                     ("heal_items", "heal items")):
        if k in fp and row[k] > e[k]:
            reasons.append(f"{label} {row[k]} > envelope max {e[k]}")
    return not reasons, reasons
