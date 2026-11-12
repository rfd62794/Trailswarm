"""The slot-0 lead migration: every reader that used to act on party slot 0 now follows the party view's
lead / fighter rule - a fainted lead means the SECOND mon, everywhere, and a healthy lead changes nothing."""
from __future__ import annotations

import json

from pokeagent.campaign import party_knows_move
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import item_use as iu
from pokeagent.explorer.behaviours.bring_out import able_slot
from pokeagent.explorer.behaviours.cave_topup import fighter_slot
from pokeagent.explorer.item_policies import policy, rare_candy
from pokeagent.explorer.item_policies.view import Mon, fighter_slot_of
from pokeagent.explorer.perceive import true_lead_level
from pokeagent.goals import party_full
from pokeagent.intervene.extra import _our_mon
from pokeagent.knowledge.party import Combatant
from pokeagent.legs.states import calm
from pokeagent.magikarp import MAGIKARP, fighter
from pokeagent.procedures import predicates
from test_party_view import mem

SP1, SP2 = 0x99, 0x9A
FAINTED = [(SP1, 18, 0, 35), (SP2, 14, 25, 32)]   # fainted lead, live second
HEALTHY = [(SP1, 18, 30, 35), (SP2, 14, 25, 32)]


def _ctx(tmp_path, memory):
    from test_status_care_behaviour import make_ctx
    ctx = make_ctx(tmp_path, memory)
    ctx.run_dir = tmp_path / "run"      # grind_atlas.json is read from run_dir's parent
    return ctx


def test_the_three_fighter_readers_agree_on_six_parties():
    cases = [("healthy lead", HEALTHY, 0),
             ("fainted lead", FAINTED, 1),
             ("magikarp lead", [(MAGIKARP, 5, 9, 9), (SP1, 18, 30, 51), (SP2, 9, 9, 40)], 1),
             ("magikarp second", [(SP1, 18, 30, 51), (MAGIKARP, 5, 9, 9), (SP2, 9, 9, 40)], 0),
             ("all fainted", [(SP1, 18, 0, 35), (SP2, 14, 0, 32)], 0),
             ("single mon", [(SP1, 18, 30, 35)], 0)]
    for name, mons, want in cases:
        emu = FakeEmulator(mem(mons))
        plain = [Mon(i, "MAGIKARP" if sp == MAGIKARP else f"#{sp}", lv, (), hp, mx)
                 for i, (sp, lv, hp, mx) in enumerate(mons)]
        assert fighter_slot(emu) == want, name
        assert fighter_slot_of(plain) == want, name
        assert fighter(emu) == tuple(mons[want]), name


def test_able_slot_sends_out_the_second_mon_behind_a_fainted_lead():
    assert able_slot(FakeEmulator(mem(FAINTED))) == 1
    assert able_slot(FakeEmulator(mem(HEALTHY))) == 0                                   # healthy lead: unchanged
    assert able_slot(FakeEmulator(mem([(SP1, 18, 0, 35), (SP2, 14, 0, 32)]))) is None   # nobody left


def test_item_use_with_an_empty_party_view_still_returns_the_raw_slot_press(tmp_path):
    from test_item_use import make_ctx
    ctx = make_ctx(tmp_path, {iu.PLAYER_MON: 2, iu.MENU_ITEM: 0})    # no party bytes: the view is empty
    d = iu.item_step(ctx, ["Use item on which", "POKeMON?"], "", 0x14, "POTION", "t")
    assert (d.button, d.rule) == ("DOWN", "item_party_pick")         # the raw wPlayerMonNumber read, as before


def test_item_use_picks_the_fighters_slot_behind_a_fainted_lead(tmp_path):
    from test_item_use import make_ctx
    ctx = make_ctx(tmp_path, {iu.MENU_ITEM: 0, **mem(FAINTED)})
    d = iu.item_step(ctx, ["Use item on which", "POKeMON?"], "", 0x14, "POTION", "t")
    assert (d.button, d.rule) == ("DOWN", "item_party_pick")         # cursor 0, the fighter is slot 1
    ctx = make_ctx(tmp_path, {iu.MENU_ITEM: 0, **mem(HEALTHY)})
    d = iu.item_step(ctx, ["Use item on which", "POKeMON?"], "", 0x14, "POTION", "t")
    assert d.button == "A"                                           # healthy lead: slot 0, as before


def test_intervene_our_mon_reports_the_fighter_when_the_battle_struct_is_stale():
    emu = FakeEmulator(mem(FAINTED, in_battle=1, battle=(0, 6, 15, 21), player_mon=0))
    got = _our_mon(emu)
    assert (got["level"], got["hp"], got["max"]) == (14, 25, 32)       # slot 1, not slot 0 or the stale struct
    healthy = FakeEmulator(mem(HEALTHY, in_battle=1, battle=(0, 6, 15, 21)))
    got = _our_mon(healthy)
    assert (got["level"], got["hp"], got["max"]) == (18, 30, 35)       # healthy lead: slot 0, as before


def test_goals_party_full_and_legs_calm_see_a_fainted_member():
    down = FakeEmulator(mem(FAINTED))
    assert not party_full(down) and not calm(down, False)
    full = FakeEmulator(mem([(SP1, 18, 35, 35), (SP2, 14, 32, 32)]))
    assert party_full(full) and calm(full, False)
    hurt = FakeEmulator(mem(HEALTHY))                                   # 30/35 hurt, nobody down
    assert not party_full(hurt) and calm(hurt, False)


def test_predicates_hp_reads_zero_on_the_fighters_max_while_a_member_is_down():
    assert predicates._party_hp(FakeEmulator(mem(FAINTED))) == (0, 32)
    assert predicates._party_hp(FakeEmulator(mem(HEALTHY))) == (30, 35)


def test_true_lead_level_is_the_fighters_level():
    assert true_lead_level(FakeEmulator(mem(FAINTED))) == 14
    assert true_lead_level(FakeEmulator(mem(HEALTHY))) == 18


def test_campaign_party_move_check_reads_every_slot():
    m = mem(HEALTHY)
    for i, mv in enumerate((15, 0, 0, 0)):
        m[0xD173 + 44 + i] = mv                                          # slot 1 knows CUT (move 15)
    emu = FakeEmulator(m)
    assert party_knows_move(emu, 15) and not party_knows_move(emu, 33)


def test_policy_grind_minutes_is_keyed_by_the_fighter(tmp_path):
    """_grind_minutes reads the atlas entry for the fighter's name+level: a fainted lead keys on slot 1."""
    atlas = {"LEADMON": {"beat_brock": {"18": [{"steps_to_goal": 9000}]}},
             "SECONDMON": {"beat_brock": {"14": [{"steps_to_goal": 450}]}}}
    (tmp_path / "grind_atlas.json").write_text(json.dumps({"atlas": atlas}), encoding="utf-8")
    party = [Combatant("LEADMON", 18, (), 0, (), ()), Combatant("SECONDMON", 14, (), 0, (), ())]
    got = policy._grind_minutes(_ctx(tmp_path, mem(FAINTED)), {}, party)
    assert got == 450 / rare_candy.STEPS_PER_MIN                          # slot 1's name and level, not slot 0's
    got = policy._grind_minutes(_ctx(tmp_path, mem(HEALTHY)), {}, party)
    assert got == 9000 / rare_candy.STEPS_PER_MIN                         # healthy lead: unchanged


def test_xitems_battle_scores_best_move_on_the_first_living_combatant(tmp_path, monkeypatch):
    """A fainted lead behind a live second in a trainer fight: best_move is judged on the second."""
    from pokeagent.explorer import training
    from pokeagent.explorer.item_policies import ids
    from pokeagent.explorer.item_policies import xitems_battle as xb
    from pokeagent.knowledge import party as kparty
    from pokeagent.knowledge import readiness as kread
    lead, second = Combatant("LEADMON", 18, (), 0, (), ()), Combatant("SECONDMON", 14, (), 0, (), ())
    seen = []
    monkeypatch.setattr(kparty, "our_party", lambda emu, kb=None: [lead, second])
    monkeypatch.setattr(policy, "next_boss", lambda goals, party: [second])
    monkeypatch.setattr(training, "readiness_for", lambda goals, party: None)
    monkeypatch.setattr(kread, "best_move", lambda a, b, ch, mv: (seen.append(a), (0, "X"))[1])
    m = mem(FAINTED, in_battle=2, battle=(SP2, 14, 25, 32), player_mon=1)
    m.update({0xD31D: 1, 0xD31E: ids.X_ATTACK, 0xD31F: 1})
    xb._decide(_ctx(tmp_path, m), 2)
    assert seen == [second]


def test_menu_learn_prompt_weighs_the_fighters_moves(tmp_path, monkeypatch):
    """The 'delete a move to make room' YES/NO sees the fighter's moves, not slot 0's."""
    from pokeagent.explorer.behaviours import menu as menu_mod
    from test_battle_types import put_box
    m = mem(FAINTED)
    for i, mv in enumerate((1, 2, 3, 4)):
        m[0xD173 + i] = mv                    # slot 0's moves (the fainted lead)
    for i, mv in enumerate((33, 45)):
        m[0xD173 + 44 + i] = mv               # the fighter's moves
    ctx = _ctx(tmp_path, m)
    put_box(ctx, ["PIKACHU wants to", "LEARN TACKLE!", "make room?", ">YES", "NO"])
    ctx.refresh()
    got = []
    monkeypatch.setattr(menu_mod, "ROM_KB", {"moves": {"33": {"name": "TACKLE"}, "45": {"name": "GROWL"},
                                                     "1": {"name": "ONE"}, "2": {"name": "TWO"},
                                                     "3": {"name": "THREE"}, "4": {"name": "FOUR"}}})
    monkeypatch.setattr(menu_mod, "learn_decision",
                        lambda context, cur, needed: (got.append(list(cur)), ("NO", "x", None))[1])
    d = menu_mod.Menu().step(ctx)
    assert d is not None and got == [["TACKLE", "GROWL"]]
