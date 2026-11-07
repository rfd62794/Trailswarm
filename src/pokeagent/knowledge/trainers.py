"""Trainer parties from the ROM: "what does Brock use", and the pre-gym type matchup of our team (report only)."""
from __future__ import annotations

from pokeagent.knowledge.kb import table

# The campaign's bosses: goal -> (trainer class, party number, gym map id). Parties come from the drained data.
GYM_BOSSES = {"beat_brock": ("BROCK", 1, 0x36), "beat_misty": ("MISTY", 1, 0x41)}
# Every later gym leader / Elite Four member: goal -> (trainer class, party number). Giovanni's parties 1 and 2 are the
# Rocket Hideout and Silph Co. fights; party 3 is the gym. (Map ids are only needed for the first two, kept as above.)
LEADER_BOSSES = {"beat_surge": ("LT.SURGE", 1), "beat_erika": ("ERIKA", 1), "beat_koga": ("KOGA", 1),
                 "beat_sabrina": ("SABRINA", 1), "beat_blaine": ("BLAINE", 1), "beat_giovanni": ("GIOVANNI", 3),
                 "beat_lorelei": ("LORELEI", 1), "beat_bruno": ("BRUNO", 1), "beat_agatha": ("AGATHA", 1),
                 "beat_lance": ("LANCE", 1)}
# The rival: goal -> (trainer class, first party number). Each class holds one party per rival starter, in groups of three
# (Squirtle, Bulbasaur, Charmander = the rival's pick, i.e. the player picked Bulbasaur, Charmander, Squirtle).
RIVAL_BOSSES = {"rival_ss_anne": ("RIVAL2", 1), "rival_pokemon_tower": ("RIVAL2", 4), "rival_silph": ("RIVAL2", 7),
                "rival_route22": ("RIVAL2", 10), "beat_champion": ("RIVAL3", 1)}
PLAYER_STARTER_LINE = {"SQUIRTLE": 2, "WARTORTLE": 2, "BLASTOISE": 2, "BULBASAUR": 0, "IVYSAUR": 0, "VENUSAUR": 0,
                       "CHARMANDER": 1, "CHARMELEON": 1, "CHARIZARD": 1}
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


def rival_variant(starter_names=()) -> int | None:
    """0/1/2 = which of the rival's three parties we face, from any of OUR party's names in a starter line; None if unknown."""
    return next((PLAYER_STARTER_LINE[n] for n in starter_names if n in PLAYER_STARTER_LINE), None)


def boss_party(goal: str, kb: dict | None = None, starter_names=()) -> list[tuple[int, str]]:
    """The party we fight to land `goal`: a gym leader, an Elite Four member, or the rival; [] when `goal` has no boss.
    The rival's party follows our starter line (`starter_names` = our party's species); unknown, we take the strongest
    of the three (the cautious choice)."""
    if goal in GYM_BOSSES:
        cls, num, _ = GYM_BOSSES[goal]
        return party_of(cls, num, kb)
    if goal in LEADER_BOSSES:
        return party_of(*LEADER_BOSSES[goal], kb=kb)
    if goal in RIVAL_BOSSES:
        cls, first = RIVAL_BOSSES[goal]
        v = rival_variant(starter_names)
        options = [party_of(cls, first + i, kb) for i in ((v,) if v is not None else range(3))]
        return max(options, key=lambda p: sum(lv for lv, _ in p), default=[])
    return []


def strongest_on_mt_moon(kb: dict | None = None) -> list[tuple[int, str]]:
    """The party with the highest total level among the trainers on Mt Moon 1F / B1F / B2F (the table fallback when empty)."""
    parties = [t["mons"] for m in MT_MOON_MAPS for t in trainers_on(m, kb) if t["mons"]]
    return max(parties, key=lambda p: sum(lv for lv, _ in p), default=[])
