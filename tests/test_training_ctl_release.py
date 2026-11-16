"""Trainee release (synthetic kb/ctx, no ROM): the (slot, map) verdict, probation, revoke, bounds."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer import grind as xg
from pokeagent.explorer.behaviours import switch_out as so_mod
from pokeagent.explorer.stats import stat_value
from pokeagent.explorer.training_ctl import release, roster
from pokeagent.grind import solo_viable
from pokeagent.grind.xpmath import xp_gain, xp_needed
from pokeagent.knowledge import team_floor
from pokeagent.knowledge.party import Combatant

SYN = {
    "moves": {"1": {"name": "TACKLE", "type": "NORMAL", "power": 35, "accuracy": 1.0, "effect": 0, "pp": 35},
              "2": {"name": "QUICK ATTACK", "type": "NORMAL", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 30},
              "3": {"name": "SPLASH", "type": "NORMAL", "power": 0, "accuracy": 1.0, "effect": 0, "pp": 40},
              "4": {"name": "WATER GUN", "type": "WATER", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25}},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0]],
    "species_by_dex": {
        "16": {"name": "PIDGEY", "type1": "NORMAL", "type2": "FLYING", "hp": 40, "atk": 45, "def": 40,
               "spd": 56, "spc": 35, "base_exp": 50, "growth": "MEDIUM_SLOW", "moves1": ["TACKLE"]},
        "19": {"name": "RATTATA", "type1": "NORMAL", "type2": "NORMAL", "hp": 30, "atk": 56, "def": 35,
               "spd": 72, "spc": 25, "base_exp": 51, "growth": "MEDIUM_FAST", "moves1": ["TACKLE", "QUICK ATTACK"]},
        "13": {"name": "WEEDLE", "type1": "BUG", "type2": "POISON", "hp": 40, "atk": 35, "def": 30,
               "spd": 50, "spc": 20, "base_exp": 39, "growth": "MEDIUM_FAST", "moves1": ["TACKLE"]},
        "129": {"name": "MAGIKARP", "type1": "WATER", "type2": "WATER", "hp": 20, "atk": 10, "def": 55,
                "spd": 80, "spc": 15, "base_exp": 40, "growth": "SLOW", "moves1": ["SPLASH"]},
        "74": {"name": "GEODUDE", "type1": "ROCK", "type2": "GROUND", "hp": 40, "atk": 80, "def": 100,
               "spd": 20, "spc": 30, "base_exp": 86, "growth": "MEDIUM_SLOW", "moves1": ["TACKLE", "WATER GUN"]},
        "95": {"name": "ONIX", "type1": "ROCK", "type2": "GROUND", "hp": 35, "atk": 45, "def": 160,
               "spd": 70, "spc": 30, "base_exp": 108, "growth": "MEDIUM_SLOW", "moves1": ["TACKLE"]},
    },
    "learnsets": {},
    "wild_by_map": {
        "12": {"grass_rate": 25, "grass": [[3, "PIDGEY"], [3, "RATTATA"], [2, "PIDGEY"], [2, "RATTATA"],
                                          [4, "PIDGEY"], [4, "RATTATA"], [3, "PIDGEY"], [5, "RATTATA"],
                                          [4, "PIDGEY"], [5, "RATTATA"]]},
        "13": {"grass_rate": 25, "grass": [[2, "RATTATA"], [2, "WEEDLE"], [3, "RATTATA"], [3, "WEEDLE"],
                                           [3, "PIDGEY"], [4, "WEEDLE"], [2, "RATTATA"], [4, "PIDGEY"],
                                           [5, "RATTATA"], [4, "WEEDLE"]]},
        "51": {"grass_rate": 8, "grass": [[3, "WEEDLE"], [4, "WEEDLE"], [3, "WEEDLE"], [5, "WEEDLE"],
                                          [4, "WEEDLE"], [6, "WEEDLE"], [3, "WEEDLE"], [4, "WEEDLE"],
                                          [5, "WEEDLE"], [6, "WEEDLE"]]},
        "33": {"grass_rate": 8, "grass": [[2, "RATTATA"], [3, "RATTATA"], [2, "PIDGEY"], [3, "PIDGEY"],
                                          [4, "RATTATA"], [4, "PIDGEY"], [5, "RATTATA"], [5, "PIDGEY"],
                                          [4, "RATTATA"], [5, "PIDGEY"]]},
    },
}


def _mon(name, level, moves=None):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    mv = tuple(row["moves1"]) if moves is None else tuple(moves)
    return Combatant(name, level, tuple(dict.fromkeys((row["type1"], row["type2"]))), hp, st,
                     mv, (8,) * 5, (0,) * 5)


def _ctx(team, m=12, step=100):
    ctx = SimpleNamespace(emu=SimpleNamespace(), view=SimpleNamespace(m=m), step=step,
                          train_member=None, mem=SimpleNamespace(data={"maps": {}}), logs=[])
    ctx.log = lambda t, tag=None: ctx.logs.append(t)
    ctx.pos = lambda: (ctx.view.m, 1, 1)
    return ctx


def _patch(monkeypatch, team, slot=0, kb=SYN):
    """release's emulator/kb reads pinned to the synthetic fixtures."""
    monkeypatch.setattr(release, "ROM_KB", kb)
    monkeypatch.setattr(release, "our_party", lambda emu, kb=None: team)
    monkeypatch.setattr(release, "read_party",
                        lambda emu: [SimpleNamespace(level=c.level, hp=c.hp, max_hp=c.hp) for c in team])
    monkeypatch.setattr(release, "trainee_slot_for", lambda emu, named, b=(), wild=None: slot)


def test_strong_trainee_released_weak_is_not(monkeypatch):
    team = [_mon("RATTATA", 6)]
    ctx = _ctx(team)
    _patch(monkeypatch, team)
    assert release.verdict(ctx, 0, 12)
    assert any("released" in ln for ln in ctx.logs)
    weak = [_mon("WEEDLE", 2)]
    _patch(monkeypatch, weak)
    assert not release.verdict(_ctx(weak), 0, 12)


def test_missing_data_is_not_released(monkeypatch):
    team = [_mon("RATTATA", 6)]
    ctx = _ctx(team)
    _patch(monkeypatch, team)
    assert not release.verdict(ctx, 0, 99)                       # no wild table for the map
    _patch(monkeypatch, team, kb={})
    assert not release.verdict(ctx, 0, 12)                       # empty moves and encounter table
    _patch(monkeypatch, [])
    assert not release.verdict(ctx, 0, 12)                       # no party row at all
    _patch(monkeypatch, [_mon("RATTATA", 6, moves=())])
    assert not release.verdict(ctx, 0, 12)                       # an empty move list never wins
    kb = {**SYN, "wild_by_map": {"12": {"grass_rate": 25, "grass": [[3, "MISSINGNO"]] * 10}}}
    _patch(monkeypatch, team, kb=kb)
    assert not release.verdict(ctx, 0, 12)                       # an unknown species is never a guess
    _patch(monkeypatch, [_mon("MAGIKARP", 5)])
    assert not release.verdict(ctx, 0, 12)                       # Magikarp never stands alone


def test_probation_drops_a_losing_release(monkeypatch):
    team = [_mon("RATTATA", 6)]
    ctx = _ctx(team)
    _patch(monkeypatch, team)
    for i in range(release.PROBATION_FIGHTS):
        release.note_battle(ctx, 0, 12, won=i < 2, hp_left=0.6, fainted=False, blackout=False)
    assert not release.verdict(ctx, 0, 12)                       # 2/3 observed < MIN_OBS_WIN
    assert any("dropped" in ln for ln in ctx.logs)


def test_faint_revokes_then_re_releases(monkeypatch):
    team = [_mon("RATTATA", 6)]
    ctx = _ctx(team)
    _patch(monkeypatch, team)
    assert release.verdict(ctx, 0, 12)
    release.note_battle(ctx, 0, 12, won=False, hp_left=0.0, fainted=True, blackout=False)
    assert not release.verdict(ctx, 0, 12)                       # revoked for the cooldown
    assert any("revoked (fainted)" in ln for ln in ctx.logs)
    ctx.step += release.REVOKE_COOLDOWN
    assert release.verdict(ctx, 0, 12)                           # cooldown over: re-released


def test_release_state_is_per_slot_and_map_and_bounded(monkeypatch):
    team = [_mon("RATTATA", 6), _mon("PIDGEY", 8)]
    ctx = _ctx(team)
    _patch(monkeypatch, team)
    release.note_battle(ctx, 0, 12, won=False, hp_left=0.0, fainted=True, blackout=False)
    assert not release.verdict(ctx, 0, 12)                       # revoked on Route 1
    assert release.verdict(ctx, 1, 12)                           # a different slot: unaffected
    assert release.verdict(ctx, 0, 33)                           # a different map: unaffected
    for _ in range(release.KEEP_FIGHTS + 2):
        release.note_battle(ctx, 1, 12, won=True, hp_left=0.8, fainted=False, blackout=False)
    assert len(ctx.__dict__["release"][(1, 12)]["fights"]) == release.KEEP_FIGHTS


def test_trainee_out_stays_in_when_released(monkeypatch):
    """The Level_Banded episode hook generalised: a released trainee (train_route path too, no
    episode live) stands alone at >= SWITCH_MIN_HP; below it or unreleased the switch stays."""
    ctx = SimpleNamespace(emu=SimpleNamespace(read=lambda a: 1), battles=1)
    monkeypatch.setattr(roster, "trainee_slot", lambda c, **k: 1)
    monkeypatch.setattr(so_mod, "read_battle_mon", lambda emu: SimpleNamespace(hp=30, max_hp=30, species=0x99))
    monkeypatch.setattr(so_mod, "party_species", lambda emu: [0x85, 0x99])
    monkeypatch.setattr(so_mod, "active_pos", lambda c: 1)
    monkeypatch.setattr(roster, "released", lambda c, s: True)
    assert so_mod.trainee_out(ctx) is None                       # released: stands alone
    monkeypatch.setattr(so_mod, "read_battle_mon", lambda emu: SimpleNamespace(hp=6, max_hp=30, species=0x99))
    assert so_mod.trainee_out(ctx) == 1                          # 6/30 < SWITCH_MIN_HP: pulled
    monkeypatch.setattr(so_mod, "read_battle_mon", lambda emu: SimpleNamespace(hp=30, max_hp=30, species=0x99))
    monkeypatch.setattr(roster, "released", lambda c, s: False)
    assert so_mod.trainee_out(ctx) == 1                          # not released (a Magikarp never is): switch


def test_floor_still_held_with_release_active(monkeypatch):
    """3.3: release live AND the floor unmet - the gate and the stall cap stand; constants pinned."""
    team = [_mon("RATTATA", 6), _mon("PIDGEY", 5)]
    ctx = _ctx(team)
    _patch(monkeypatch, team)
    assert release.verdict(ctx, 0, 12)                           # the release is live
    floor = team_floor.check("beat_brock", team, [(12, "GEODUDE"), (14, "ONIX")], SYN)
    assert floor is not None and not floor.met and floor.have == 0  # 0 of 2 sendable members at L12
    assert not team_floor.ready(SimpleNamespace(ready=True), floor)  # the gate stays shut
    assert xg.stall_hold_holds({}, "without a level gain", 10, 0, floor_unmet=True)
    assert xg.STALL_HOLD_CAP == 6000 and xg.FLOOR_CAP_MULT == 3 and xg.FLOOR_BLACKOUTS == 10
    assert team_floor.FLOOR_BY_GOAL["beat_brock"] == 12 and team_floor.TEAM_FLOOR_MEMBERS == 2


def test_level5_and_6_trainees_released_on_pre_brock_route(monkeypatch):
    """Robert 2026-11-15: a full-HP Rattata/Pidgey at L5-6 stands alone on a pre-Brock route
    (wild L2-5). Merged constants: SOLO_MIN_WIN 0.75, SOLO_MARGIN 0.10."""
    for lvl, sp in ((5, "RATTATA"), (6, "RATTATA"), (5, "PIDGEY"), (6, "PIDGEY")):
        team = [_mon(sp, lvl)]
        ctx = _ctx(team)
        _patch(monkeypatch, team)
        sv = solo_viable.solo_verdict(team[0], SYN, 12)
        assert sv is not None and solo_viable.passes(sv), f"{sp} L{lvl}: {sv}"
        assert release.verdict(ctx, 0, 12)
        print(f"\n[sim] {sp} L{lvl} on Route 1: win {sv[0]:.2f}, hp_left {sv[1]:.2f}")


def test_monotone_model_full_xp_beats_switch_trick():
    """The arithmetic behind the independence claim: full XP (1 participant) needs fewer fights
    to reach the floor than the switch trick (2 participants) on the same encounter mix."""
    mix = solo_viable.encounter_mix(SYN, 12)
    base = {r["name"]: r["base_exp"] for r in SYN["species_by_dex"].values()}
    need = xp_needed("MEDIUM_FAST", 8, 12)
    solo = need / sum(w * xp_gain(base[sp], lv, participants=1) for sp, lv, w in mix)
    shared = need / sum(w * xp_gain(base[sp], lv, participants=2) for sp, lv, w in mix)
    assert solo < shared and shared == 2 * solo
