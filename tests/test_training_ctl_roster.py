"""Training controller slice 4 (Roster): roster.trainee_slot is the one trainee-selection owner;
the monotonic faint counter that replaces the fainted bit in party_order.team_sig."""
from __future__ import annotations

import inspect
import subprocess
import sys
from types import SimpleNamespace

from pokeagent.emulator import FakeEmulator
# behaviours.* first: trainee_gate -> heal_walk -> behaviours/__init__ -> grind_drill -> trainee_gate
# is a pre-existing cycle on main; it only bites when trainee_gate is imported before behaviours.
from pokeagent.explorer.behaviours import catch as catch_behav
from pokeagent.explorer.behaviours import party_order as po
from pokeagent.explorer.behaviours import switch_out as so_mod
from pokeagent.explorer import catch_list, grind_episode, trainee_gate
from pokeagent.explorer.training_ctl import roster
from pokeagent.knowledge import team_plan
from pokeagent.knowledge.party import Combatant
from pokeagent.magikarp import MAGIKARP, trainee_slot_for
from test_magikarp import party_mem
from test_party_full_policy import _ctx as _catch_ctx, _full_party, _mon


def _ctx(emu, train_member=None, step=100):
    return SimpleNamespace(emu=emu, train_member=train_member, step=step)


def test_roster_trainee_slot_equals_trainee_slot_for():
    karp = FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (0xB1, 18, 51, 51)]))
    ctx = _ctx(karp, 1)
    assert roster.trainee_slot(ctx) == trainee_slot_for(karp, 1) == 0          # the Magikarp always wins

    weak = FakeEmulator(party_mem([(0xB1, 30, 79, 79), (0x54, 9, 20, 20)]))
    ctx = _ctx(weak, 1)
    assert roster.trainee_slot(ctx) == trainee_slot_for(weak, 1) == 1          # the named weak member
    ctx = _ctx(weak, None)
    assert roster.trainee_slot(ctx) == trainee_slot_for(weak, None) is None    # nobody named, no breakers

    team_plan.of(ctx)["breakers"] = (1,)
    assert roster.trainee_slot(ctx, breakers=True) == trainee_slot_for(weak, None, (1,)) == 1
    assert roster.trainee_slot(ctx) is None                                    # breakers=False: the old read


def test_migrated_modules_do_not_mention_trainee_slot_for():
    for mod in (catch_behav, so_mod, grind_episode, trainee_gate):
        assert "trainee_slot_for" not in inspect.getsource(mod), mod.__name__


def test_roster_and_its_callers_import_in_a_fresh_process():
    # behaviours.* first: trainee_gate -> heal_walk -> behaviours/__init__ -> grind_drill -> trainee_gate
    # is a pre-existing cycle on main; it only bites when trainee_gate is imported before behaviours.
    r = subprocess.run([sys.executable, "-c",
                        "import pokeagent.explorer.behaviours.catch, pokeagent.explorer.behaviours.switch_out, "
                        "pokeagent.explorer.training_ctl.roster, pokeagent.explorer.grind_episode, "
                        "pokeagent.explorer.trainee_gate"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --- slice 4b1: the monotonic faint counter in team_sig ------------------------------------------------------

CHARMELEON = 0xB2
HEALTHY = [(0x54, 9, 20, 20), (CHARMELEON, 16, 50, 50)]
DOWN = [(0x54, 9, 0, 20), (CHARMELEON, 16, 50, 50)]      # slot 0 fainted
TRIO = [(0x54, 9, 20, 20), (0x55, 12, 30, 30), (CHARMELEON, 16, 50, 50)]
TRIO_DOWN = [(0x54, 9, 0, 20), (0x55, 12, 30, 30), (CHARMELEON, 16, 50, 50)]


def _order_ctx(mons, step=100):
    return SimpleNamespace(emu=FakeEmulator(party_mem(mons)), step=step)


def test_a_level_up_reorders_again():
    ctx = _order_ctx([HEALTHY[1], HEALTHY[0]])                                # strong first: a swap is wanted
    team_plan.of(ctx)["order_hold"] = (ctx.step - 12, po.team_sig(ctx))
    assert po.want_home(ctx) is None                                          # held
    ctx.emu = FakeEmulator(party_mem([(CHARMELEON, 16, 50, 50), (0x54, 10, 22, 22)]))
    ctx.step += 1
    assert po.team_sig(ctx) != team_plan.of(ctx)["order_hold"][1]             # the team changed
    assert po.want_home(ctx) is not None                                      # a reorder fires


def test_a_real_faint_bumps_the_counter_and_reorders():
    ctx = _order_ctx(TRIO)
    team_plan.of(ctx)["order_hold"] = (ctx.step, po.team_sig(ctx))
    ctx.emu = FakeEmulator(party_mem(TRIO_DOWN))                              # slot 0 faints: it belongs last
    ctx.step += 1
    assert roster.note_faints(ctx) == 1                                       # alive -> fainted counted
    assert not po._held(ctx)
    assert po.want_home(ctx) is not None                                      # fainted member last: reorder


def test_a_heal_revive_keeps_the_hold():
    ctx = _order_ctx(HEALTHY)
    po.team_sig(ctx)                                                          # baseline: nobody down
    ctx.emu = FakeEmulator(party_mem(DOWN))
    ctx.step += 1
    sig_fainted = po.team_sig(ctx)                                            # the faint counted
    team_plan.of(ctx)["order_hold"] = (ctx.step, sig_fainted)
    ctx.emu = FakeEmulator(party_mem(HEALTHY))                                # the revive: hp 0 -> alive
    ctx.step += 1
    assert po.team_sig(ctx) == sig_fainted                                    # monotonic: never back down
    assert po._held(ctx)                                                      # the 2026-11-13 incident stays dead


def test_a_pure_slot_permutation_changes_nothing():
    ctx = _order_ctx(HEALTHY)
    sig0, n0 = po.team_sig(ctx), roster.note_faints(ctx)
    ctx.emu = FakeEmulator(party_mem([HEALTHY[1], HEALTHY[0]]))               # same members, other order
    ctx.step += 1
    assert po.team_sig(ctx) == sig0 and roster.note_faints(ctx) == n0


def test_the_hold_never_expires():
    ctx = _order_ctx(HEALTHY)
    team_plan.of(ctx)["order_hold"] = (ctx.step - 5000, po.team_sig(ctx))
    assert po._held(ctx)                                                      # no 300-step expiry ever returns


def test_note_faints_counts_once_per_step():
    ctx = _order_ctx(HEALTHY)
    roster.note_faints(ctx)                                                   # baseline
    ctx.emu = FakeEmulator(party_mem(DOWN))
    ctx.step += 1
    assert roster.note_faints(ctx) == 1
    assert roster.note_faints(ctx) == 1                                       # same step: the stored value
    assert team_plan.of(ctx)["faints"] == 1


def test_a_member_fainting_twice_counts_twice():
    ctx = _order_ctx(HEALTHY)
    roster.note_faints(ctx)
    ctx.emu = FakeEmulator(party_mem(DOWN))
    ctx.step += 1
    assert roster.note_faints(ctx) == 1
    ctx.emu = FakeEmulator(party_mem(HEALTHY))
    ctx.step += 1
    assert roster.note_faints(ctx) == 1                                       # the heal never subtracts
    ctx.emu = FakeEmulator(party_mem(DOWN))
    ctx.step += 1
    assert roster.note_faints(ctx) == 2                                       # a second faint counts again


# --- slice 4b2: prefer evolving a WEEDLE (it keeps Poison Sting through Beedrill) -----------------------------

def _com(name, level):
    return Combatant(name, level, ("NORMAL",), 30, (10,) * 4, ("TACKLE",), (8,) * 5, (0,) * 5)


def test_a_trainable_weedle_wins_over_the_named_member_and_a_breaker():
    party = [_com("CHARMELEON", 25), _com("WEEDLE", 5), _com("RATTATA", 8)]
    assert team_plan.trainee_slot(party, named=2) == 1                        # beats the named weak member
    assert team_plan.trainee_slot(party, named=None, breakers=(2,)) == 1      # ... and a band breaker
    two = [_com("CHARMELEON", 25), _com("WEEDLE", 6), _com("WEEDLE", 5)]
    assert team_plan.trainee_slot(two, named=None) == 2                       # the lowest-level one


def test_a_weedle_at_beedrill_level_or_the_strongest_is_not_chosen():
    party = [_com("CHARMELEON", 25), _com("WEEDLE", 10), _com("RATTATA", 8)]
    assert team_plan.trainee_slot(party, named=2) == 2                        # L10: the old rule answers
    lead = [_com("WEEDLE", 5), _com("CHARMELEON", 5)]
    assert team_plan.trainee_slot(lead, named=None) is None                   # never the strongest member


def test_a_kakuna_is_never_the_trainee_by_this_rule():
    party = [_com("CHARMELEON", 25), _com("KAKUNA", 4), _com("RATTATA", 8)]
    assert team_plan.trainee_slot(party, named=2) == 2                        # falls through to the old logic
    assert team_plan.trainee_slot(party, named=None) is None


def test_our_kakuna_with_poison_sting_stays_the_trainee():
    ours = Combatant("KAKUNA", 7, ("BUG",), 30, (10,) * 4, ("POISON STING", "STRING SHOT", "HARDEN"), (8,) * 5, (0,) * 5)
    party = [_com("CHARMELEON", 25), ours, _com("RATTATA", 8)]
    assert team_plan.trainee_slot(party, named=2) == 1                        # evolved from our Weedle
    kb = {"name_of_internal": {"113": "KAKUNA"}, "moves": {"40": {"name": "POISON STING"}, "106": {"name": "HARDEN"}}}
    ram = [SimpleNamespace(species=113, level=7, hp=20, moves=(40, 106, 0, 0)), _com("CHARMELEON", 25)]
    assert team_plan.trainee_slot(ram, named=None, kb=kb) == 0                # RAM move ids resolve too
    wild = [SimpleNamespace(species=113, level=7, hp=20, moves=(106, 0, 0, 0)), _com("CHARMELEON", 25)]
    assert team_plan.trainee_slot(wild, named=None, kb=kb) is None            # Harden only: not ours


def test_full_party_keeps_our_evolved_kakuna(monkeypatch):
    _patch_catch(monkeypatch)
    party = _full_party()
    party[5] = _mon("KAKUNA", 9, ("POISON STING", "STRING SHOT", "HARDEN"))
    assert catch_behav.full_party_slot(_catch_ctx(), party) == 2              # RATTATA L8, the old rule


def test_the_rule_matches_a_ram_member_through_name_of_internal():
    kb = {"name_of_internal": {"112": "WEEDLE"}}                              # a PartyMon: species id, no .name
    party = [SimpleNamespace(species=112, level=5, hp=20), _com("CHARMELEON", 25)]
    assert team_plan.trainee_slot(party, named=None, kb=kb) == 0
    assert team_plan.trainee_slot(party, named=None, kb={}) is None           # no table: no match, old logic


# --- slice 4b3: a wild KAKUNA in the party is the deposit pick --------------------------------------------------

def _six_with_kakuna():
    p = _full_party()
    p[5] = _mon("KAKUNA", 7, ("HARDEN",))                                     # a wild one: Harden only
    return p


def _patch_catch(monkeypatch, trainee=None, needs=(), hm=None):
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx, **kw: trainee)
    monkeypatch.setattr(catch_list, "upcoming_needs", lambda goals: list(needs))
    monkeypatch.setattr(catch_list, "hm_table", lambda: hm or {})


def test_full_party_marks_the_kakuna_over_a_lower_level_member(monkeypatch):
    _patch_catch(monkeypatch)
    party = _six_with_kakuna()                                                # KAKUNA L7, RATTATA L8
    assert catch_behav.full_party_slot(_catch_ctx(), party) == 5              # the Kakuna, not the lower level


def test_full_party_never_marks_the_trainee_even_when_it_is_a_kakuna(monkeypatch):
    _patch_catch(monkeypatch, trainee=5)
    assert catch_behav.full_party_slot(_catch_ctx(), _six_with_kakuna()) == 2  # protected: RATTATA L8 marks


def test_full_party_without_a_kakuna_keeps_the_lowest_level_choice(monkeypatch):
    _patch_catch(monkeypatch)
    assert catch_behav.full_party_slot(_catch_ctx(), _full_party()) == 5      # WEEDLE L7: the old answer


def test_full_party_hm_protection_still_wins(monkeypatch):
    _patch_catch(monkeypatch, needs=["cut"], hm={"cut": {"KAKUNA"}})
    assert catch_behav.full_party_slot(_catch_ctx(), _six_with_kakuna()) == 2  # the needed learner stays
