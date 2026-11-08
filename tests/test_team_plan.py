"""team_plan: the team-level gate (boss_need), matchup lead, matchup switch, exp band, grind pressure.

All fixtures are synthetic (no ROM): a small species/move/chart table like test_catch_plan's.
"""
from __future__ import annotations

from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge import team_plan
from pokeagent.knowledge.party import Combatant


def _mv(name, typ, power, acc=1.0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": 0, "pp": 20}


def _sp(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc,
            "moves1": moves1}


SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35), "2": _mv("WATER GUN", "WATER", 40),
              "3": _mv("EMBER", "FIRE", 40), "4": _mv("VINE WHIP", "GRASS", 45),
              "5": _mv("THUNDERSHOCK", "ELECTRIC", 40)},
    "type_chart": [["WATER", "FIRE", 2.0], ["WATER", "WATER", 0.5], ["WATER", "GRASS", 0.5],
                   ["WATER", "ELECTRIC", 1.0], ["FIRE", "WATER", 0.5], ["GRASS", "WATER", 2.0],
                   ["ELECTRIC", "WATER", 2.0], ["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0]],
    "species_by_dex": {
        "1": _sp("MAGIKARP", "WATER", "WATER", 20, 10, 55, 80, 20, ["TACKLE"]),
        "2": _sp("RATTATA", "NORMAL", "NORMAL", 30, 56, 35, 72, 25, ["TACKLE"]),
        "3": _sp("PIDGEY", "NORMAL", "FLYING", 40, 45, 40, 56, 35, ["TACKLE"]),
        "4": _sp("CHARMELEON", "FIRE", "FIRE", 58, 64, 58, 80, 65, ["EMBER"]),
        "5": _sp("WEEDLE", "BUG", "POISON", 40, 35, 30, 50, 20, ["TACKLE"]),
        "6": _sp("SPEAROW", "NORMAL", "FLYING", 40, 60, 30, 70, 31, ["TACKLE"]),
        "7": _sp("ODDISH", "GRASS", "POISON", 45, 50, 55, 30, 75, ["VINE WHIP"]),
        "8": _sp("STARYU", "WATER", "WATER", 30, 45, 55, 85, 70, ["WATER GUN"]),
        "9": _sp("STARMIE", "WATER", "PSYCHIC", 60, 75, 85, 115, 100, ["WATER GUN"]),
        "10": _sp("PIKACHU", "ELECTRIC", "ELECTRIC", 35, 55, 30, 90, 50, ["THUNDERSHOCK"]),
        "11": _sp("GYARADOS", "WATER", "FLYING", 95, 125, 79, 81, 100, ["WATER GUN"]),
    },
    "learnsets": {n: {"learnset": []} for n in ("MAGIKARP", "RATTATA", "PIDGEY", "CHARMELEON", "WEEDLE", "SPEAROW",
                                              "ODDISH", "STARYU", "STARMIE", "PIKACHU", "GYARADOS")},
}

MISTY = [(18, "STARYU"), (21, "STARMIE")]


def _mon(name, level, moves=None):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, tuple(dict.fromkeys((row["type1"], row["type2"]))), hp, st,
                     tuple(moves if moves is not None else row["moves1"]), (8,) * 5, (0,) * 5)


def _marathon_party():
    """The marathon run's shape: a weak Magikarp leads, the strong mon sits in slot 3."""
    return [_mon("MAGIKARP", 12), _mon("RATTATA", 8), _mon("PIDGEY", 9),
            _mon("CHARMELEON", 23), _mon("WEEDLE", 10), _mon("SPEAROW", 12)]


# --- the team-level gate --------------------------------------------------------------------------------------------

def test_boss_need_marathon_party_not_ready_names_slot_3():
    nv = team_plan.boss_need(_marathon_party(), MISTY, SYN, "MISTY")
    assert nv is not None and nv.ready is False
    assert nv.lead_slot == 3          # CHARMELEON, not the Magikarp in slot 0
    assert nv.team_score < 0.3
    assert nv.raise_slot in (0, 3)    # Magikarp -> Gyarados at L25, or the Charmeleon carry
    assert nv.raise_level is not None
    assert nv.raise_level > _marathon_party()[nv.raise_slot].level
    assert "not ready" in nv.text


def test_boss_need_ready_and_empty():
    assert team_plan.boss_need([], MISTY, SYN) is None
    assert team_plan.boss_need(_marathon_party(), [], SYN) is None
    strong = [_mon("GYARADOS", 40), _mon("CHARMELEON", 30), _mon("PIKACHU", 28)]
    nv = team_plan.boss_need(strong, MISTY, SYN, "MISTY")
    assert nv is not None and nv.ready and nv.weak_slots == ()


def test_choose_lead_picks_the_water_answer_against_staryu():
    team = [_mon("CHARMELEON", 20), _mon("ODDISH", 20), _mon("SPEAROW", 21)]
    foe = [m for lv, n in MISTY if (m := _mon(n, lv))]
    # GRASS hits Staryu x2, Ember is resisted x0.5: the Oddish leads even in slot 1
    assert team_plan.choose_lead(team, foe[:1], SYN) == 1
    # without a Grass answer the strongest damage ratio leads
    assert team_plan.choose_lead(_marathon_party(), foe[:1], SYN) == 3


# --- the matchup switch ----------------------------------------------------------------------------------------------

def test_switch_choice_thin_fire_lead_swaps_for_grass():
    team = [_mon("CHARMELEON", 15), _mon("ODDISH", 16)]
    foe = _mon("STARMIE", 21)
    pick = team_plan.switch_choice(team, 0, foe, SYN)
    assert pick == 1  # Water hits Fire x2 and Ember is resisted: the Grass member fights better
    assert team_plan.switch_choice(team, 0, foe, SYN, switches=2) is None  # per-battle cap
    assert team_plan.switch_choice(team, 0, foe, SYN, trainee=1) is None   # never the trainee IN


def test_switch_choice_returns_none_when_nothing_is_better():
    team = [_mon("CHARMELEON", 15), _mon("WEEDLE", 9)]
    foe = _mon("STARMIE", 21)
    # thin but nobody beats the ratio by SWITCH_GAIN, and the weedle cannot take a hit either way
    assert team_plan.switch_choice(team, 0, foe, SYN) is None
    healthy = [_mon("GYARADOS", 30), _mon("RATTATA", 25)]
    assert team_plan.switch_choice(healthy, 0, _mon("SPEAROW", 10), SYN) is None  # not thin: stay


# --- the exp band and rotation -----------------------------------------------------------------------------------------

def test_level_band_and_breakers():
    team = [_mon("CHARMELEON", 25), _mon("RATTATA", 20), _mon("ODDISH", 21), _mon("PIDGEY", 8)]
    band = team_plan.level_band(team, 25)
    assert band[0] == (25, 25) and band[1] == (21, 25)
    assert team_plan.band_breakers(team, band) == (1, 3)


def test_trainee_slot_named_then_lowest_breaker():
    party = [_mon("CHARMELEON", 25), _mon("RATTATA", 18), _mon("PIDGEY", 8)]
    assert team_plan.trainee_slot(party, named=1) == 1          # TEAM_GAP+ under the lead
    assert team_plan.trainee_slot(party, named=0) is None       # the lead is never the trainee
    assert team_plan.trainee_slot(party, named=None, breakers=(1, 2)) == 2  # the lowest breaker leads
    # a breaker that cannot take the wild mon's hit is skipped: the pick is the next survivor or None
    wild = [_mon("STARMIE", 30)]
    pick = team_plan.trainee_slot(party, named=None, breakers=(1, 2), wild=wild, kb=SYN)
    assert pick in (None, 1)  # never slot 2: the L8 Pidgey dies to one hit from Starmie


# --- grind pressure ---------------------------------------------------------------------------------------------------

def test_grind_pressure_monotonic_in_gap_and_breakers():
    team = [_mon("CHARMELEON", 20), _mon("RATTATA", 12), _mon("PIDGEY", 10)]
    assert team_plan.grind_pressure(team, 20, ready=True) == 0.0
    low = team_plan.grind_pressure(team, 21, breakers=())
    mid = team_plan.grind_pressure(team, 26, breakers=())
    high = team_plan.grind_pressure(team, 26, breakers=(1, 2))
    assert low < mid < high
    near = team_plan.grind_pressure(team, 26, next_boss_gap_steps=10, breakers=(1, 2))
    far = team_plan.grind_pressure(team, 26, next_boss_gap_steps=500, breakers=(1, 2))
    assert near > far
    assert team_plan.grind_pressure(team, 26, blackouts_recent=2, breakers=(1, 2)) > high
    assert 0.0 <= team_plan.grind_pressure(team, 60, breakers=(0, 1, 2), blackouts_recent=5) <= 1.0


def test_release_candidate_lowest_value_not_protected():
    party = [_mon("CHARMELEON", 25), _mon("RATTATA", 8), _mon("PIDGEY", 12)]
    assert team_plan.release_candidate(party, values=[c.level for c in party]) == 1
    assert team_plan.release_candidate(party, protected={1}, values=[c.level for c in party]) == 2
    assert team_plan.release_candidate(party, protected={0, 1, 2}) is None
