"""Readiness and training targets for every boss and rival fight, the under-level signal, and the trainer-battle outcome."""
from __future__ import annotations

from pokeagent.explorer import training
from pokeagent.explorer.grind import battle_outcome
from pokeagent.goals import GOALS
from pokeagent.knowledge import kb as kbmod
from pokeagent.knowledge import trainers
from pokeagent.knowledge.party import at_level
from test_knowledge import SYN, _starter  # noqa: F401  (synthetic cartridge: AQUA water, BLAZE fire, PEBBLE rock/ground)


def _after(last_done: str) -> dict:
    i = GOALS.index(last_done)
    return {g: n <= i for n, g in enumerate(GOALS)}


def _rom(monkeypatch, trainers_tbl):
    monkeypatch.setattr(kbmod, "ROM_KB", {**SYN, "trainers": trainers_tbl})
    training._cache.clear()


def test_every_boss_goal_has_a_boss_party_a_label_and_a_fallback_level():
    boss_goals = [*trainers.GYM_BOSSES, *trainers.LEADER_BOSSES, *trainers.RIVAL_BOSSES]
    for g in boss_goals:
        assert g in GOALS and g in training.BOSS_LABEL and g in training.TRAIN_LEVEL_BY_GOAL, g
    assert all(trainers.boss_party(g) for g in boss_goals) or not kbmod.ROM_KB   # real ROM tables (when present) cover all of them


def test_stage_goal_continues_past_misty():
    assert training.stage_goal(_after("heal_cerulean")) == "beat_misty"
    assert training.stage_goal(_after("beat_misty")) == "rival_ss_anne"
    assert training.stage_goal(_after("rival_ss_anne")) == "beat_surge"
    assert training.stage_goal(_after("beat_surge")) == "beat_erika"
    assert training.stage_goal(_after("beat_giovanni")) == "rival_route22"
    assert training.stage_goal(_after("beat_champion")) is None
    assert training.required_level(_after("beat_misty"), 8, None)[0] == 20     # fallback table, no party


def test_rival_ss_anne_readiness_from_synthetic_rival_party(monkeypatch):
    _rom(monkeypatch, {"RIVAL2": [[[19, "PEBBLE"], [20, "PEBBLE"]]] * 3})
    goals = _after("beat_misty")
    water = _starter("AQUA", 12, ["TACKLE", "WATER GUN"])
    weak = training.readiness_for(goals, [water])
    assert weak is not None and not weak.ready and weak.required > 12
    strong = training.readiness_for(goals, [at_level(water, 30, SYN)])
    assert strong.ready and "RIVAL (S.S. ANNE)" in strong.text


def test_rival_party_follows_our_starter_line():
    kb = {"trainers": {"RIVAL2": [[[19, "A"]], [[19, "B"]], [[19, "C"]], [[25, "D"]], [[25, "E"]], [[25, "F"]]]}}
    assert trainers.boss_party("rival_ss_anne", kb, ["WARTORTLE"]) == [(19, "C")]      # Squirtle line -> rival Charmander party
    assert trainers.boss_party("rival_ss_anne", kb, ["BULBASAUR"]) == [(19, "A")]
    assert trainers.boss_party("rival_pokemon_tower", kb, ["CHARMELEON"]) == [(25, "E")]
    assert trainers.boss_party("rival_ss_anne", kb, ["PIDGEY"]) == [(19, "A")]         # unknown starter: the strongest (first of a tie)
    assert trainers.boss_party("nonsense", kb) == []


def test_beat_surge_readiness_and_party_fight_counts_the_whole_party(monkeypatch):
    _rom(monkeypatch, {"LT.SURGE": [[[21, "PEBBLE"], [24, "PEBBLE"]]]})
    goals = _after("bicycle")
    water, fire = _starter("AQUA", 10, ["TACKLE", "WATER GUN"]), _starter("BLAZE", 10, ["TACKLE", "EMBER"])
    v_lead = training.readiness_for(goals, [water])
    assert v_lead is not None and not v_lead.ready
    v_both = training.readiness_for(goals, [water, fire])             # judged as a party, not the lead alone
    assert v_both.score >= v_lead.score
    assert training.readiness_for(goals, [at_level(water, 40, SYN)]).ready


def test_under_level_signal(monkeypatch):
    _rom(monkeypatch, {"LT.SURGE": [[[21, "PEBBLE"], [24, "PEBBLE"]]]})
    goals = _after("bicycle")
    water = _starter("AQUA", 10, ["TACKLE", "WATER GUN"])
    need, have, gap = training.under_level(goals, [water], 0)
    assert have == 10 and need > 10 and gap == need - have
    assert training.under_level_note(goals, [water]) == f"under-level for beat_surge: need L{need}, have L10"
    assert training.under_level(goals, [at_level(water, 40, SYN)], 0) is None
    assert training.under_level(goals, [], 0) is None
    assert training.under_level(_after("deliver_parcel"), [water], 0) is None  # before Route 2 only the floor level is asked
    assert training.under_level_note(goals, [at_level(water, 40, SYN)]) == ""


def test_trainer_win_is_not_lost_when_the_trainer_walks_us_off_the_tile():
    """2026-11-06, S.S. Anne 2F rooms: the fight chain moved us one tile and through a door; the record said lost."""
    start, end = (103, 2, 14), (103, 2, 13)
    assert battle_outcome(trainer=True, start=start, end=end, party_count=3) == (True, False)
    assert battle_outcome(trainer=True, start=start, end=(0x29, 3, 3), party_count=3) == (False, True)   # blackout: another map
    assert battle_outcome(trainer=False, start=start, end=start, party_count=3) == (True, False)
    assert battle_outcome(trainer=False, start=start, end=end, party_count=3) == (False, True)           # wild: exact-tile test kept
