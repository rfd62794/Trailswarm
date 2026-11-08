"""catcher: the damaging-move HARD RULE (a Splash-only Magikarp and a status-only set are rejected),
the EVERY-wild-mon bar, the catcher slot, and the level band."""
from __future__ import annotations

from dataclasses import replace

from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge.catcher import (CATCHER_BAND, catcher_slot, level_band_ok, min_damage,
                                        qualifies, safe_moves)
from pokeagent.knowledge.party import Combatant


def _mv(name, typ, power, acc=1.0, effect=0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": effect, "pp": 20}


def _sp(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd,
            "spc": spc, "moves1": moves1}


SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("SPLASH", "NORMAL", 0),
              "3": _mv("SLEEP POWDER", "GRASS", 0, 0.75, effect=0x20), "4": _mv("HYPER", "NORMAL", 150, 0.9)},
    "type_chart": [["NORMAL", "GHOST", 0.0]],
    "species_by_dex": {
        "1": _sp("MAGIKARP", "WATER", "WATER", 15, 5, 40, 50, 10, ["SPLASH"]),
        "2": _sp("PIDGEY", "NORMAL", "FLYING", 30, 25, 40, 40, 30, ["TACKLE"]),
        "3": _sp("SINGER", "NORMAL", "NORMAL", 40, 30, 30, 30, 30, ["SLEEP POWDER"]),
        "4": _sp("AQUA", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
        "5": _sp("SPOOKY", "GHOST", "GHOST", 30, 30, 30, 30, 30, ["TACKLE"]),
        "6": _sp("BULLY", "NORMAL", "NORMAL", 60, 80, 60, 50, 50, ["TACKLE", "HYPER"]),
    },
}
CHART = {(a, d): e for a, d, e in SYN["type_chart"]}
MOVES = SYN["moves"]


def _mon(name, level, moves=None):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    types = tuple(dict.fromkeys((row["type1"], row["type2"])))
    return Combatant(name, level, types, hp, st, tuple(moves if moves is not None else row["moves1"]), (8,) * 5, (0,) * 5)


# the HARD RULE: no damaging move, no catcher
def test_splash_only_magikarp_and_status_only_set_are_rejected():
    pidgey = _mon("PIDGEY", 3)
    assert not qualifies(_mon("MAGIKARP", 10), [pidgey], CHART, MOVES)          # SPLASH only
    assert not qualifies(_mon("SINGER", 12), [pidgey], CHART, MOVES)            # a sleep move is a bonus, never the role
    assert safe_moves(_mon("MAGIKARP", 10), pidgey, CHART, MOVES) == []
    assert min_damage(_mon("MAGIKARP", 10), MOVES["2"], pidgey, CHART) == 0.0


def test_tackle_magikarp_qualifies_only_when_it_cannot_ko():
    pidgey = _mon("PIDGEY", 3)
    karp = _mon("MAGIKARP", 15, ("SPLASH", "TACKLE"))
    assert qualifies(karp, [pidgey], CHART, MOVES)                            # min-roll TACKLE cannot KO the L3 Pidgey
    assert "TACKLE" in safe_moves(karp, pidgey, CHART, MOVES)
    weak = replace(pidgey, hp=5)                                              # same target weakened: the hit would finish it
    assert not qualifies(karp, [weak], CHART, MOVES)


def test_every_move_koing_is_rejected_and_every_wild_mon_must_be_safe():
    pidgey, spooky = _mon("PIDGEY", 3), _mon("SPOOKY", 3)
    assert not qualifies(_mon("AQUA", 30), [pidgey], CHART, MOVES)             # min-roll TACKLE KOs: overpowered, not a catcher
    karp = _mon("MAGIKARP", 15, ("SPLASH", "TACKLE"))
    assert qualifies(karp, [pidgey], CHART, MOVES)
    assert not qualifies(karp, [pidgey, spooky], CHART, MOVES)                # NORMAL is useless vs GHOST: EVERY wild mon must be safe


def test_catcher_slot_picks_the_lowest_qualifying_non_lead():
    party = [_mon("BULLY", 25), _mon("MAGIKARP", 15, ("SPLASH", "TACKLE")), _mon("PIDGEY", 12)]
    assert catcher_slot(party, [_mon("PIDGEY", 3)], CHART, MOVES) == 2        # the L12 over the L15
    assert catcher_slot(party, [_mon("PIDGEY", 3)], CHART, MOVES, lead=2) == 1  # the lead is never its own catcher
    assert catcher_slot([_mon("BULLY", 25)], [_mon("PIDGEY", 3)], CHART, MOVES) is None
    assert catcher_slot(party, [_mon("PIDGEY", 3)], CHART, {}) is None        # no move data: nobody qualifies


def test_level_band_around_catcher_band():
    wild = [_mon("PIDGEY", 3)]
    lead = _mon("AQUA", 20)
    assert level_band_ok([lead, _mon("PIDGEY", 20 - CATCHER_BAND)], wild, CHART, MOVES)
    assert not level_band_ok([lead, _mon("PIDGEY", 20 - CATCHER_BAND + 1)], wild, CHART, MOVES)
    assert not level_band_ok([lead], wild, CHART, MOVES)
    assert not level_band_ok([], wild, CHART, MOVES)
    assert level_band_ok([lead, _mon("PIDGEY", 5)], wild, CHART, MOVES, band=2)
