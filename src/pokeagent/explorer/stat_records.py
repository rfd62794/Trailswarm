"""Stats awareness bookkeeping in map memory: catch keep-best records and per-map stat exp yield.

Report-only: nothing here moves a mon or changes a decision. ``data`` is ``ctx.mem.data``.
"""
from __future__ import annotations

from pokeagent.explorer.stats import dv_total, dvs
from pokeagent.ramstructs import PartyMon

MAX_RECORDS = 60


def record_catch(data: dict, party: list[PartyMon], species: int, step: int) -> dict | None:
    """After a catch of ``species``: store every party mon of that species with its DVs, and name
    the best set (highest DV total; ties keep the earlier slot). Returns the species record, or None
    when no such mon is in the party (it went to a box: DVs unreadable until withdrawn)."""
    mons = [(i, m) for i, m in enumerate(party) if m.species == species]
    if not mons:
        return None
    rows = [{"slot": i, "level": m.level, "dvs": dvs(m), "total": dv_total(dvs(m)), "ot_id": m.ot_id} for i, m in mons]
    best = max(rows, key=lambda r: (r["total"], -r["slot"]))
    rec = {"species": species, "mons": rows, "prefer_slot": best["slot"], "duplicate": len(rows) > 1, "step": step}
    book = data.setdefault("dv_records", [])
    book[:] = [r for r in book if r.get("species") != species] + [rec]
    del book[:-MAX_RECORDS]
    return rec


def note_stat_exp(training: dict, stat_exp_total: int, prev_total: int | None) -> None:
    """Add the stat exp gained since the previous press to this map's training record (mutates it)."""
    if prev_total is not None and stat_exp_total > prev_total:
        training["stat_exp"] = training.get("stat_exp", 0) + stat_exp_total - prev_total


def stat_exp_per_step(training: dict) -> float:
    """Training preference score for a map: stat exp gained per step spent there."""
    steps = training.get("steps", 0)
    return training.get("stat_exp", 0) / steps if steps else 0.0
