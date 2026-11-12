"""Battle knowledge: cartridge move values, type math, and the learned ledgers around them.

Move powers, the type chart and species data come from kb/rom_tables.json (ROM_KB; None when
no ROM was ever read on this machine). RAM type bytes use the Gen 1 ids in TYPE_IDS. Our
battler's types are wBattleMon 0xD019/0xD01A - the Pokemon actually in the fight; party slot
1's 0xD170/0xD171 was the old source and is wrong after a switch or a faint.
"""
from __future__ import annotations

from pokeagent.explorer.kb import ROM_KB
from pokeagent.knowledge.damage import PHYSICAL, expected_damage, turns_to_ko
from pokeagent.knowledge.scoring import ScoreCtx, adjust
from pokeagent.party_view import read_battle_view

# Gen 1 type ids as stored in wBattleMon/wEnemyMon and the pokedex base stats (6 and 9-19 unused).
TYPE_IDS = {"NORMAL": 0, "FIGHTING": 1, "FLYING": 2, "POISON": 3, "GROUND": 4, "ROCK": 5, "BUG": 7,
            "GHOST": 8, "FIRE": 20, "WATER": 21, "GRASS": 22, "ELECTRIC": 23, "PSYCHIC": 24, "ICE": 25,
            "DRAGON": 26}
TYPE_NAMES = {v: k for k, v in TYPE_IDS.items()}

ENEMY_TYPE1, ENEMY_TYPE2 = 0xCFEA, 0xCFEB       # wEnemyMon type1/type2
BATTLE_TYPE1, BATTLE_TYPE2 = 0xD019, 0xD01A     # wBattleMon type1/type2 (ours, in the fight)
ENEMY_MAXHP_HI, ENEMY_MAXHP_LO = 0xCFF4, 0xCFF5  # wEnemyMonMaxHP

_EFFECTS = ("super", "weak", "none", "neutral")


def norm_name(name) -> str:
    """Names compare without case or punctuation ('QUICK ATTACK' == 'quickattack')."""
    return "".join(ch for ch in str(name).upper() if ch.isalnum())


def type_names(ids) -> list[str]:
    """Type ids -> names, deduped in order; ids outside the Gen 1 set read '?'."""
    out: list[str] = []
    for i in ids:
        n = TYPE_NAMES.get(i, "?")
        if n not in out:
            out.append(n)
    return out


def enemy_types(emu) -> list[str]:
    """The enemy's types (wEnemyMon 0xCFEA/0xCFEB)."""
    return type_names((emu.read(ENEMY_TYPE1), emu.read(ENEMY_TYPE2)))


def battler_types(emu) -> list[str]:
    """OUR battler's types (wBattleMon 0xD019/0xD01A) - the Pokemon actually in the fight."""
    return type_names((emu.read(BATTLE_TYPE1), emu.read(BATTLE_TYPE2)))


def enemy_max_hp(emu) -> int:
    return (emu.read(ENEMY_MAXHP_HI) << 8) | emu.read(ENEMY_MAXHP_LO)


def move_by_name(name: str) -> dict | None:
    """The ROM_KB move whose display name matches (normalized), else None."""
    if not ROM_KB:
        return None
    n = norm_name(name)
    for mv in ROM_KB["moves"].values():
        if norm_name(mv["name"]) == n:
            return mv
    return None


FIXED_DAMAGE_EFFECTS = (0x28, 0x29)  # ROM move effects: SUPER FANG (half HP), fixed damage (DRAGON RAGE, SONICBOOM, ...)


def is_typed_attack(name: str) -> bool:
    """A ROM move whose damage follows the type chart: power > 0 and not a fixed-damage effect.
    Status moves (GROWL) and fixed-damage moves must not feed the type-effect or damage-by-type ledgers."""
    mv = move_by_name(name)
    return bool(mv) and mv.get("power", 0) > 0 and mv.get("effect", 0) not in FIXED_DAMAGE_EFFECTS


def move_value(name: str) -> float:
    """Cartridge value of a move by name (power x accuracy, status moves 0); used when learning/forgetting moves."""
    mv = move_by_name(name)
    return mv["power"] * mv["accuracy"] if mv else 0.0


def _chart() -> dict:
    return {(a, d): e for a, d, e in ROM_KB["type_chart"]} if ROM_KB else {}


def chart_mult(chart: dict, move_type: str, def_types: list[str]) -> float:
    """Type-chart multiplier of move_type against each defender type, multiplied out."""
    eff = 1.0
    for t in def_types:
        eff *= chart.get((move_type, t), 1.0)
    return eff


def expected_effect(eff: float) -> str:
    """The battle message a chart multiplier should produce."""
    if eff <= 0:
        return "none"
    if eff >= 2:
        return "super"
    if eff <= 0.5:
        return "weak"
    return "neutral"


def _tag(mv: dict, eff: float, defs: list[str], mine: list[str]) -> str:
    """'EMBER x2 FIRE>GRASS/POISON STAB' - one move's matchup; the rule string for sees/thinking."""
    return f"{mv['name']} x{eff:g} {mv['type']}>{'/'.join(defs)}{' STAB' if mv['type'] in mine else ''}"


def move_rule(emu, name: str) -> str:
    """The chosen move's rule string ('EMBER x2 FIRE>GRASS/POISON STAB'); the bare name without ROM_KB."""
    mv = move_by_name(name)
    if mv is None:
        return name
    defs, mine = enemy_types(emu), battler_types(emu)
    return _tag(mv, chart_mult(_chart(), mv["type"], defs), defs, mine)


def _score_ctx(emu, rows: list, chart: dict, defs: list[str], mine: list[str], catching: bool) -> ScoreCtx:
    """Battle facts the effect table needs; fast_ko = our best damaging move ends the fight in <= 2 turns."""
    from pokeagent.ramstructs import read_battle_mon, read_enemy_mon
    me, foe = read_battle_mon(emu), read_enemy_mon(emu)
    best = 0.0
    for mv, pp in rows:
        phys = mv["type"] in PHYSICAL
        a, d = (me.stats[0], foe.stats[1]) if phys else (me.stats[3], foe.stats[3])
        best = max(best, expected_damage(me.level, mv["power"], a, d, stab=mv["type"] in mine, eff=chart_mult(chart, mv["type"], defs))
                   * mv["accuracy"] * (pp > 0))
    return ScoreCtx(level=me.level, hp_frac=me.hp / me.max_hp if me.max_hp else 1.0, enemy_hp=foe.hp, enemy_status=foe.status,
                    catching=catching, fast_ko=bool(foe.hp and best and turns_to_ko(foe.hp, best) <= 2))


def move_scores(emu, catching: bool = False) -> dict[str, tuple[float, str]]:
    """Knowledge-based move values for the current battle: power x type effectiveness (ROM type chart) x STAB x
    accuracy, from the cartridge's own tables, then adjusted by the move's effect (knowledge.scoring: drain, two-turn,
    multi-hit, fixed damage, status when catching ...); moves with 0 PP score 0. Returns {MOVE NAME: (score, rule)}."""
    if not ROM_KB:
        return {}
    chart = _chart()
    defs, mine = enemy_types(emu), battler_types(emu)
    bm = read_battle_view(emu).battle_mon  # None while wBattleMon is stale (species 0): moves/PP unknown
    rows = []
    if bm is not None:
        for mid, pp in zip(bm.moves, bm.pp):
            mv = ROM_KB["moves"].get(str(mid))
            if mv and mid:
                rows.append((mv, pp & 0x3F))
    ctx = _score_ctx(emu, rows, chart, defs, mine, catching) if any("effect" in mv for mv, _ in rows) else ScoreCtx()
    out = {}
    for mv, pp in rows:
        eff = chart_mult(chart, mv["type"], defs)
        stab = 1.5 if mv["type"] in mine else 1.0
        base = mv["power"] * eff * stab * mv["accuracy"]
        score, note = adjust(mv, base, eff, mv["accuracy"], ctx) if pp > 0 else (0.0, "")
        out[mv["name"]] = (score if pp > 0 else 0.0, _tag(mv, eff, defs, mine) + (f" [{note}]" if note else ""))
    return out


def record_type_effect(data: dict, move_type: str | None, def_types: list[str], observed: str,
                       *, chart: dict | None = None, step: int = 0) -> None:
    """Count one observed type matchup after one of our attacks.

    The ledger key is always ``"<MOVE TYPE>>><DEF TYPE1>[/<DEF TYPE2>]"``, e.g. ``FIRE>>GRASS/POISON``
    (``>>`` separates attacker and defender; ``/`` joins a dual type); written only here, read only
    through ``learned_effect`` and the ``chart_disagreements`` entries' ``key``.
    ``data['type_effect']['FIRE>>GRASS/POISON']`` keeps super/weak/none/neutral tallies plus ``n``;
    ``learned_effect`` reads the majority. ``data['chart_disagreements']`` logs observations the ROM
    chart did not predict - a check on the drained table, expected to stay empty.
    """
    if not move_type or not def_types or "?" in def_types or observed not in _EFFECTS:
        return
    key = f"{move_type}>>{'/'.join(def_types)}"
    rec = data.setdefault("type_effect", {}).setdefault(
        key, {"super": 0, "weak": 0, "none": 0, "neutral": 0, "n": 0})
    rec[observed] += 1
    rec["n"] += 1
    if chart is None:
        chart = _chart()
    if chart:
        exp = expected_effect(chart_mult(chart, move_type, def_types))
        if exp != observed:
            dis = data.setdefault("chart_disagreements", [])
            dis.append({"key": key, "expected": exp, "observed": observed, "step": step})
            del dis[:-50]


def learned_effect(rec: dict) -> str:
    """The matchup a type_effect record agrees on most (ties resolve in _EFFECTS order)."""
    return max(_EFFECTS, key=lambda e: rec.get(e, 0))


def observed_damage(data: dict, species, move: str, type_key: str, emax: int) -> tuple[int, float]:
    """(tried, approx damage) for the move chooser's tiebreak: the species-specific move_damage
    record first, then the type-generalised damage_by_type fractions scaled by this enemy's max HP."""
    d = data.get("move_damage", {}).get(f"{species}:{move}")
    if d:
        return 1, sum(d) / len(d)
    t = data.get("damage_by_type", {}).get(f"{move}|{type_key}")
    if t:
        return 1, (sum(t) / len(t)) * emax
    return 0, 0.0


def threat_score(emu, move_name: str) -> float | None:
    """How dangerous an enemy move is to our battler: ROM power x type effectiveness against
    wBattleMon's types x the enemy's own STAB. None when the move or the tables are unknown."""
    if not ROM_KB:
        return None
    mv = move_by_name(move_name)
    if mv is None:
        return None
    mine, theirs = battler_types(emu), enemy_types(emu)
    eff = chart_mult(_chart(), mv["type"], mine)
    stab = 1.5 if mv["type"] in theirs else 1.0
    return mv["power"] * eff * stab


def record_threat(data: dict, emu, species: int, move_name: str, *, step: int = 0) -> None:
    """Keep the worst ROM-estimated threat each enemy species has shown (``threat_by_species``)."""
    score = threat_score(emu, move_name)
    if score is None:
        return
    rec = data.setdefault("threat_by_species", {}).setdefault(
        str(species), {"move": "", "type": "", "score": 0.0, "n": 0})
    rec["n"] += 1
    if score > rec["score"]:
        mv = move_by_name(move_name) or {}
        rec.update({"move": move_name, "type": mv.get("type", ""), "score": score})
