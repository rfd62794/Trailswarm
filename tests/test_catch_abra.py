"""catch_abra (--build abra): the goal's settle rule, the flee-species turn-1 throw, the build want,
and the full-party/floor/build-key guards. Synthetic fixtures (test_catch_policy's table; party_mem
fakes for RAM), no ROM.
"""
from __future__ import annotations

import pytest
from dataclasses import replace
from types import SimpleNamespace

from pokeagent import team_fp
from pokeagent.abra_goal import ABRA_STEP_CAP, BALLS_MIN, catch_abra_settled, resolve_build
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.catch import full_party_slot
from pokeagent.explorer.catch_list import catch_wanted
from pokeagent.knowledge import team_floor
from pokeagent.knowledge.flee_catch import flee_on_turn
from pokeagent.knowledge.party import Combatant
from pokeagent.goals import GOALS, check_goals
from test_catch_policy import ALL_BALLS, _decide, _mon
from test_magikarp import bcd, party_mem
from test_team_floor import BOSS
from test_team_plan import SYN, _mon as _tp_mon

ABRA_ID, KADABRA_ID, ALAKAZAM_ID = 148, 38, 149   # name_of_internal ids in the NAMES fake below
NAMES = {"148": "ABRA", "38": "KADABRA", "149": "ALAKAZAM", "177": "CHARMANDER"}


def _abra(level=10, hp=None):
    m = Combatant("ABRA", level, ("PSYCHIC",), 30, (20, 20, 40, 20), ("TELEPORT",), (8,) * 5, (0,) * 5)
    return m if hp is None else replace(m, hp=hp)


def _st(build="abra", **extra):
    return {"opts": SimpleNamespace(build=build), **extra}


def _emu(mons=((177, 14, 30, 30),), money=0, balls=None):
    mem = {**party_mem(list(mons)), **bcd(money)}
    if balls is not None:  # {item_id: qty} into the bag slots (0xD31D count + 0xD31E pairs)
        items = list(balls.items())
        mem[0xD31D] = len(items)
        for i, (it, q) in enumerate(items):
            mem[0xD31E + 2 * i], mem[0xD31E + 2 * i + 1] = it, q
    return FakeEmulator(mem)


def _set(emu: FakeEmulator, mem: dict) -> None:
    for a, v in mem.items():
        emu.set(a, v)


# --- flee_on_turn / the catch policy's flee rule --------------------------------------------------------------------

def test_flee_on_turn_marks_flee_species_and_all_flee_moves():
    assert flee_on_turn("ABRA", ()) and flee_on_turn("ABRA", ("TACKLE",))   # species table: any moves
    assert flee_on_turn("ZUBAT", ("ROAR", "WHIRLWIND"))                    # every known move a battle-ender
    assert flee_on_turn("PIDGEY", ("TELEPORT",))
    assert not flee_on_turn("PIDGEY", ("TACKLE",)) and not flee_on_turn("PIDGEY", ())
    assert flee_on_turn(None, ("TELEPORT",))                                     # nameless but all-flee: still throws first


def test_flee_species_throws_on_turn_one_never_weakens():
    abra = _abra(10)
    step = _decide(_mon("AQUA", 10), abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=0)
    assert step.kind == "throw" and step.ball                                    # 100% HP: still a throw
    assert "flee" in step.why
    again = _decide(_mon("AQUA", 10), abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=1)
    assert again.kind == "throw"                                                 # a failed throw: throw again
    hurt = _decide(_mon("AQUA", 10), abra, 5, abra.hp, rate=200, bag=ALL_BALLS, turn=3)
    assert hurt.kind == "throw" and hurt.ball                                    # never a damage_move, any HP
    pidgey = _mon("PIDGEY", 10)
    non_flee = _decide(_mon("AQUA", 10), pidgey, pidgey.hp, pidgey.hp, rate=45, turn=0)
    assert non_flee.kind != "throw" or "flee" not in non_flee.why                # non-flee: unchanged rules


def test_flee_species_first_turn_may_status_instead():
    singer = _mon("SINGER", 9)                                                   # knows only SLEEP POWDER
    abra = _abra(10)
    step = _decide(singer, abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=0)
    assert step.kind in ("status_move", "throw")                                 # status MAY run on the first turn
    if step.kind == "status_move":
        assert step.move == "SLEEP POWDER"
    already = _decide(singer, abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=0, status="sleep")
    assert already.kind == "throw"                                               # never re-status an afflicted mon


# --- catch_abra_settled ----------------------------------------------------------------------------------------------

def test_goal_settles_for_any_build_but_abra():
    assert catch_abra_settled(_emu(), _st(""), set(), {"name_of_internal": NAMES})
    assert catch_abra_settled(_emu(), _st("gyarados"), set(), {"name_of_internal": NAMES})
    assert not catch_abra_settled(_emu(money=3000), _st("abra"), set(), {"name_of_internal": NAMES})


def test_goal_opens_until_an_abra_line_member_is_in_the_party():
    emu = _emu(((177, 14, 30, 30),), money=3000, balls={4: 15})
    st = _st("abra")
    assert not catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})   # open: nobody yet
    _set(emu, party_mem([(177, 14, 30, 30), (ABRA_ID, 10, 25, 25)]))
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES}) and st["had_abra"]
    _set(emu, party_mem([(177, 14, 30, 30)]))
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})       # sticky: depositing does not reopen


def test_kadabra_and_alakazam_count_too():
    for sp in (KADABRA_ID, ALAKAZAM_ID):
        emu = _emu(((177, 14, 30, 30), (sp, 20, 40, 40)), money=0)
        assert catch_abra_settled(emu, _st("abra"), set(), {"name_of_internal": NAMES})


def test_goal_settles_on_the_step_cap_and_when_no_balls_no_money():
    emu = _emu(money=3000)
    st = _st("abra", abra_skipped=True)
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})       # ABRA_STEP_CAP spent
    broke = _emu(money=0, balls={4: BALLS_MIN - 1})
    assert catch_abra_settled(broke, _st("abra"), set(), {"name_of_internal": NAMES})  # no balls, no money
    restockable = _emu(money=3000, balls={4: BALLS_MIN - 1})
    assert not catch_abra_settled(restockable, _st("abra"), set(), {"name_of_internal": NAMES})  # money buys a ball
    stocked = _emu(money=0, balls={4: BALLS_MIN})
    assert not catch_abra_settled(stocked, _st("abra"), set(), {"name_of_internal": NAMES})


def test_check_goals_wires_catch_abra_between_team_ready_and_to_bill():
    assert GOALS.index("catch_abra") == GOALS.index("team_ready") + 1
    assert GOALS.index("to_bill") == GOALS.index("catch_abra") + 1
    g = check_goals(_emu(money=3000), _st("abra"))
    assert g["catch_abra"] is False                                            # open under the build
    assert check_goals(_emu(money=3000), {})["catch_abra"]                     # settled for the default build


def test_constants_named():
    assert ABRA_STEP_CAP == 3000 and BALLS_MIN == 12


def test_resolve_build_accepts_only_the_known_builds():
    assert resolve_build("abra", None) == "abra" and resolve_build(None, "abra") == "abra"
    assert resolve_build(None, None) == "" and resolve_build("", "abra") == ""   # the flag wins
    with pytest.raises(ValueError):
        resolve_build("charmander", None)


# --- the build want / full-party protection / floor + key -------------------------------------------------------------

def test_catch_wanted_wants_abra_line_only_for_the_build():
    assert catch_wanted("ABRA", [], 20, [], build="abra") == "catch_abra goal (build abra)"
    assert catch_wanted("KADABRA", [], 20, [], build="abra") == "catch_abra goal (build abra)"
    assert catch_wanted("ABRA", [], 20, []) is None                              # default build: dex rules only
    assert catch_wanted("KAKUNA", [], 20, [], build="abra") is None              # NEVER_CATCH still wins


def _six(build, abra_level=10):
    party = [SimpleNamespace(name="RATTATA", level=12, moves=("TACKLE",)),
             SimpleNamespace(name="PIDGEY", level=14, moves=("TACKLE",)),
             SimpleNamespace(name="ABRA", level=abra_level, moves=("TELEPORT",)),
             SimpleNamespace(name="ODDISH", level=13, moves=("TACKLE",)),
             SimpleNamespace(name="SPEAROW", level=15, moves=("TACKLE",)),
             SimpleNamespace(name="WEEDLE", level=11, moves=("TACKLE",))]
    goals_all = {g: True for g in GOALS}
    ctx = SimpleNamespace(opts=SimpleNamespace(build=build), goals=lambda: goals_all,
                          emu=FakeEmulator({}), train_member=None)
    return party, ctx


def test_full_party_slot_never_marks_the_abra_under_build_abra(monkeypatch):
    from pokeagent.explorer.training_ctl import roster
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx: None)
    party, ctx = _six("abra")
    pick = full_party_slot(ctx, party)
    assert pick == 5                                                             # WEEDLE 11: the lowest UNPROTECTED level
    assert party[pick].name != "ABRA"                                            # the build's Abra is protected
    abras, _ = _six("abra")
    for c in abras:
        c.name = "ABRA"
    assert full_party_slot(ctx, abras) is None                                   # only Abra-line members: nobody to give up


def test_full_party_slot_may_mark_the_abra_for_the_default_build(monkeypatch):
    from pokeagent.explorer.training_ctl import roster
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx: None)
    party, ctx = _six("")
    assert full_party_slot(ctx, party) == 2                                      # default build: the L10 Abra is the low man


def test_floor_verdict_is_the_same_with_or_without_an_abra_member():
    abra = _abra(10)
    without = [_tp_mon("STARMIE", 30), _tp_mon("CHARMELEON", 30), _tp_mon("RATTATA", 8)]
    for party in (without, without + [abra], [abra] + without):
        fl = team_floor.check("beat_misty", party, BOSS, SYN)
        assert fl is not None and fl.met and fl.have == 2 and fl.need == 2       # Abra is not sendable (Teleport does 0)
    weak = [_tp_mon("RATTATA", 19), _tp_mon("PIDGEY", 19), _tp_mon("WEEDLE", 5)]
    a, b = team_floor.check("beat_misty", weak, BOSS, SYN), team_floor.check("beat_misty", weak + [abra], BOSS, SYN)
    assert (a.met, a.have, a.need, a.text) == (b.met, b.have, b.need, b.text)


def test_build_key_names_the_abra_build():
    kb = {"name_of_internal": NAMES}
    fp = {"team": [{"species": ABRA_ID, "level": 10}, {"species": 177, "level": 14}]}
    key = team_fp.build_key(fp, kb)
    assert key.startswith("ABRA:") and "CHARMANDER:" in key
    band = team_fp.build_key({"team": [{"species": ABRA_ID, "level": 12}]}, kb)
    assert band == team_fp.build_key({"team": [{"species": ABRA_ID, "level": 10}]}, kb)  # same 5-level band
    assert team_fp.build_key({"team": [{"species": ABRA_ID, "level": 10}]}, kb) == "ABRA:L10"
