"""Where to catch X, and where to train against Y, from the drained wild encounter tables."""
from __future__ import annotations

from pokeagent.knowledge.kb import table

# Map names for the maps the campaign visits (ids verified in docs/KNOWLEDGE.md); others print as 0xNN.
MAP_NAMES = {0x0C: "Route 1", 0x0D: "Route 2", 0x0E: "Route 3", 0x0F: "Route 4", 0x21: "Route 22", 0x23: "Route 24", 0x24: "Route 25",
             0x33: "Viridian Forest", 0x3B: "Mt Moon 1F", 0x3C: "Mt Moon B1F", 0x3D: "Mt Moon B2F"}


def map_name(m: int) -> str:
    return MAP_NAMES.get(m, f"0x{m:02X}")


def slot_chances() -> list[float]:
    """The 10 grass slots' probabilities (Gen 1: 51/256, 51, 39, 25, 25, 25, 13, 13, 11, 3 of 256)."""
    return [x / 256 for x in (51, 51, 39, 25, 25, 25, 13, 13, 11, 3)]


def where_to_catch(species: str, kb: dict | None = None) -> list[dict]:
    """Every map (and grass/water) where `species` can appear: [{"map", "name", "kind", "levels": (lo, hi), "chance"}], likeliest first."""
    out = []
    for m, row in table(kb, "wild_by_map").items():
        for kind in ("grass", "water"):
            slots = row.get(kind) or []
            hits = [(i, lv) for i, (lv, n) in enumerate(slots) if n.upper() == species.upper()]
            if hits:
                chance = sum(slot_chances()[i] for i, _ in hits)
                out.append({"map": int(m), "name": map_name(int(m)), "kind": kind, "levels": (min(lv for _, lv in hits), max(lv for _, lv in hits)),
                            "chance": round(chance, 3), "rate": row[f"{kind}_rate"]})
    return sorted(out, key=lambda r: -r["chance"] * r["rate"])


def species_on(map_id: int, kb: dict | None = None) -> dict[str, tuple[int, int, float]]:
    """{species: (min level, max level, chance per encounter)} for a map's grass: what to train against there."""
    row = table(kb, "wild_by_map").get(map_id) or table(kb, "wild_by_map").get(str(map_id)) or {}
    res: dict[str, list] = {}
    for i, (lv, n) in enumerate(row.get("grass") or []):
        r = res.setdefault(n, [lv, lv, 0.0]); r[0] = min(r[0], lv); r[1] = max(r[1], lv); r[2] += slot_chances()[i]
    return {n: (a, b, round(c, 3)) for n, (a, b, c) in res.items()}


def train_vs(species: str, kb: dict | None = None) -> list[str]:
    """Human lines: where to meet `species`, with levels (the map to grind on to face it)."""
    return [f"{r['name']} {r['kind']}: L{r['levels'][0]}-{r['levels'][1]} ({r['chance'] * 100:.0f}% per encounter)" for r in where_to_catch(species, kb)]


# The map the agent grinds on before each stage (planner: Route 1 for Brock, Route 3 for Mt Moon, Route 24 for Misty).
TRAIN_MAP = {"beat_brock": 0x0C, "to_mt_moon": 0x0E, "beat_misty": 0x23}


def level_ceiling(goal: str, kb: dict | None = None) -> int | None:
    """Highest wild grass level on the goal's training route, or None when the route or its table is unknown."""
    m = TRAIN_MAP.get(goal)
    species = species_on(m, kb) if m is not None else {}
    return max((hi for _, hi, _ in species.values()), default=None)
