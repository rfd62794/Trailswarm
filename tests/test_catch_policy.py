"""catch_policy: the wild-only HARD RULE (may_throw), status first, minimum damage, the overpower
gate (switch to a catcher / throw at full HP / skip), the ball choice, and the turn cap."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace


from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge.catch_policy import (ACCEPTABLE_P, MAX_TURNS, CatchStep, decide, may_throw,
                                             may_throw_ctx)
from pokeagent.knowledge.catcher import catcher_slot
from pokeagent.knowledge.party import Combatant


def _mv(name, typ, power, acc=1.0, effect=0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": effect, "pp": 20}


def _sp(name, t1, t2, hp, atk, dfn, spd, spc, moves1, catch_rate=255):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd,
            "spc": spc, "moves1": moves1, "catch_rate": catch_rate}


SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40),
              "3": _mv("HYPER", "NORMAL", 150, 0.9), "4": _mv("THUNDER WAVE", "ELECTRIC", 0, 1.0, effect=0x43),
              "5": _mv("SLEEP POWDER", "GRASS", 0, 0.75, effect=0x20), "6": _mv("SPLASH", "NORMAL", 0)},
    "type_chart": [],
    "species_by_dex": {
        "1": _sp("AQUA", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
        "2": _sp("BIGLEAD", "NORMAL", "NORMAL", 60, 80, 60, 50, 50, ["TACKLE", "HYPER"]),
        "3": _sp("PIDGEY", "NORMAL", "FLYING", 30, 25, 40, 40, 30, ["TACKLE"]),
        "4": _sp("RARE", "NORMAL", "NORMAL", 60, 50, 50, 50, 50, ["TACKLE"], catch_rate=45),
        "5": _sp("KARP", "WATER", "WATER", 15, 5, 40, 50, 10, ["SPLASH"]),
        "6": _sp("SINGER", "NORMAL", "NORMAL", 40, 30, 30, 30, 30, ["SLEEP POWDER"]),
    },
}
CHART = {(a, d): e for a, d, e in SYN["type_chart"]}
MOVES = SYN["moves"]
PRICE = {"POKE": 200, "GREAT": 600, "ULTRA": 1200}
POKES = {"POKE": 5, "GREAT": 0, "ULTRA": 0}
ALL_BALLS = {"POKE": 5, "GREAT": 3, "ULTRA": 1}
GREATS = {"POKE": 0, "GREAT": 3, "ULTRA": 0}


def _mon(name, level, moves=None):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    types = tuple(dict.fromkeys((row["type1"], row["type2"])))
    return Combatant(name, level, types, hp, st, tuple(moves if moves is not None else row["moves1"]), (8,) * 5, (0,) * 5)


def _wild(name, level, hp=None):
    m = _mon(name, level)
    return m if hp is None else replace(m, hp=hp)


def _decide(active, wild, hp, hpmax, *, rate=255, bag=None, status=None, party=None, turn=0, kind=1, **kw):
    return decide(active, [active] if party is None else party, wild, hp, hpmax, status, rate,
                  POKES if bag is None else bag, PRICE, CHART, MOVES, turn=turn, kind=kind, **kw)


# the HARD RULE: only wild pokemon can be caught, never an owned/trainer one
def test_may_throw_is_wild_only():
    assert may_throw(1) and may_throw(1, None, None)
    assert not may_throw(2) and not may_throw(None) and not may_throw(0)
    assert not may_throw(1, {"pic": 1})                     # a trainer NPC is set
    assert not may_throw(1, None, 2)                        # the battle log says trainer
    ctx = SimpleNamespace(bv=SimpleNamespace(kind=1), trainer_npc=None, battle_log=None)
    assert may_throw_ctx(ctx)
    assert not may_throw_ctx(SimpleNamespace(bv=SimpleNamespace(kind=2), trainer_npc=None, battle_log=None))
    assert not may_throw_ctx(SimpleNamespace(bv=SimpleNamespace(kind=1), trainer_npc={"pic": 2}, battle_log=None))
    assert not may_throw_ctx(SimpleNamespace(bv=None, trainer_npc=None, battle_log={"kind": 2}))


def test_trainer_battle_always_skips():
    aqua = _mon("AQUA", 10)
    rare = _wild("RARE", 5, 21)
    for kw in (dict(kind=2), dict(trainer_npc={"pic": 1}), dict(battle_log_kind=2)):
        step = _decide(aqua, rare, 21, 21, rate=45, bag=ALL_BALLS, **kw)
        assert step == CatchStep("skip", why="trainer battle: cannot catch")
    # even a lone overpowering lead with a qualifying catcher in the party: never switch/throw in a trainer fight
    party = [_mon("BIGLEAD", 25), _mon("KARP", 15, ("SPLASH", "TACKLE"))]
    pidgey = _wild("PIDGEY", 3, 15)
    assert _decide(party[0], pidgey, 15, 15, party=party, kind=2).kind == "skip"


# 1. status first
def test_status_first_sleep_beats_paralyse_and_never_restatuses():
    aqua = _mon("AQUA", 10, ("TACKLE", "SLEEP POWDER", "THUNDER WAVE"))
    rare = _wild("RARE", 5, 21)
    step = _decide(aqua, rare, 21, 21, rate=45, bag=GREATS)
    assert step.kind == "status_move" and step.move == "SLEEP POWDER"      # sleep (25) over paralyse (12)
    tw = _decide(_mon("AQUA", 10, ("TACKLE", "THUNDER WAVE")), rare, 21, 21, rate=45, bag=GREATS)
    assert tw.kind == "status_move" and tw.move == "THUNDER WAVE"
    done = _decide(aqua, rare, 21, 21, rate=45, bag=GREATS, status="paralyse")
    assert done.kind != "status_move"                                      # never re-status an afflicted mon


# 2. minimum damage
def test_weakest_safe_hit_is_chosen_and_a_ko_hit_never_is():
    aqua = _mon("AQUA", 10, ("TACKLE", "WATER GUN"))
    rare = _wild("RARE", 5, 21)
    step = _decide(aqua, rare, 21, 21, rate=45)
    assert step.kind == "damage_move" and step.move == "TACKLE"            # 35 power under 40
    hurt = _wild("RARE", 5, 8)                                             # >35% HP but a hit could finish it
    step = _decide(aqua, hurt, 8, 21, rate=45)
    assert step.kind == "throw"                                            # no hit is safe this turn: throw


# 3. the overpower gate
def test_overpower_gate_switch_throw_and_skip():
    lead = _mon("BIGLEAD", 25)
    karp = _mon("KARP", 15, ("SPLASH", "TACKLE"))
    singer = _mon("SINGER", 9)
    pidgey = _wild("PIDGEY", 3, 15)
    party = [lead, singer, karp]
    step = _decide(lead, pidgey, 15, 15, party=party)
    assert step.kind == "switch" and step.slot == 2                        # the qualifying catcher, not the lead
    step = _decide(lead, pidgey, 15, 15)                                   # no catcher: full HP + easy species -> throw
    assert step.kind == "throw" and step.p >= ACCEPTABLE_P
    hurt = _decide(lead, _wild("PIDGEY", 3, 9), 9, 15)                     # no catcher, hurt, P fine -> throw (no full-HP gate)
    assert hurt.kind == "throw" and hurt.p >= ACCEPTABLE_P
    rare = _wild("RARE", 3, 16)
    step = _decide(lead, rare, 16, 16, rate=45)                            # no catcher, P too low -> skip
    assert step.kind == "skip" and "overpowered" in step.why


def test_catcher_must_be_fit_and_lead_index_is_used():
    lead = _mon("BIGLEAD", 25)
    karp = _mon("KARP", 15, ("SPLASH", "TACKLE"))
    pidgey = _wild("PIDGEY", 3, 15)
    party = [lead, karp]
    ok = _decide(lead, pidgey, 15, 15, party=party, party_hp=[(60, 60), (40, 40)])
    assert ok.kind == "switch" and ok.slot == 1
    for hp in (0, 9):                                                      # fainted / under 25% of 40
        step = _decide(lead, pidgey, 15, 15, party=party, party_hp=[(60, 60), (hp, 40)])
        assert step.kind != "switch"
    twins = [_mon("BIGLEAD", 25), _mon("BIGLEAD", 25), karp]               # identical mons: lead index decides
    step = _decide(twins[1], pidgey, 15, 15, party=twins, lead=1)
    assert step.kind == "switch" and step.slot == 2
    assert catcher_slot(twins, [pidgey], CHART, MOVES, lead=1, fit=[True, True, False]) is None


# 4. the ball choice and the weaken target
def test_throw_picks_the_best_value_ball_and_weakened_goes_straight_to_throw():
    aqua = _mon("AQUA", 10, ("TACKLE",))
    rare = _wild("RARE", 5, 7)                                             # <=35% HP and still safe to hit
    step = _decide(aqua, rare, 7, 21, rate=45, bag=ALL_BALLS)
    assert step.kind == "throw" and step.ball == "POKE"                    # a Great Ball is not worth 3x here
    step = _decide(aqua, rare, 7, 21, rate=45, bag={"POKE": 0, "GREAT": 2, "ULTRA": 1})
    assert step.kind == "throw" and step.ball == "GREAT"
    step = _decide(aqua, rare, 7, 21, rate=45, bag={"POKE": 0, "GREAT": 0, "ULTRA": 0})
    assert step.kind == "skip"                                             # no ball in the bag


# 5. the turn cap and unknown data
def test_turn_cap_and_missing_data_skip_without_raising():
    aqua = _mon("AQUA", 10)
    rare = _wild("RARE", 5, 21)
    assert _decide(aqua, rare, 21, 21, rate=45, turn=MAX_TURNS).kind == "skip"
    assert _decide(aqua, rare, 21, 21, rate=45, turn=MAX_TURNS - 1).kind != "skip"
    assert _decide(aqua, None, 0, 0, rate=0).kind == "skip"                # unknown species
    assert _decide(None, rare, 21, 21, rate=45).kind == "skip"
    step = decide(aqua, [aqua], rare, 21, 21, None, 45, POKES, PRICE, {}, {}, turn=0)
    assert step.kind in ("throw", "skip", "switch")                        # empty tables: deterministic, no exception


# run explore-20261112-072650 step 1506: a full-HP wild mon whose only safe hit fails just the worst case
# (max roll AND crit) was thrown at unweakened; a non-crit-safe hit must weaken it first.
def test_full_hp_weakens_when_only_the_crit_margin_fails():
    aqua, wild = _mon("AQUA", 14), _wild("RARE", 5)
    step = _decide(aqua, wild, wild.hp, wild.hp)
    assert step.kind == "damage_move" and step.move == "TACKLE"


def test_full_hp_still_throws_when_a_plain_max_roll_could_ko():
    wild = _wild("RARE", 3)
    step = _decide(_mon("BIGLEAD", 30, ("TACKLE",)), wild, wild.hp, wild.hp)
    assert step.kind != "damage_move"
