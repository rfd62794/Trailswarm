"""Re-validate the library against the party rules: a rule added later still reaches old states.

``revalidate`` re-runs ``party_rules.violations`` on every entry's fingerprint in one pass, then - with every
entry's verdict recomputed - names, for each entry that currently violates a rule, the NEAREST CLEAN ANCESTOR
(the state a regeneration would restart from). Report-only: entries are marked in memory; nothing on disk is
moved, retired or deleted - that is ``states retire``.
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
    """Two passes over ``entries`` (``directory_index`` maps the entry's ``state`` path - or its file name - to
    the fp read fresh from the sidecar). Pass 1 recomputes every verdict so pass 2 picks ancestors from the
    RECOMPUTED verdicts, never the stored ones; every entry that currently violates is marked ``retirable``
    and gets a RETIRABLE line. An entry with no readable sidecar keeps its stored verdict."""
    rep = Report()
    fps = directory_index or {}
    for e in entries:
        fp = fps.get(e.get("state")) or fps.get(Path(e.get("state") or "").name)
        if fp is None:
            continue
        e["violations"] = party_rules.violations(fp, kb)
        e["verdict"] = "violation" if e["violations"] else party_rules.verdict(fp, kb)
        if e["verdict"] != "violation":
            e.pop("retirable", None)
    for e in entries:
        if e.get("verdict") != "violation":
            continue
        e["retirable"] = True
        rep.retirable.append(e)
        anc = _ancestor(e, entries)
        where = f"{anc['name']} ({anc['state']})" if anc else "none"
        rep.lines.append(f"RETIRABLE {e['name']}: {'; '.join(e.get('violations') or ['(recorded)'])}; "
                         f"nearest clean ancestor: {where}")
    return rep
