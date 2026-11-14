"""Re-validate the library against the party rules: a rule added later still reaches old states.

``revalidate`` re-runs ``party_rules.violations`` on every entry's fingerprint and names, for each entry that
turns clean -> violation, the NEAREST CLEAN ANCESTOR (the state a regeneration would restart from). Report-only:
entries are marked in memory; nothing on disk is moved, retired or deleted - that is ``states retire``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pokeagent import party_rules
from pokeagent.goals import GOALS
from pokeagent.segment_names import state_goal


@dataclass
class Report:
    """revalidate's findings: the entries that turned retirable and their RETIRABLE print lines."""
    retirable: list = field(default_factory=list)
    lines: list = field(default_factory=list)


def _goal_index(e: dict) -> int:
    g = state_goal((e.get("name") or "").removesuffix(".best"))
    if g in GOALS:
        return GOALS.index(g)
    seg = (e.get("segment") or "").split("@", 1)[0]
    return GOALS.index(seg) if seg in GOALS else len(GOALS)


def _ancestor(e: dict, entries: list) -> dict | None:
    """The nearest clean ancestor through ``parent`` links, else the latest clean entry of the same tier with a
    smaller GOALS index (the clean checkpoint a regeneration would start from)."""
    by_name = {Path(x["state"]).name: x for x in entries}
    by_name.update({x["name"]: x for x in entries})
    seen, cur = set(), e
    while (parent := cur.get("parent")) and parent not in seen:
        seen.add(parent)
        nxt = by_name.get(parent) or by_name.get(Path(str(parent)).stem)
        if nxt is None:
            break
        if nxt.get("verdict") == "clean":
            return nxt
        cur = nxt
    cands = [x for x in entries if x is not e and x.get("verdict") == "clean" and x.get("tier") == e.get("tier")
             and _goal_index(x) < _goal_index(e)]
    return max(cands, key=lambda x: x.get("created") or "", default=None)


def revalidate(entries: list, kb: dict | None, directory_index: dict | None) -> Report:
    """Re-run ``violations`` on every entry's fingerprint (``directory_index`` maps the entry's ``state`` path -
    or its file name - to the fp read fresh from the sidecar). An entry turning clean -> violation is marked
    ``retirable: true`` and its RETIRABLE line is added to the report."""
    rep = Report()
    fps = directory_index or {}
    for e in entries:
        fp = fps.get(e.get("state")) or fps.get(Path(e.get("state") or "").name)
        if fp is None:
            continue
        new_vio = party_rules.violations(fp, kb)
        if e.get("verdict") != "clean" or not new_vio:
            continue
        e["verdict"], e["violations"], e["retirable"] = "violation", new_vio, True
        rep.retirable.append(e)
        anc = _ancestor(e, entries)
        where = f"{anc['name']} ({anc['state']})" if anc else "none"
        rep.lines.append(f"RETIRABLE {e['name']}: {'; '.join(new_vio)}; nearest clean ancestor: {where}")
    return rep
