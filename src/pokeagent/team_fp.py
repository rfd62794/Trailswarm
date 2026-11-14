"""Team fingerprints: pure functions over a fingerprint's ``team`` list.

``fp["team"]`` (statefp) records ``{"species", "level", "moves", "hp", "max_hp", "ot_id", "exp"}`` per party slot.
From it a library can name the build (the team's shape: species lines and rounded levels, moves NOT included),
what HMs it covers, and where a member plausibly came from. Names resolve through the kb tables; a caller passes
``kb`` explicitly (``kb/rom_tables.json``) and unknowns stay unknown - nothing here guesses.
"""
from __future__ import annotations

from pokeagent.explorer import catch_list
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.team_value import EVOLUTIONS

LEVEL_ROUND = 5


def _name(species_id, kb) -> str | None:
    n = table(kb, "name_of_internal").get(str(species_id))
    return n if isinstance(n, str) and n else None


def _line_of_name(name: str) -> str:
    """The base species of ``name``'s evolution line, walking EVOLUTIONS backwards; unknown: ``name`` itself."""
    cur = name
    while (prev := next((s for s, (into, _lv) in EVOLUTIONS.items() if into == cur), None)) is not None:
        cur = prev
    return cur


def species_line(species_id, kb) -> str:
    """The base species of the member's line (WEEDLE for WEEDLE/KAKUNA/BEEDRILL); unknown species: its own name."""
    return _line_of_name(_name(species_id, kb) or str(species_id))


def build_key(fp: dict | None, kb) -> str | None:
    """The team's shape: members sorted by (line, rounded level) as ``LINE:L<level rounded down to 5>`` joined
    with ``|``. Moves are NOT part of a build. None when ``fp`` has no ``team`` (team unknown)."""
    team = (fp or {}).get("team")
    if team is None:
        return None
    shaped = sorted((species_line(m.get("species"), kb), int(m.get("level") or 0) // LEVEL_ROUND)
                    for m in team if isinstance(m, dict))
    return "|".join(f"{line}:L{band * LEVEL_ROUND}" for line, band in shaped)


def moves_of(member: dict, kb) -> frozenset[str]:
    """The member's move names via the kb's ``moves`` table (ids the table does not name are dropped)."""
    moves = table(kb, "moves")
    return frozenset(row["name"] for i in member.get("moves") or ()
                     if (row := moves.get(str(i))) and row.get("name"))


def hm_capable(fp: dict | None, kb, hm_table) -> frozenset[str]:
    """The HMs (cut, flash, surf, strength) some member can learn (``hm_table`` = the shape
    ``knowledge.hm_compat.load()`` returns) or already knows by move name. ``hm_table=None``: empty set."""
    if not hm_table:
        return frozenset()
    out: set[str] = set()
    for m in (fp or {}).get("team") or ():
        if not isinstance(m, dict):
            continue
        name, known = _name(m.get("species"), kb), moves_of(m, kb)
        out |= {hm for hm, mv in catch_list.HM_MOVE.items()
                if name in (hm_table.get(hm) or ()) or mv in known}
    return frozenset(out)


def provenance(member: dict, kb, starter_species=None) -> str:
    """``starter`` when the member's line equals ``starter_species``'s line, ``wild-caught-harden-only`` when
    catch_list.wild_never_catch is true, else ``unknown``. Best effort: never guessed beyond these three."""
    if starter_species is not None:
        sline = (species_line(starter_species, kb) if str(starter_species).isdigit()
                 else _line_of_name(str(starter_species)))
        if species_line(member.get("species"), kb) == sline:
            return "starter"
    if catch_list.wild_never_catch(_name(member.get("species"), kb), moves_of(member, kb)):
        return "wild-caught-harden-only"
    return "unknown"
