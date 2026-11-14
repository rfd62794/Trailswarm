"""The full-party catch policy: a wanted catch at six members throws only when the catch plan marks a
release_candidate (lowest value, never the trainee, never a needed HM learner) and the box prompt then
answers YES. Synthetic ctx; no ROM, no emulator.
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer import catch_list
from pokeagent.explorer.behaviours import catch as catch_behav
from pokeagent.explorer.dialog import yesno_answer
from pokeagent.explorer.training_ctl import roster
from pokeagent.knowledge.party import Combatant


def _mon(name, level, moves=("TACKLE",)):
    return Combatant(name, level, ("NORMAL", "NORMAL"), 40, (30, 30, 30, 30), tuple(moves), (8,) * 5, (0,) * 5)


def _full_party():
    return [_mon("CHARMELEON", 25), _mon("ODDISH", 9), _mon("RATTATA", 8),
            _mon("PIDGEY", 12), _mon("SPEAROW", 10), _mon("WEEDLE", 7)]


def _ctx(trainee=None):
    return SimpleNamespace(train_member=trainee, emu=None, goals=lambda: {"beat_brock": False})


def test_full_party_slot_marks_the_lowest_value_member(monkeypatch):
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx, **kw: None)
    monkeypatch.setattr(catch_list, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(catch_list, "hm_table", lambda: {})
    slot = catch_behav.full_party_slot(_ctx(), _full_party())
    assert slot == 6 - 1  # WEEDLE L7 is the weakest member


def test_full_party_slot_never_the_trainee_or_a_needed_learner(monkeypatch):
    party = _full_party()
    # the trainee (slot 5) and the team's only Cut learner (ODDISH slot 1) are protected;
    # the weakest remaining member is RATTATA L8 at slot 2
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx, **kw: 5)
    monkeypatch.setattr(catch_list, "upcoming_needs", lambda goals: ["cut"])
    monkeypatch.setattr(catch_list, "hm_table", lambda: {"cut": {"ODDISH"}})
    assert catch_behav.full_party_slot(_ctx(), party) == 2


def test_full_party_slot_none_under_six_or_all_protected(monkeypatch):
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx, **kw: None)
    monkeypatch.setattr(catch_list, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(catch_list, "hm_table", lambda: {})
    assert catch_behav.full_party_slot(_ctx(), _full_party()[:5]) is None  # not full yet


def test_box_prompt_yes_only_with_a_pending_release():
    q = "Want to deposit POKeMON? YES/NO"
    assert yesno_answer(q, release_pending=True)[0] == "YES"
    assert yesno_answer(q, release_pending=False)[0] == "NO"   # the default policy still refuses
    assert yesno_answer("Want to nickname it? YES/NO", release_pending=True)[0] == "NO"


def test_the_pending_mark_only_lifts_a_deposit_pokemon_prompt():
    # UNVERIFIED wording (none is recorded): the match is narrow - a prompt about something else,
    # even one naming a box, keeps its own answer while the mark is pending.
    assert yesno_answer("Want to deposit ITEMS? YES/NO", release_pending=True)[0] == "NO"
    assert yesno_answer("The BOX is full! Want to release POKeMON? YES/NO", release_pending=True)[0] == "NO"


def test_release_pending_lives_for_one_battle_only(tmp_path):
    """set -> the deposit prompt gets YES during the fight -> cleared when it ends (and a stale mark
    is dropped at the next battle's start); a later 'box' prompt is back to its own answer."""
    from pokeagent.emulator import FakeEmulator
    from pokeagent.explorer.behaviours.battle import Battle
    from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
    from pokeagent.explorer.memory import MapMemory
    from pokeagent.knowledge import team_plan
    emu = FakeEmulator({0xD35E: 0x28, 0xD362: 5, 0xD361: 6, 0xD057: 1, 0xD163: 6})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, stable_frames=10)
    ctx.refresh()
    Battle().step(ctx)                                          # battle 1 opens
    st = team_plan.of(ctx)
    st["release_pending"] = {"species": "PIDGEY", "slot": 5, "battle": ctx.battles}
    pending = lambda: bool(team_plan.of(ctx).get("release_pending"))
    assert yesno_answer("Want to deposit POKeMON? YES/NO", release_pending=pending())[0] == "YES"
    emu.set(0xD057, 0); ctx.refresh()
    Battle().step(ctx)                                          # the catch resolved: the mark is spent
    assert team_plan.of(ctx).get("release_pending") is None
    st["release_pending"] = {"species": "X", "slot": 0, "battle": ctx.battles}  # a mark left over somehow
    emu.set(0xD057, 1); ctx.refresh()
    Battle().step(ctx)                                          # the next battle clears it too
    assert team_plan.of(ctx).get("release_pending") is None
    assert yesno_answer("Want to deposit POKeMON? YES/NO", release_pending=pending())[0] == "NO"
