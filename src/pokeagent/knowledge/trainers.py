"""Trainer parties from the ROM: "what does Brock use", and the pre-gym type matchup of our team (report only)."""
from __future__ import annotations

from pokeagent.knowledge.kb import table

# The campaign's bosses: goal -> (trainer class, party number, gym map id). Parties come from the drained data.
GYM_BOSSES = {"beat_brock": ("BROCK", 1, 0x36), "beat_misty": ("MISTY", 1, 0x41)}
MT_MOON_MAPS = (0x3B, 0x3C, 0x3D)


def party_of(trainer_class: str, number: int = 1, kb: dict | None = None) -> list[tuple[int, str]]:
    """[(level, species)] of a trainer class's party (1-based party number); [] when unknown."""
    parties = table(kb, "trainers").get(trainer_class.upper()) or []
    return [(int(lv), n) for lv, n in parties[number - 1]] if 0 < number <= len(parties) else []


def what_does_use(name: str, kb: dict | None = None) -> str:
    """'BROCK: GEODUDE L12, ONIX L14' for a class (all its parties are joined with ' | ')."""
    parties = table(kb, "trainers").get(name.upper()) or []
    return f"{name.upper()}: " + " | ".join(", ".join(f"{n} L{lv}" for lv, n in p) for p in parties) if parties else f"{name.upper()}: unknown"


def trainers_on(map_id: int, kb: dict | None = None) -> list[dict]:
    """The trainers placed on a map: [{"class", "party", "x", "y", "mons": [(level, species)]}]."""
    rows = table(kb, "map_trainers").get(map_id) or table(kb, "map_trainers").get(str(map_id)) or []
    return [{**r, "mons": party_of(r["class"], r["party"], kb)} for r in rows]


def boss_party(goal: str, kb: dict | None = None) -> list[tuple[int, str]]:
    """The party of the gym leader behind `goal` (beat_brock, beat_misty), else []."""
    if goal not in GYM_BOSSES:
        return []
    cls, num, _ = GYM_BOSSES[goal]
    return party_of(cls, num, kb)


def strongest_on_mt_moon(kb: dict | None = None) -> list[tuple[int, str]]:
    """The party with the highest total level among the trainers on Mt Moon 1F / B1F / B2F (the table fallback when empty)."""
    parties = [t["mons"] for m in MT_MOON_MAPS for t in trainers_on(m, kb) if t["mons"]]
    return max(parties, key=lambda p: sum(lv for lv, _ in p), default=[])
