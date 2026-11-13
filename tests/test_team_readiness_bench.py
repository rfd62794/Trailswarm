"""Team readiness with a useless bench member (Misty 2026-11-12: "KAKUNA L4 -> L26 (lead L26)" for 6,000 steps).
SYNTHETIC: the test_team_plan cartridge plus a KAKUNA that knows no damaging move."""
from __future__ import annotations

import copy

from pokeagent.explorer.training import train_member_for
from pokeagent.knowledge import team_plan
from pokeagent.knowledge.readiness import team_readiness
from test_team_plan import SYN as BASE, _mon as _base_mon, _sp
from pokeagent.explorer.stats import stat_value
from pokeagent.knowledge.party import Combatant

SYN = copy.deepcopy(BASE)
SYN["species_by_dex"]["12"] = _sp("KAKUNA", "BUG", "POISON", 45, 25, 50, 35, 25, ["HARDEN"])
SYN["learnsets"]["KAKUNA"] = {"learnset": []}


def mon(name, level):
    if name != "KAKUNA":
        return _base_mon(name, level)
    row = SYN["species_by_dex"]["12"]
    return Combatant(name, level, ("BUG", "POISON"), stat_value(row["hp"], 8, 0, level, hp=True),
                     tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc")), ("HARDEN",), (8,) * 5, (0,) * 5)


HARD = [(26, "STARYU"), (30, "STARMIE")]   # water bosses a half-HP L26 Charmeleon cannot beat alone
PARTY = lambda: [mon("CHARMELEON", 26), mon("KAKUNA", 4)]  # noqa: E731


def test_a_bench_member_the_sim_never_sends_in_is_not_weakest():
    t = team_readiness(PARTY(), HARD, "MISTY", SYN)
    assert t is not None and t.ready is False
    assert t.weakest is None
    assert t.members[1].flips is False


def test_the_reason_is_printed_and_no_target_tracks_the_lead():
    t = team_readiness(PARTY(), HARD, "MISTY", SYN)
    assert "KAKUNA" not in t.text and "L26 -> L26" not in t.text
    assert "lead needs L" in t.text or "hurt lead loses" in t.text
    assert all(m.target <= 26 for m in t.members)   # capped at a reachable level (the lead's)


def test_hold_and_train_member_agree():
    party = PARTY()
    nv = team_plan.boss_need(party, HARD, SYN, "MISTY")
    t = team_readiness(party, HARD, "MISTY", SYN)
    assert nv is not None and not nv.ready          # the gate holds
    slot = train_member_for(nv, t)
    assert slot != 1                                 # never the Kakuna
    assert slot == (nv.raise_slot if nv.raise_slot is not None else nv.lead_slot)
    assert nv.level_by_slot.get(1) is None           # raising the Kakuna alone cannot flip boss_need


def test_train_member_falls_back_to_the_lead_when_no_raise_flips_it():
    nv = team_plan.Need(False, -1.0, 0, {0: None, 1: None}, None, None, 40, (), "x")
    assert train_member_for(nv, None) == 0


def test_open_gate_keeps_the_team_goal_steering():
    nv = team_plan.Need(True, 0.9, 0, {}, None, None, 26, (), "ready")
    assert train_member_for(nv, None) is None


def test_a_useful_second_member_is_still_named():
    from test_team_readiness import BOSS, SYN as TSYN, _mon
    t = team_readiness([_mon("AQUA", 26), _mon("MAGIKARP", 13)], BOSS, "TWO-MON", TSYN)
    assert t.weakest is not None and t.weakest.name == "MAGIKARP" and "hurt lead loses" in t.text
