"""Solo-viable grinding (synthetic kb + ledgers, no ROM/emulator): the encounter mix, the
win/margin bars, the choose() preference + nurse penalty + travel cap, and the trainee_out hook."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokeagent.explorer.behaviours import switch_out as so_mod
from pokeagent.explorer.training_ctl import roster
from pokeagent.grind import solo_viable as sv
from pokeagent.grind import stage_maps
from pokeagent.grind import points as gp
from pokeagent.knowledge.party import trainer_mon

SYN = {
    "moves": {"1": {"name": "EMBER", "type": "FIRE", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "2": {"name": "TACKLE", "type": "NORMAL", "power": 35, "accuracy": 1.0, "effect": 0, "pp": 35},
              "3": {"name": "WATER GUN", "type": "WATER", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "4": {"name": "SPLASH", "type": "NORMAL", "power": 0, "accuracy": 1.0, "effect": 0, "pp": 40}},
    "type_chart": [["FIRE", "BUG", 2.0], ["WATER", "FIRE", 2.0]],
    "species_by_dex": {
        "1": {"name": "CHARMELEON", "type1": "FIRE", "type2": "FIRE", "hp": 58, "atk": 64, "def": 58,
              "spd": 80, "spc": 65, "moves1": ["EMBER"]},
        "2": {"name": "WEEDLE", "type1": "BUG", "type2": "POISON", "hp": 40, "atk": 35, "def": 30,
              "spd": 50, "spc": 20, "moves1": ["TACKLE"]},
        "3": {"name": "PIDGEY", "type1": "NORMAL", "type2": "FLYING", "hp": 40, "atk": 45, "def": 40,
              "spd": 56, "spc": 35, "moves1": ["TACKLE"]},
        "4": {"name": "CATERPIE", "type1": "BUG", "type2": "BUG", "hp": 45, "atk": 30, "def": 35,
              "spd": 45, "spc": 20, "moves1": ["TACKLE"]},
        "5": {"name": "STARMIE", "type1": "WATER", "type2": "PSYCHIC", "hp": 60, "atk": 75, "def": 85,
              "spd": 115, "spc": 100, "moves1": ["WATER GUN"]},
        "6": {"name": "MAGIKARP", "type1": "WATER", "type2": "WATER", "hp": 20, "atk": 10, "def": 55,
              "spd": 80, "spc": 15, "moves1": ["SPLASH"]},
    },
    "learnsets": {},
    "wild_by_map": {
        "5": {"grass": [[3, "WEEDLE"], [5, "WEEDLE"], [4, "PIDGEY"], [3, "PIDGEY"], [4, "WEEDLE"],
                        [5, "PIDGEY"], [3, "CATERPIE"], [4, "CATERPIE"], [5, "WEEDLE"], [6, "PIDGEY"]]},
        "6": {"grass": [[8, "STARMIE"], [8, "STARMIE"], [9, "STARMIE"], [9, "STARMIE"], [10, "STARMIE"],
                        [10, "STARMIE"], [8, "STARMIE"], [9, "STARMIE"], [10, "STARMIE"], [10, "STARMIE"]]},
        "7": {"grass": []},
        "8": {"grass": [[3, "WEEDLE"], [3, "WEEDLE"], [4, "WEEDLE"], [4, "WEEDLE"], [5, "WEEDLE"],
                        [5, "WEEDLE"], [3, "PIDGEY"], [4, "PIDGEY"], [5, "PIDGEY"], [3, "CATERPIE"]]},
        "9": {"grass": [[3, "WEEDLE"]] * 10},
    },
}


def pt(map_id, band=(1, 99), prior=100.0, **kw):
    return gp.GrindPoint(map_id, name=f"MAP{map_id}", level_band=band, xp_per_min_prior=prior, **kw)


def test_encounter_mix_weights_sum_to_one_and_split_levels():
    mix = sv.encounter_mix(SYN, 5)
    assert sum(w for _, _, w in mix) == pytest.approx(1.0)
    d = {(sp, lv): w for sp, lv, w in mix}
    assert d[("WEEDLE", 3)] == pytest.approx(51 / 256)            # slot 0 alone
    assert d[("WEEDLE", 5)] == pytest.approx((51 + 11) / 256)      # slots 1 and 8 summed
    assert d[("WEEDLE", 4)] == pytest.approx(25 / 256)             # slot 4 is its OWN level
    assert d[("PIDGEY", 4)] == pytest.approx(39 / 256)            # the slot's own level, not a min/max split
    assert ("WEEDLE", 6) not in d and ("CATERPIE", 5) not in d    # no row at an unlisted level


def test_strong_trainee_is_viable_on_a_weak_map():
    trainee = trainer_mon("CHARMELEON", 12, SYN)
    wr, hp = sv.solo_verdict(trainee, SYN, 8)
    assert wr == 1.0 and hp >= sv.SOLO_MARGIN
    assert sv.is_solo_viable(trainee, SYN, 8) is True


def test_weak_trainee_is_not_viable_where_it_loses():
    assert sv.is_solo_viable(trainer_mon("WEEDLE", 4, SYN), SYN, 6) is False


def test_missing_data_is_not_viable():
    trainee = trainer_mon("CHARMELEON", 12, SYN)
    no_moves = {**SYN, "moves": {}}
    unknown = {**SYN, "wild_by_map": {"5": {"grass": [[5, "MISSINGNO"]] * 10}}}
    assert sv.solo_verdict(trainee, no_moves, 8) is None         # empty move table
    assert sv.solo_verdict(trainee, SYN, 7) is None              # empty map row
    assert sv.solo_verdict(trainee, unknown, 5) is None          # unknown species: never a guess
    assert sv.solo_verdict(None, SYN, 8) is None
    assert sv.is_solo_viable(trainee, no_moves, 8) is False
    assert sv.is_solo_viable(trainee, SYN, 7) is False
    assert sv.is_solo_viable(None, SYN, 8) is False


def test_magikarp_is_never_viable():
    karp = trainer_mon("MAGIKARP", 10, SYN)
    assert sv.solo_verdict(karp, SYN, 9) == (0.0, 0.0)           # SPLASH loses even the easiest map
    assert sv.is_solo_viable(karp, SYN, 9) is False              # stays on the switch trick


def test_threshold_boundaries(monkeypatch):
    w, m = sv.SOLO_MIN_WIN, sv.SOLO_MARGIN
    monkeypatch.setattr(sv, "solo_verdict", lambda *a: (w, m))
    assert sv.is_solo_viable(object(), {}, 1) is True            # exactly at both bars: viable
    monkeypatch.setattr(sv, "solo_verdict", lambda *a: (w - 0.001, m))
    assert sv.is_solo_viable(object(), {}, 1) is False           # just under the win bar
    monkeypatch.setattr(sv, "solo_verdict", lambda *a: (w, m - 0.001))
    assert sv.is_solo_viable(object(), {}, 1) is False           # just under the HP-margin bar


def test_retuned_constants_are_the_robert_2026_11_15_dial_step():
    assert (sv.SOLO_MIN_WIN, sv.SOLO_MARGIN) == (0.75, 0.10)


ROUTE1 = [[3, "PIDGEY"], [3, "RATTATA"], [3, "RATTATA"], [2, "RATTATA"], [2, "PIDGEY"], [3, "PIDGEY"],
          [3, "PIDGEY"], [4, "RATTATA"], [4, "PIDGEY"], [5, "PIDGEY"]]   # Route 1 (map 0x0C) as in the ROM
R1 = {**SYN, "species_by_dex": {
    "16": {"name": "PIDGEY", "type1": "NORMAL", "type2": "FLYING", "hp": 40, "atk": 45, "def": 40,
           "spd": 56, "spc": 35, "moves1": ["GUST"]},
    "19": {"name": "RATTATA", "type1": "NORMAL", "type2": "NORMAL", "hp": 30, "atk": 56, "def": 35,
           "spd": 72, "spc": 25, "moves1": ["TACKLE"]}},
    "moves": {**SYN["moves"], "16": {"name": "GUST", "type": "NORMAL", "power": 40, "accuracy": 1.0,
                                     "effect": 0, "pp": 35}},
    "wild_by_map": {"12": {"grass": ROUTE1}}}


@pytest.mark.parametrize("species", ["RATTATA", "PIDGEY"])
def test_level6_rattata_or_pidgey_fights_route_1_alone(species):
    assert sv.is_solo_viable(trainer_mon(species, 6, R1), R1, 12) is True


def test_choose_prefers_viable_point_over_higher_score():
    led = gp.GrindLedger({5: pt(5, prior=100), 6: pt(6, prior=60)})
    rank = sv.make_rank({6: (1.0, 0.9)}, {6: 0.0}, {}, None)
    assert gp.choose(led, [10], 20, None, {"maps": {}}, rank=rank).map_id == 6   # viable beats the higher score
    rank = sv.make_rank({5: (1.0, 0.9)}, {5: 0.0}, {}, None)
    assert gp.choose(led, [10], 20, None, {"maps": {}}, rank=rank).map_id == 5   # flip it: the high score wins


def test_choose_without_viable_is_unchanged():
    led = gp.GrindLedger({35: pt(35, prior=100), 36: pt(36, prior=80), 37: pt(37, band=(16, 30), prior=500)})
    assert gp.choose(led, [10], 20, None, rank=None).map_id == 35
    assert gp.choose(led, [10], 20, None).map_id == 35            # exactly today's answer


def test_nurse_penalty_scales_with_distance_and_hp_loss():
    assert sv.nurse_penalty(100.0, 0.9, 10) < sv.nurse_penalty(100.0, 0.3, 10)
    assert sv.nurse_penalty(100.0, 0.3, 10) < sv.nurse_penalty(100.0, 0.3, 500)
    assert 0 <= sv.nurse_penalty(100.0, 0.9, 10)
    assert sv.nurse_penalty(100.0, 0.3, sv.FAR_TRAVEL) == 100.0   # no known nurse: the cap
    assert sv.nurse_penalty(100.0, 0.0, 1e9) == 100.0             # never more than the xp/min itself


def test_travel_cap_excludes_far_viable_point_and_falls_back():
    chain = {str(i): {"warps": {"0,0,UP": [i + 1, 0, 0]}} for i in range(1, 12)}
    led = gp.GrindLedger({12: pt(12, prior=50), 2: pt(2, prior=100)})
    near = sv.make_rank({12: (1.0, 0.9)}, {12: 0.0}, chain, 11)   # one hop: inside the cap
    far = sv.make_rank({12: (1.0, 0.9)}, {12: 0.0}, chain, 1)     # eleven hops: 352 > MAX_TRAVEL_STEPS
    assert gp.choose(led, [10], 20, 11, chain, rank=near).map_id == 12   # in cap: the preference wins
    assert gp.choose(led, [10], 20, 1, chain, rank=far).map_id == 2      # past it: no preference
    solo = gp.GrindLedger({12: pt(12, prior=50)})
    assert gp.choose(solo, [10], 20, 1, chain, rank=far).map_id == 12    # alone: today's _best answer


def test_stage_allow_list_and_band_fallback_still_hold():
    maps = {"2": {"warps": {"1,1,UP": [0x0D, 3, 3]}}, "13": {"warps": {"3,3,DOWN": [2, 1, 1]}}}
    led = gp.GrindLedger({0x0D: pt(0x0D, prior=50.0), 0x3C: pt(0x3C, prior=500.0)})
    rank = sv.make_rank({0x3C: (1.0, 0.9)}, {0x3C: 0.0}, maps, 0x02)
    got = gp.choose(led, [9], 17, 0x02, maps, only_maps=stage_maps.allowed("beat_brock"), rank=rank)
    assert got.map_id == 0x0D                                      # viable but off the allow-list: never chosen
    out = pt(0x0D, band=(2, 6), prior=50.0)                          # out of band for the L9 trainee
    rank = sv.make_rank({0x0D: (1.0, 0.9)}, {0x0D: 0.0}, maps, 0x02)
    assert gp.choose(gp.GrindLedger({0x0D: out}), [9], 17, 0x02, maps,
                     only_maps=stage_maps.allowed("beat_brock"), rank=rank).map_id == 0x0D  # band fallback fires


def test_rank_for_gates_and_builds_a_working_rank():
    ours = [trainer_mon("CHARMELEON", 12, SYN), trainer_mon("STARMIE", 20, SYN)]
    pts = [pt(8, prior=50), pt(30, prior=100)]                      # 8: weak wilds; 30: no wild table
    args = (None, {}, None, (), 2)
    assert sv.rank_for(pts, ours, [12, 20], None, *args, kb=SYN) == (None, {})      # no trainee slot
    assert sv.rank_for(pts, ours, [12, 20], 1, *args, kb=SYN) == (None, {})         # slot 1 IS the fighter
    assert sv.rank_for(pts, ours[:1], [12, 20], 0, *args, kb=SYN) == (None, {})     # shifted indices: skip
    rank, viable = sv.rank_for(pts, ours, [12, 20], 0, *args, kb=SYN)
    assert rank is not None and viable[8][0] >= sv.SOLO_MIN_WIN and 30 not in viable
    led = gp.GrindLedger({8: pts[0], 30: pts[1]})
    assert gp.choose(led, [12, 20], 30, None, {"maps": {}}, trainee_slot=0, rank=rank).map_id == 8
    assert gp.choose(led, [12, 20], 30, None, {"maps": {}}, trainee_slot=0).map_id == 30


# --- trainee_out: the one fight-mode hook (4.3) ------------------------------------------------------------

def _trainee_ctx(monkeypatch, solo, frac, trainee=0):
    """A ctx where the trainee is the mon out at ``frac`` of its HP, under an episode flagged ``solo``."""
    ep = {"solo": solo}
    ctx = SimpleNamespace(battles=7, emu=None, _grind_state={"episode": ep})
    monkeypatch.setattr(roster, "trainee_slot", lambda c, **kw: trainee)
    monkeypatch.setattr(so_mod, "read_battle_mon",
                        lambda emu: SimpleNamespace(species=10, hp=int(frac * 40), max_hp=40, level=8))
    monkeypatch.setattr(so_mod, "party_species", lambda emu: [10, 11])
    monkeypatch.setattr(so_mod, "active_pos", lambda c: trainee)
    return ctx, ep


def test_trainee_out_stays_in_when_solo(monkeypatch):
    ctx, ep = _trainee_ctx(monkeypatch, True, 0.8)              # started >= 0.6, holding >= 0.25
    assert so_mod.trainee_out(ctx) is None                      # stays in: keeps the whole battle's XP
    assert ep["solo_battle"] == (7, True)
    monkeypatch.setattr(so_mod, "read_battle_mon",
                        lambda emu: SimpleNamespace(species=10, hp=8, max_hp=40, level=8))
    assert so_mod.trainee_out(ctx) == 0                         # dropped under 0.25 mid-battle: hands over

    ctx, ep = _trainee_ctx(monkeypatch, True, 0.5)              # started under SOLO_START_HP: latch False
    assert so_mod.trainee_out(ctx) == 0 and ep["solo_battle"] == (7, False)

    ctx, ep = _trainee_ctx(monkeypatch, False, 0.9)             # no solo flag: the switch trick as today
    assert so_mod.trainee_out(ctx) == 0 and "solo_battle" not in ep

    ctx = SimpleNamespace(battles=7, emu=None)                  # no episode at all
    monkeypatch.setattr(roster, "trainee_slot", lambda c, **kw: 0)
    monkeypatch.setattr(so_mod, "read_battle_mon",
                        lambda emu: SimpleNamespace(species=10, hp=32, max_hp=40, level=8))
    assert so_mod.trainee_out(ctx) == 0
