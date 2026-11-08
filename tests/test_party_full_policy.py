"""The full-party catch policy: a wanted catch at six members throws only when the catch plan marks a
release_candidate (lowest value, never the trainee, never a needed HM learner) and the box prompt then
answers YES. Synthetic ctx; no ROM, no emulator.
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer import catch_list
from pokeagent.explorer.behaviours import catch as catch_behav
from pokeagent.explorer.dialog import yesno_answer
from pokeagent.knowledge.party import Combatant


def _mon(name, level, moves=("TACKLE",)):
    return Combatant(name, level, ("NORMAL", "NORMAL"), 40, (30, 30, 30, 30), tuple(moves), (8,) * 5, (0,) * 5)


def _full_party():
    return [_mon("CHARMELEON", 25), _mon("ODDISH", 9), _mon("RATTATA", 8),
            _mon("PIDGEY", 12), _mon("SPEAROW", 10), _mon("WEEDLE", 7)]


def _ctx(trainee=None):
    return SimpleNamespace(train_member=trainee, emu=None, goals=lambda: {"beat_brock": False})


def test_full_party_slot_marks_the_lowest_value_member(monkeypatch):
    monkeypatch.setattr(catch_behav, "trainee_slot_for", lambda emu, named: None)
    monkeypatch.setattr(catch_list, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(catch_list, "hm_table", lambda: {})
    slot = catch_behav.full_party_slot(_ctx(), _full_party())
    assert slot == 6 - 1  # WEEDLE L7 is the weakest member


def test_full_party_slot_never_the_trainee_or_a_needed_learner(monkeypatch):
    party = _full_party()
    # the trainee (slot 5) and the team's only Cut learner (ODDISH slot 1) are protected;
    # the weakest remaining member is RATTATA L8 at slot 2
    monkeypatch.setattr(catch_behav, "trainee_slot_for", lambda emu, named: 5)
    monkeypatch.setattr(catch_list, "upcoming_needs", lambda goals: ["cut"])
    monkeypatch.setattr(catch_list, "hm_table", lambda: {"cut": {"ODDISH"}})
    assert catch_behav.full_party_slot(_ctx(), party) == 2


def test_full_party_slot_none_under_six_or_all_protected(monkeypatch):
    monkeypatch.setattr(catch_behav, "trainee_slot_for", lambda emu, named: None)
    monkeypatch.setattr(catch_list, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(catch_list, "hm_table", lambda: {})
    assert catch_behav.full_party_slot(_ctx(), _full_party()[:5]) is None  # not full yet


def test_box_prompt_yes_only_with_a_pending_release():
    q = "Want to deposit POKeMON? YES/NO"
    assert yesno_answer(q, release_pending=True)[0] == "YES"
    assert yesno_answer(q, release_pending=False)[0] == "NO"   # the default policy still refuses
    assert yesno_answer("Want to nickname it? YES/NO", release_pending=True)[0] == "NO"
