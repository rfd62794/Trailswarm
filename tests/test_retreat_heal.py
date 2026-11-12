"""retreat_heal: retreat to the nurse when the next likely fight costs too much HP, earlier when she is close."""
from __future__ import annotations

from dataclasses import replace

from pokeagent.explorer import retreat_risk as rr
from pokeagent.knowledge.party import trainer_mon
from pokeagent.procedures import after_victory_rules as av
from test_after_victory import SYN, _mon

WILD = {"PEBBLEMON": (10, 14, 1.0)}   # a one-species grass: the top level (14) sets the risk


def _lead(frac, level=12):
    return [_mon("AQUAMON", level, frac), _mon("AQUAMON", 12, 1.0)]


def test_floor_rises_as_the_nurse_gets_closer():
    assert rr.floor_for(300) == rr.FLOOR_NEAR and rr.floor_for(5000) == rr.FLOOR_FAR
    assert rr.floor_for(300) > rr.floor_for(1500) > rr.floor_for(2900)


def test_full_party_never_retreats():
    assert not rr.assess(_lead(1.0), WILD, 200, SYN).retreat


def test_unknown_or_far_nurse_never_retreats():
    hurt = [_mon("AQUAMON", 12, 0.1), _mon("AQUAMON", 12, 0.1)]
    assert not rr.assess(hurt, WILD, None, SYN).retreat
    assert not rr.assess(hurt, WILD, rr.MAX_WALK_FRAMES + 1, SYN).retreat


def test_hurt_lead_retreats_near_but_the_same_state_pushes_on_far():
    """A lead the worst wild duel leaves between the two floors: a short walk retreats, a long trek does not."""
    party = [_mon("AQUAMON", 12, 0.5), _mon("AQUAMON", 12, 1.0)]
    foes = rr._worst_wild(WILD, SYN)
    from pokeagent.knowledge.readiness import _chart, duel
    from pokeagent.knowledge.kb import table
    left = duel(party[0], float(party[0].hp), foes[0], float(foes[0].hp), _chart(SYN), table(SYN, "moves"))[0] / rr._max_hp(party[0], SYN)
    assert rr.FLOOR_FAR < left < rr.FLOOR_NEAR, left   # fixture sanity: this is the band where distance decides
    assert rr.assess(party, WILD, 300, SYN).retreat
    assert not rr.assess(party, WILD, rr.FAR_FRAMES, SYN).retreat


def test_low_party_total_always_retreats_when_a_nurse_is_known():
    party = [_mon("AQUAMON", 12, 0.2), _mon("AQUAMON", 12, 0.2)]
    assert rr.assess(party, {}, 3500, SYN).retreat


def test_fainted_lead_with_a_healthy_second_is_judged_on_the_second():
    party = [replace(_mon("AQUAMON", 12), hp=0), _mon("AQUAMON", 12, 1.0)]
    assert not rr.assess(party, WILD, 300, SYN).retreat


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
    monkeypatch.setattr(rh, "assess", lambda party, wild, walk, kb=None: rr.assess(party, WILD, walk, SYN))
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
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=16)          # 40%: nobody fainted or poisoned
    ctx.step = 0
    presses = [_beat(ctx) for _ in range(12)]
    walk = of(ctx).get("walk")
    assert walk is not None and walk["min_frac"] == heal_walk.RETREAT_DONE
    assert any(d is not None and d.rule == "heal_walk" for d in presses)
    rows = (tmp_path / "status_care.jsonl").read_text().count("heal_walk_start")
    assert rows == 1                                         # no start/healed/start spam
    assert "heal_walk_healed" not in (tmp_path / "status_care.jsonl").read_text()


def test_walk_ends_once_the_nurse_has_healed_and_a_slightly_hurt_party_does_not_loop(tmp_path, monkeypatch):
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=16)
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
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=16)
    heal_walk.start(ctx, "after_victory", heal_walk.RETREAT_DONE)
    for _ in range(5):
        StatusCare().step(ctx)
    assert of(ctx).get("walk") is not None                   # before the fix: "healed" on step one


def test_route_distance_is_cached_between_evaluations(tmp_path, monkeypatch):
    ctx = _chain_ctx(tmp_path, monkeypatch, hp=16)
    calls = []
    monkeypatch.setattr(outside_use, "walk_to_center", lambda c, get=None: calls.append(1) or (16 * 20, 0, 0x40))
    ctx.step = 100
    for _ in range(3):
        rh.RetreatHeal._walk_frames(ctx)
        ctx.step += 1
    assert len(calls) == 1
