"""RAM trust tiers: how much a ram_map.json row may be trusted, and the rules that keep
``trust`` and the stored ``verified`` boolean agreeing.

Tiers: ``sym`` (a pokered label; location assumed correct, nothing has contradicted it),
``verified`` (a ROM check or ramlab replay asserts it; ``evidence`` names which), ``caveat``
(known stale or valid only in some states; ``note`` carries a clause starting ``valid when``,
and the row keeps whatever ``verified`` it had), and ``discovered`` (found by
tools/ram_probe.py, not in pokered; ``source`` is ``ram_probe <run id>`` and ram_lookup's
``is_usable`` withholds it unless opted in). ``verified`` stays a stored boolean: every reader
of the old file keeps working, and a row without ``trust`` still loads (verified -> verified,
else sym).
"""
from __future__ import annotations

TIERS = ("sym", "verified", "caveat", "discovered")


def tier_of(row: dict) -> str:
    """The row's tier: the stored ``trust`` when present, else derived from ``verified``."""
    t = row.get("trust")
    if t:
        return t
    return "verified" if row.get("verified") else "sym"


def validate(rows: list[dict]) -> list[str]:
    """Problems in the rows: an unknown tier, a caveat without a 'valid when' clause, a
    discovered row with no evidence or a true verified flag, or trust disagreeing with the
    stored verified flag."""
    problems = []
    for r in rows:
        t, name = tier_of(r), r.get("name", "?")
        if t not in TIERS:
            problems.append(f"{name}: unknown trust {t!r}")
            continue
        if t == "caveat":
            if "valid when" not in r.get("note", ""):
                problems.append(f"{name}: caveat without 'valid when' in note")
        elif t == "verified":
            if not r.get("verified") or not r.get("evidence"):
                problems.append(f"{name}: trust verified but verified/evidence missing")
        elif t == "sym":
            if r.get("verified"):
                problems.append(f"{name}: trust sym but verified is true")
        elif t == "discovered":
            if r.get("verified"):
                problems.append(f"{name}: discovered but verified is true")
            if not r.get("evidence"):
                problems.append(f"{name}: discovered without evidence")
    return problems


def no_downgrade(prior_rows: list[dict], new_rows: list[dict]) -> list[str]:
    """Names whose tier fell to ``sym`` from verified/caveat, or whose verified flag went
    true -> false. verified -> caveat is not a downgrade."""
    prior = {r["name"]: r for r in prior_rows}
    out = []
    for r in new_rows:
        p = prior.get(r["name"])
        if p is None:
            continue
        if tier_of(p) in ("verified", "caveat") and tier_of(r) == "sym":
            out.append(r["name"])
        elif p.get("verified") and not r.get("verified"):
            out.append(r["name"])
    return out


def promote_verified(row: dict, evidence: str) -> dict:
    """Promote a row to ``verified``. Refuses an empty evidence string and a caveat row
    (a caveat keeps its verified flag; fix the 'valid when' note, not the tier)."""
    if not evidence:
        raise ValueError(f"{row.get('name')}: promote_verified needs an evidence string")
    if tier_of(row) == "caveat":
        raise ValueError(f"{row.get('name')}: a caveat row is not promoted")
    row["verified"] = True
    row["evidence"] = evidence
    row["trust"] = "verified"
    return row
