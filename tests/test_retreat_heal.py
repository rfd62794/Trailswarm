"""retreat_heal: retreat to the nurse when the next likely fight costs too much HP, earlier when she is close."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from pokeagent.explorer import retreat_risk as rr
from pokeagent.knowledge.party import trainer_mon
from pokeagent.procedures import after_victory_rules as av
from test_after_victory import SYN, _mon

WILD = {"PEBBLEMON": (10, 14, 1.0)}   # a one-species grass: the top level (14) sets the risk


def _lead(frac, level=12):
    return [_mon("AQUAMON", level, frac), _mon("AQUAMON", 12, 1.0)]


def test_floor_rises_as_the_nurse_gets_closer():
    assert rr.survive_margin(300) == rr.SURVIVE_NEAR and rr.survive_margin(5000) == rr.SURVIVE_FAR
    assert rr.survive_margin(300) > rr.survive_margin(1500) > rr.survive_margin(2900)


def test_full_party_never_retreats():
    assert not rr.assess(_lead(1.0), WILD, 200, SYN).retreat


def test_unknown_or_far_nurse_never_retreats():
    hurt = [_mon("AQUAMON", 12, 0.1), _mon("AQUAMON", 12, 0.1)]
    assert not rr.assess(hurt, WILD, None, SYN).retreat
    assert not rr.assess(hurt, WILD, rr.MAX_WALK_FRAMES + 1, SYN).retreat


def test_hurt_lead_retreats_near_but_the_same_state_pushes_on_far():
    """A lead the worst wild duel leaves between the two margins: a short walk retreats, a long trek does not."""
    party = [_mon("AQUAMON", 12, 0.12), _mon("AQUAMON", 8, 1.0)]   # the L8 bench keeps 0% vs the L14 foe: it never carries
    foes = rr._worst_wild(WILD, SYN)
    from pokeagent.knowledge.readiness import _chart, duel
    from pokeagent.knowledge.kb import table
    left = duel(party[0], float(party[0].hp), foes[0], float(foes[0].hp), _chart(SYN), table(SYN, "moves"))[0] / rr._max_hp(party[0], SYN)
    assert rr.SURVIVE_FAR < left < rr.SURVIVE_NEAR, left   # fixture sanity: this is the band where distance decides
    assert rr.assess(party, WILD, 300, SYN).retreat
    assert not rr.assess(party, WILD, rr.FAR_FRAMES, SYN).retreat


def test_low_party_total_always_retreats_when_a_nurse_is_known():
    party = [_mon("AQUAMON", 12, 0.1), _mon("AQUAMON", 12, 0.1)]
    assert rr.assess(party, {}, 3500, SYN).retreat


def test_fainted_lead_with_a_healthy_second_is_judged_on_the_second():
    party = [replace(_mon("AQUAMON", 12), hp=0), _mon("AQUAMON", 12, 1.0)]
    assert not rr.assess(party, WILD, 300, SYN).retreat


def test_retreat_heal_uses_the_fighter_slot_with_a_magikarp_lead(tmp_path):
    """Magikarp in slot 0, the strong mon in slot 1: the hurt check judges the fighter, not the trainee in front."""
    mem = {}
    put_mon(mem, 0, 133, 5, 20, 20)       # the Magikarp trainee leads, full HP (internal id 133)
    put_mon(mem, 1, 153, 14, 16, 40)      # the fighter behind it
    ctx = make_ctx(tmp_path, mem)
    hurt = [SimpleNamespace(hp=20, max_hp=20), SimpleNamespace(hp=16, max_hp=40)]
    assert RetreatHeal._hurt(ctx, hurt)                      # slot 1 at 40%: under the 80% lead gate
    fit = [SimpleNamespace(hp=20, max_hp=20), SimpleNamespace(hp=36, max_hp=40)]
    assert not RetreatHeal._hurt(ctx, fit)                   # slot 1 at 90%: the gates are not tripped


# --- after_victory: a close nurse makes "push" need a healthier party ---
BOSS = [[(12, "PEBBLEMON"), (14, "PEBBLEMON")]]


def test_after_victory_heals_instead_of_pushing_at_63_percent_lead_41_percent_party_near_a_center():
    party = [_mon("AQUAMON", 30, 0.63), _mon("AQUAMON", 28, 0.2)]
    d = av.decide(party, BOSS, {}, (900, 0, 58), SYN)
    assert d.action == "heal"


def test_after_victory_still_pushes_when_healthy_or_the_center_is_far():
    healthy = [_mon("AQUAMON", 30, 0.9), _mon("AQUAMON", 28, 0.9)]
    assert av.decide(healthy, BOSS, {}, (900, 0, 58), SYN).action == "push"
    hurt = [_mon("AQUAMON", 30, 0.63), _mon("AQUAMON", 28, 0.2)]
    assert av.decide(hurt, BOSS, {}, (3000, 0, 58), SYN).action == "push"


# --- the real chain: RetreatHeal requests, StatusCare carries out (review of #206) ---
import pytest

from pokeagent.explorer import heal_walk
from pokeagent.explorer.behaviours import retreat_heal as rh
from pokeagent.explorer.behaviours.retreat_heal import RetreatHeal
from pokeagent.explorer.behaviours.status_care import StatusCare
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.status_care import of
from test_status_care_behaviour import _road_to_center, make_ctx, put_mon


def _chain_ctx(tmp_path, monkeypatch, hp, mx=40, frames=16 * 20):
    mem = {}
    put_mon(mem, 0, 153, 14, hp, mx)           # one living, unpoisoned member
    ctx = make_ctx(tmp_path, mem)
    _road_to_center(ctx)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda c, get=None: (frames, 0, 0x40))
    monkeypatch.setattr(rh, "party_now", lambda emu: [_mon("AQUAMON", 12, hp / mx)])
    monkeypatch.setattr(rh, "assess", lambda party, wild, walk, kb=None, fighter_idx=0: rr.assess(party, WILD, walk, SYN, fighter_idx))
    return ctx


def _beat(ctx):
    """One engine beat: RetreatHeal (if it applies) then StatusCare (if it applies)."""
    ctx.step += 1
    for b in (RetreatHeal(), StatusCare()):
        if b.applies(ctx):
            d = b.step(ctx)
            if d is not None:
                return d
    return None


def test_a_retreat_walk_survives_a_standing_hurt_party_and_presses_toward_the_nurse(tmp_path, monkeypatch):
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=4)           # 10%: nobody fainted or poisoned
    ctx.step = 0
    presses = [_beat(ctx) for _ in range(12)]
    walk = of(ctx).get("walk")
    assert walk is not None and walk["min_frac"] == heal_walk.RETREAT_DONE
    assert any(d is not None and d.rule == "heal_walk" for d in presses)
    rows = (tmp_path / "status_care.jsonl").read_text().count("heal_walk_start")
    assert rows == 1                                         # no start/healed/start spam
    assert "heal_walk_healed" not in (tmp_path / "status_care.jsonl").read_text()


def test_walk_ends_once_the_nurse_has_healed_and_a_slightly_hurt_party_does_not_loop(tmp_path, monkeypatch):
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=4)
    ctx.step = 0
    for _ in range(5):
        _beat(ctx)
    assert of(ctx).get("walk") is not None
    ctx.emu.set(0xD16C, 0); ctx.emu.set(0xD16D, 40)         # the nurse: lead back to 40/40
    ctx.refresh()
    _beat(ctx)
    assert of(ctx).get("walk") is None and of(ctx)["healed_at"] > 0
    ctx.emu.set(0xD16D, 36)                                  # one grind fight later: 90%, then 75% still inside the gates' cooldown
    for _ in range(40):
        _beat(ctx)
    assert of(ctx).get("walk") is None
    ctx.emu.set(0xD16D, 30)                                  # 75% lead: under the gate but inside AFTER_HEAL
    ctx.refresh()
    for _ in range(40):
        _beat(ctx)
    assert of(ctx).get("walk") is None


def test_near_full_party_never_starts_a_retreat(tmp_path, monkeypatch):
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=39)           # 97%
    ctx.step = 0
    for _ in range(30):
        _beat(ctx)
    assert of(ctx).get("walk") is None


def test_after_victory_heal_walk_also_holds_until_the_party_is_back_up(tmp_path, monkeypatch):
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=4)
    heal_walk.start(ctx, "after_victory", heal_walk.RETREAT_DONE)
    for _ in range(5):
        StatusCare().step(ctx)
    assert of(ctx).get("walk") is not None                   # before the fix: "healed" on step one


def test_route_distance_is_cached_between_evaluations(tmp_path, monkeypatch):
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=4)
    calls = []
    monkeypatch.setattr(outside_use, "walk_to_center", lambda c, get=None: calls.append(1) or (16 * 20, 0, 0x40))
    ctx.step = 100
    for _ in range(3):
        rh.RetreatHeal._walk_frames(ctx)
        ctx.step += 1
    assert len(calls) == 1


def test_trainee_mode_fighter_at_10_percent_retreats_though_the_magikarp_lead_is_full(tmp_path, monkeypatch):
    mem = {}
    put_mon(mem, 0, 133, 5, 20, 20)     # slot 0: the Magikarp in training (internal id 133), full HP
    put_mon(mem, 1, 153, 14, 4, 40)     # the fighter at 10%
    put_mon(mem, 2, 153, 10, 4, 40)     # a weak bench: nobody can carry the next fight
    ctx = make_ctx(tmp_path, mem)
    _road_to_center(ctx)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda c, get=None: (16 * 20, 0, 0x40))
    monkeypatch.setattr(rh, "party_now", lambda emu: [_mon("AQUAMON", 5, 1.0), _mon("AQUAMON", 12, 0.1), _mon("AQUAMON", 12, 0.1)])
    monkeypatch.setattr(rh, "assess", lambda party, wild, walk, kb=None, fighter_idx=0: rr.assess(party, WILD, walk, SYN, fighter_idx))
    ctx.step = 0
    for _ in range(5):
        _beat(ctx)
    assert of(ctx).get("walk") is not None


# --- survival rule: retreat only when NO living member keeps the margin ---
def _left(c):
    return rr._kept([c], WILD, SYN)[0][1]


def test_a_fighter_keeping_26_percent_does_not_retreat_near_a_nurse():
    lead = _mon("AQUAMON", 12, 0.27)
    assert 0.2 < _left(lead) < 0.3
    assert not rr.assess([lead], WILD, 300, SYN).retreat


def test_a_fighter_keeping_nothing_with_a_healthy_bench_does_not_retreat_and_the_carrier_is_named():
    weak = _mon("AQUAMON", 5, 0.1)
    weak = replace(weak, hp=1)
    bench = replace(_mon("AQUAMON", 12, 1.0), name="PEBBLEMON")
    assert _left(weak) < rr.SURVIVE_FAR
    v = rr.assess([weak, bench], WILD, 300, SYN)
    assert not v.retreat and "PEBBLEMON would carry the fight" in v.why


def test_an_all_weak_party_retreats():
    party = [_mon("AQUAMON", 12, 0.12), _mon("AQUAMON", 8, 1.0), _mon("AQUAMON", 8, 1.0)]   # total HP is fine; nobody keeps the margin
    assert all(_left(c) < rr.SURVIVE_NEAR for c in party)
    v = rr.assess(party, WILD, 300, SYN)
    assert v.retreat and "no party member keeps" in v.why


def test_no_wild_table_falls_back_to_hp_fractions_against_the_margin():
    assert rr.assess([_mon("AQUAMON", 12, 0.10)], {}, 300, SYN).retreat
    assert not rr.assess([_mon("AQUAMON", 12, 0.22)], {}, 300, SYN).retreat
