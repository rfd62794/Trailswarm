"""Where to catch a Cut learner: pick the nearest wild grass map whose table holds a Cut-compatible species.

Pure functions over the drained tables: ``hm`` is the kb/hm_compat.json table ({hm: species names}), ``wild_by_map``
the kb/rom_tables.json wild table ({map id: {"grass_rate", "grass": [[level, species]x10], ...}}). Both are ROM-derived
and gitignored, so callers pass them in; ``party_names`` turns RAM species ids into names via name_of_internal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pokeagent.knowledge.encounters import map_name, slot_chances
from pokeagent.magikarp import party_species

LEARNER_STEP_CAP = 6000      # steps on the stage without a Cut-capable member before the goal is settled for this run (named; tune from runs)

_NAMES_JSON = Path(__file__).resolve().parents[1] / "atlas" / "map_names.json"


@lru_cache(maxsize=1)
def _names() -> dict[int, str]:
    """Map id -> display name ("Route 6"), from the committed ROM map-name table; hex fallback."""
    try:
        raw = json.loads(_NAMES_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    return {int(k): v.replace("_", " ").title() for k, v in raw.items()}


@dataclass(frozen=True)
class LearnerTarget:
    """Where to hunt the learner: grass ``rate``/256 per step, ``chance`` of ``species`` per encounter."""

    map: int
    name: str
    species: str
    levels: tuple[int, int]
    chance: float
    rate: int


def cut_capable(party_names, hm: dict | None) -> bool:
    """Any party species name can learn CUT under the kb/hm_compat table; no table -> cannot judge -> False."""
    can = (hm or {}).get("cut") or ()
    return any(n in can for n in (party_names or ()))


def party_names(emu, kb: dict | None) -> list[str] | None:
    """Party species names via kb name_of_internal (the same lookup catch.py uses); None when there is no ROM data."""
    if not kb:
        return None
    names = kb.get("name_of_internal") or {}
    return [names.get(str(s), str(s)) for s in party_species(emu)]


def _best_slot_species(grass: list, can) -> tuple[float, str, tuple[int, int]] | None:
    """The likeliest Cut-compatible species in a grass table: (chance per encounter, species, (lo, hi) levels)."""
    chances = slot_chances()
    best = None
    for sp in {n for _, n in grass if n in can}:
        idx = [i for i, (_, n) in enumerate(grass) if n == sp]
        chance = sum(chances[i] for i in idx)
        lv = (min(grass[i][0] for i in idx), max(grass[i][0] for i in idx))
        if best is None or chance > best[0] or (chance == best[0] and sp < best[1]):
            best = (chance, sp, lv)
    return best


def pick_target(here_map: int, known_maps, hm: dict, wild_by_map: dict, distance=None) -> LearnerTarget | None:
    """The nearest grass map holding a Cut-compatible wild species. Candidates: every map in ``wild_by_map`` whose
    GRASS table has one (water-only species like Tentacool/Krabby/Kingler need Surf: not candidates in v1).
    weight = the species' chance per encounter x grass rate. Prefer maps in ``known_maps`` (the learned world,
    runs/maps.json keys) and the smallest ``distance(here_map, map)`` (default: abs difference of the map ids;
    the caller may pass a graph-path length); ties go to the higher weight, then the lower map id.
    None when there is no candidate (e.g. no tables)."""
    dist = distance or (lambda a, b: abs(a - b))
    known = {int(m) for m in (known_maps or ())}
    can = set((hm or {}).get("cut") or ())
    cands = []
    for m, row in (wild_by_map or {}).items():
        row = row or {}
        best = _best_slot_species(row.get("grass") or [], can)
        if best and row.get("grass_rate"):
            chance, sp, levels = best
            m = int(m)
            cands.append(LearnerTarget(m, _names().get(m, map_name(m)), sp, levels, round(chance, 3), row["grass_rate"]))
    cands.sort(key=lambda t: (t.map not in known, dist(here_map, t.map), -t.chance * t.rate, t.map))
    return cands[0] if cands else None
