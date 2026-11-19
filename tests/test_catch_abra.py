"""catch_abra (--build abra): the goal's settle rule, the flee-species turn-1 throw, the build want,
and the full-party/floor/build-key guards. Synthetic fixtures (test_catch_policy's table; party_mem
fakes for RAM), no ROM.
"""
from __future__ import annotations

import json

import pytest
from dataclasses import replace
from types import SimpleNamespace

from pokeagent import team_fp
from pokeagent.abra_goal import (ABRA_STEP_CAP, BALLS_MIN, abra_stage, box_species,
                                 catch_abra_settled, resolve_build)
from pokeagent.campaign import goal_ids
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import press_goals
from pokeagent.explorer.behaviours import Catch, Restock
from pokeagent.explorer.behaviours import catch as catch_mod
from pokeagent.explorer.behaviours.abra_hunt import ABRA_WANT, AbraHunt
from pokeagent.explorer.behaviours.battle import BattleView
from pokeagent.explorer.behaviours.catch import full_party_slot
from pokeagent.explorer.catch_list import catch_wanted
from pokeagent.explorer.economy.shopping import ball_need
from pokeagent.knowledge import team_floor
from pokeagent.knowledge.catch_policy import CatchStep
from pokeagent.knowledge.flee_catch import flee_on_turn
from pokeagent.knowledge.party import Combatant
from pokeagent.goals import GOALS, check_goals
from test_catch_policy import ALL_BALLS, _decide, _mon
from test_catch_seam import _ctx
from test_magikarp import bcd, party_mem
from test_team_floor import BOSS
from test_team_inventory import make_ctx
from test_team_plan import SYN, _mon as _tp_mon

ABRA_ID, KADABRA_ID, ALAKAZAM_ID = 148, 38, 149   # name_of_internal ids in the NAMES fake below
NAMES = {"148": "ABRA", "38": "KADABRA", "149": "ALAKAZAM", "177": "CHARMANDER"}


def _abra(level=10, hp=None):
    m = Combatant("ABRA", level, ("PSYCHIC",), 30, (20, 20, 40, 20), ("TELEPORT",), (8,) * 5, (0,) * 5)
    return m if hp is None else replace(m, hp=hp)


def _st(build="abra", **extra):
    return {"opts": SimpleNamespace(build=build), **extra}


def _emu(mons=((177, 14, 30, 30),), money=0, balls=None):
    mem = {**party_mem(list(mons)), **bcd(money)}
    if balls is not None:  # {item_id: qty} into the bag slots (0xD31D count + 0xD31E pairs)
        items = list(balls.items())
        mem[0xD31D] = len(items)
        for i, (it, q) in enumerate(items):
            mem[0xD31E + 2 * i], mem[0xD31E + 2 * i + 1] = it, q
    return FakeEmulator(mem)


def _set(emu: FakeEmulator, mem: dict) -> None:
    for a, v in mem.items():
        emu.set(a, v)


# --- flee_on_turn / the catch policy's flee rule --------------------------------------------------------------------

def test_flee_on_turn_marks_flee_species_and_all_flee_moves():
    assert flee_on_turn("ABRA", ()) and flee_on_turn("ABRA", ("TACKLE",))   # species table: any moves
    assert flee_on_turn("ZUBAT", ("ROAR", "WHIRLWIND"))                    # every known move a battle-ender
    assert flee_on_turn("PIDGEY", ("TELEPORT",))
    assert not flee_on_turn("PIDGEY", ("TACKLE",)) and not flee_on_turn("PIDGEY", ())
    assert flee_on_turn(None, ("TELEPORT",))                                     # nameless but all-flee: still throws first


def test_flee_species_throws_on_turn_one_never_weakens():
    abra = _abra(10)
    step = _decide(_mon("AQUA", 10), abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=0)
    assert step.kind == "throw" and step.ball                                    # 100% HP: still a throw
    assert "flee" in step.why
    again = _decide(_mon("AQUA", 10), abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=1)
    assert again.kind == "throw"                                                 # a failed throw: throw again
    hurt = _decide(_mon("AQUA", 10), abra, 5, abra.hp, rate=200, bag=ALL_BALLS, turn=3)
    assert hurt.kind == "throw" and hurt.ball                                    # never a damage_move, any HP
    pidgey = _mon("PIDGEY", 10)
    non_flee = _decide(_mon("AQUA", 10), pidgey, pidgey.hp, pidgey.hp, rate=45, turn=0)
    assert non_flee.kind != "throw" or "flee" not in non_flee.why                # non-flee: unchanged rules


def test_flee_species_first_turn_may_status_instead():
    singer = _mon("SINGER", 9)                                                   # knows only SLEEP POWDER
    abra = _abra(10)
    step = _decide(singer, abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=0)
    assert step.kind in ("status_move", "throw")                                 # status MAY run on the first turn
    if step.kind == "status_move":
        assert step.move == "SLEEP POWDER"
    already = _decide(singer, abra, abra.hp, abra.hp, rate=200, bag=ALL_BALLS, turn=0, status="sleep")
    assert already.kind == "throw"                                               # never re-status an afflicted mon


# --- catch_abra_settled ----------------------------------------------------------------------------------------------

def test_goal_settles_for_any_build_but_abra():
    assert catch_abra_settled(_emu(), _st(""), set(), {"name_of_internal": NAMES})
    assert catch_abra_settled(_emu(), _st("gyarados"), set(), {"name_of_internal": NAMES})
    assert not catch_abra_settled(_emu(money=3000), _st("abra"), set(), {"name_of_internal": NAMES})


def test_goal_opens_until_an_abra_line_member_is_in_the_party():
    emu = _emu(((177, 14, 30, 30),), money=3000, balls={4: 15})
    st = _st("abra")
    assert not catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})   # open: nobody yet
    _set(emu, party_mem([(177, 14, 30, 30), (ABRA_ID, 10, 25, 25)]))
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES}) and st["had_abra"]
    _set(emu, party_mem([(177, 14, 30, 30)]))
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})       # sticky: depositing does not reopen


def test_kadabra_and_alakazam_count_too():
    for sp in (KADABRA_ID, ALAKAZAM_ID):
        emu = _emu(((177, 14, 30, 30),), money=3000)
        st = _st("abra")
        assert not catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})   # the start pool
        _set(emu, party_mem([(177, 14, 30, 30), (sp, 20, 40, 40)]))                 # gained this run
        assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})


def test_goal_settles_on_the_step_cap_and_only_when_no_balls_no_money():
    """"0 balls AND no money for one" is the ONLY out-of-resources settle: short of BALLS_MIN but
    able to buy, or broke with balls still in the bag, the goal stays open - it shops or hunts on."""
    emu = _emu(money=3000)
    st = _st("abra", abra_skipped=True)
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})       # ABRA_STEP_CAP spent
    assert catch_abra_settled(_emu(money=0), _st("abra"), set(), {"name_of_internal": NAMES})      # no ball, no money
    assert catch_abra_settled(_emu(money=100), _st("abra"), set(), {"name_of_internal": NAMES})    # under a ball's price
    st2 = _st("abra")
    assert not catch_abra_settled(_emu(money=3000), st2, set(), {"name_of_internal": NAMES})       # 0 balls but a buy is affordable
    assert not catch_abra_settled(_emu(money=0, balls={4: 3}), _st("abra"), set(),
                                {"name_of_internal": NAMES})                                     # broke but 3 throws left: hunt on
    assert not catch_abra_settled(_emu(money=3000, balls={4: BALLS_MIN - 1}), _st("abra"), set(),
                                {"name_of_internal": NAMES})                                     # short of the stock: restock first
    assert not catch_abra_settled(_emu(money=0, balls={4: BALLS_MIN}), _st("abra"), set(),
                                {"name_of_internal": NAMES})


def test_check_goals_wires_catch_abra_between_team_ready_and_to_bill():
    assert GOALS.index("catch_abra") == GOALS.index("team_ready") + 1
    assert GOALS.index("to_bill") == GOALS.index("catch_abra") + 1
    g = check_goals(_emu(money=3000), _st("abra"))
    assert g["catch_abra"] is False                                            # open under the build
    assert check_goals(_emu(money=3000), {})["catch_abra"]                     # settled for the default build


def test_constants_named():
    from pokeagent.explorer import restock as rs
    from pokeagent.explorer.economy import shopping
    assert ABRA_STEP_CAP == 3000 and BALLS_MIN == 5
    # the goal's low-water mark IS the machinery's own ball trigger: every armed trip really buys balls,
    # and one trip's lot clears the threshold (the round-4 note: BALLS_MIN 12 vs a 10-ball buy could
    # never agree - the errand re-armed a Mart that had nothing more to sell and the hunts between
    # rechecks ran on 10 balls while the goal still read 'short')
    assert BALLS_MIN == shopping.BALL_MIN == rs.BALL_MIN and BALLS_MIN <= rs.BALL_BUY


def test_resolve_build_accepts_only_the_known_builds():
    assert resolve_build("abra", None) == "abra" and resolve_build(None, "abra") == "abra"
    assert resolve_build(None, None) == "" and resolve_build("", "abra") == ""   # the flag wins
    with pytest.raises(ValueError):
        resolve_build("charmander", None)


# --- the build want / full-party protection / floor + key -------------------------------------------------------------

def test_catch_wanted_wants_abra_line_only_for_the_build():
    assert catch_wanted("ABRA", [], 20, [], build="abra") == "catch_abra goal (build abra)"
    assert catch_wanted("KADABRA", [], 20, [], build="abra") == "catch_abra goal (build abra)"
    assert catch_wanted("ABRA", [], 20, []) is None                              # default build: dex rules only
    assert catch_wanted("KAKUNA", [], 20, [], build="abra") is None              # NEVER_CATCH still wins


def _six(build, abra_level=10):
    party = [SimpleNamespace(name="RATTATA", level=12, moves=("TACKLE",)),
             SimpleNamespace(name="PIDGEY", level=14, moves=("TACKLE",)),
             SimpleNamespace(name="ABRA", level=abra_level, moves=("TELEPORT",)),
             SimpleNamespace(name="ODDISH", level=13, moves=("TACKLE",)),
             SimpleNamespace(name="SPEAROW", level=15, moves=("TACKLE",)),
             SimpleNamespace(name="WEEDLE", level=11, moves=("TACKLE",))]
    goals_all = {g: True for g in GOALS}
    ctx = SimpleNamespace(opts=SimpleNamespace(build=build), goals=lambda: goals_all,
                          emu=FakeEmulator({}), train_member=None)
    return party, ctx


def test_full_party_slot_never_marks_the_abra_under_build_abra(monkeypatch):
    from pokeagent.explorer.training_ctl import roster
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx: None)
    party, ctx = _six("abra")
    pick = full_party_slot(ctx, party)
    assert pick == 5                                                             # WEEDLE 11: the lowest UNPROTECTED level
    assert party[pick].name != "ABRA"                                            # the build's Abra is protected
    abras, _ = _six("abra")
    for c in abras:
        c.name = "ABRA"
    assert full_party_slot(ctx, abras) is None                                   # only Abra-line members: nobody to give up


def test_full_party_slot_may_mark_the_abra_for_the_default_build(monkeypatch):
    from pokeagent.explorer.training_ctl import roster
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx: None)
    party, ctx = _six("")
    assert full_party_slot(ctx, party) == 2                                      # default build: the L10 Abra is the low man


def test_floor_verdict_is_the_same_with_or_without_an_abra_member():
    abra = _abra(10)
    without = [_tp_mon("STARMIE", 30), _tp_mon("CHARMELEON", 30), _tp_mon("RATTATA", 8)]
    for party in (without, without + [abra], [abra] + without):
        fl = team_floor.check("beat_misty", party, BOSS, SYN)
        assert fl is not None and fl.met and fl.have == 2 and fl.need == 2       # Abra is not sendable (Teleport does 0)
    weak = [_tp_mon("RATTATA", 19), _tp_mon("PIDGEY", 19), _tp_mon("WEEDLE", 5)]
    a, b = team_floor.check("beat_misty", weak, BOSS, SYN), team_floor.check("beat_misty", weak + [abra], BOSS, SYN)
    assert (a.met, a.have, a.need, a.text) == (b.met, b.have, b.need, b.text)


def test_build_key_names_the_abra_build():
    kb = {"name_of_internal": NAMES}
    fp = {"team": [{"species": ABRA_ID, "level": 10}, {"species": 177, "level": 14}]}
    key = team_fp.build_key(fp, kb)
    assert key.startswith("ABRA:") and "CHARMANDER:" in key
    band = team_fp.build_key({"team": [{"species": ABRA_ID, "level": 12}]}, kb)
    assert band == team_fp.build_key({"team": [{"species": ABRA_ID, "level": 10}]}, kb)  # same 5-level band
    assert team_fp.build_key({"team": [{"species": ABRA_ID, "level": 10}]}, kb) == "ABRA:L10"


# --- the Mart errand (round 2: buy balls before hunting) ------------------------------------------------------------

def test_the_shopping_list_wants_balls_while_catch_abra_is_open():
    met = {g: True for g in goal_ids()}
    assert not ball_need(met)                              # nothing upcoming: no ball need
    assert ball_need({**met, "catch_abra": False})         # the open abra goal wants balls
    assert not ball_need({**met, "catch_abra": True})      # settled: back to the campaign's own needs


def test_ball_errand_arms_a_restock_trip_the_existing_machinery_walks(tmp_path):
    ctx = make_ctx(tmp_path, balls=0, money=4000)          # Cerulean, Mart learned, purse covers it
    assert AbraHunt()._ball_errand(ctx)
    assert ctx.restock["intent"] and ctx.restock["want"] == (0x04,) and ctx.shop_intent == ("mart", None)
    d = Restock().step(ctx)
    assert d is not None and d.rule == "restock_walk"      # the armed trip is walked by Restock itself


def test_ball_errand_stays_quiet_when_stocked_broke_or_spent(tmp_path):
    assert not AbraHunt()._ball_errand(make_ctx(tmp_path, balls=BALLS_MIN, money=4000))   # enough throws already
    assert not AbraHunt()._ball_errand(make_ctx(tmp_path, balls=0, money=0))              # the settle rule owns this
    ctx = make_ctx(tmp_path, balls=0, money=4000)
    ctx.restock["tries"] = 3
    assert not AbraHunt()._ball_errand(ctx)               # the per-run Mart budget is spent
    ctx = make_ctx(tmp_path, balls=0, money=4000)
    ctx.restock["intent"] = True
    assert AbraHunt()._ball_errand(ctx)                   # a trip is underway: keep yielding to Restock


# --- encounter counting (round 2: a wild Abra counts at battle start, balls or not) ---------------------------------

ABRA_KB = {"dex_of_internal": {"148": 63}, "name_of_internal": {"148": "ABRA"}, "items": {}}


def _abra_battle_ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(catch_mod, "ROM_KB", ABRA_KB)
    ctx = _ctx(tmp_path)
    ctx.bv = BattleView(kind=1, hp=20, mx=20, run_line="RUN", species=ABRA_ID, e_lvl=10)
    logs = []
    ctx.log = lambda t, tag=None: logs.append(t)
    return ctx, logs


def test_abra_encounter_counts_at_battle_start_even_with_no_balls(tmp_path, monkeypatch):
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)    # the fake bag is empty: nothing to throw
    assert Catch().step(ctx) is None
    assert ctx.abra_encounters == 1 and ctx.abra_pending["battle"] == ctx.battles
    assert any("no ball" in t and "ABRA" in t for t in logs)   # let go - but the encounter counted
    Catch().step(ctx)
    assert ctx.abra_encounters == 1                        # once per battle, not once per step
    ctx.battles += 1
    Catch().step(ctx)
    assert ctx.abra_encounters == 2                        # the next encounter counts too


def test_abra_encounter_counts_with_balls_and_logs_one_action_line(tmp_path, monkeypatch):
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(catch_mod, "bag_contents", lambda emu: {0x04: 5})
    monkeypatch.setattr(catch_mod, "catch_wanted", lambda *a, **k: "catch_abra goal (build abra)")
    monkeypatch.setattr(catch_mod, "cave_catch_allowed", lambda ctx, sp: True)
    monkeypatch.setattr(catch_mod, "our_party", lambda emu: [])
    monkeypatch.setattr(catch_mod, "dex_owned_count", lambda emu: 0)
    monkeypatch.setattr(catch_mod, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(catch_mod, "_policy_hint", lambda *a, **k: CatchStep("throw", ball="POKE"))
    Catch().step(ctx)
    assert ctx.abra_encounters == 1
    assert sum("abra:" in t for t in logs) == 1 and any("throw" in t and "ABRA" in t for t in logs)
    Catch().step(ctx)
    assert ctx.abra_encounters == 1 and sum("abra:" in t for t in logs) == 1   # one line per encounter


# --- the throw drives the bag (round 4: a throw decision never yields a FIGHT press) ---------------------------------

def _throw_ctx(tmp_path, monkeypatch):
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(catch_mod, "bag_contents", lambda emu: {0x04: 5})
    monkeypatch.setattr(catch_mod, "catch_wanted", lambda *a, **k: "catch_abra goal (build abra)")
    monkeypatch.setattr(catch_mod, "cave_catch_allowed", lambda ctx, sp: True)
    monkeypatch.setattr(catch_mod, "our_party", lambda emu: [])
    monkeypatch.setattr(catch_mod, "dex_owned_count", lambda emu: 0)
    monkeypatch.setattr(catch_mod, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(catch_mod, "_policy_hint", lambda *a, **k: CatchStep("throw", ball="POKE", p=0.4))
    return ctx, logs


def test_throw_never_hands_battle_moves_a_fight_press(tmp_path, monkeypatch):
    """2026-11-18 real-ROM FAIL (de69d2f): 10 Abra encounters logged 'turn 1 throw POKE' and the battle
    driver still picked FIGHT/A; balls stayed 10. On a step with no readable menu Catch returned None and
    battle_moves' fallthrough pressed A - a Gen 1 menu renders mid-step, so that A either lands on the
    just-drawn FIGHT (switch_press documents the race and backs out with B) or, once the move menu is up,
    picks a damaging move. Either way the Abra teleports on its turn. A pending throw must answer with
    bag/menu inputs only."""
    ctx, logs = _throw_ctx(tmp_path, monkeypatch)
    # intro text, no menu readable: B advances the text - it cannot select FIGHT the way an A can
    ctx.bv = replace(ctx.bv, run_line=None)
    ctx.view.lines = ["Wild ABRA appeared!"]
    dec = Catch().step(ctx)
    assert dec is not None and dec.button == "B" and dec.rule == "catch_menu_b"
    # the stray A already opened FIGHT (the move menu reads TYPE/): B backs out to FIGHT/PKMN/ITEM/RUN
    ctx.view.lines = ["TYPE/", "NORMAL", "29/30", ">TACKLE"]
    dec = Catch().step(ctx)
    assert dec is not None and dec.button == "B" and dec.rule == "catch_menu_b"
    # the battle menu itself: item_step walks it to ITEM
    ctx.bv = replace(ctx.bv, run_line="RUN")
    ctx.view.lines = [">FIGHT PKMN", "ITEM RUN"]
    dec = Catch().step(ctx)
    assert dec is not None and dec.rule == "item_menu_down" and dec.button == "DOWN"
    # ITEM under the cursor: A opens the bag
    ctx.view.lines = ["FIGHT PKMN", ">ITEM RUN"]
    dec = Catch().step(ctx)
    assert dec is not None and dec.rule == "item_open" and dec.button == "A"
    # the bag list on screen: the A on the ball row is item_use - the throw itself, never 'fight'
    ctx.view.lines = ["POKE BALL", "x5"]
    _set(ctx.emu, {0xD31D: 1, 0xD31E: 0x04, 0xD31F: 5})
    dec = Catch().step(ctx)
    assert dec is not None and dec.rule == "item_use" and dec.button == "A"
    assert any("throwing" in t for t in logs)


def test_throw_sequence_presses_are_capped(tmp_path, monkeypatch):
    """The B steps count toward CATCH_BAG_PRESSES: a screen that never parses a menu abandons the
    catch instead of pressing B until the step cap - on a flee species the battle ends long first."""
    ctx, logs = _throw_ctx(tmp_path, monkeypatch)
    ctx.bv = replace(ctx.bv, run_line=None)
    ctx.view.lines = ["Wild ABRA appeared!"]
    for _ in range(catch_mod.CATCH_BAG_PRESSES):
        assert Catch().step(ctx).button == "B"
    dec = Catch().step(ctx)                                   # one press too many: abandon, fight on
    assert dec is not None and dec.rule == "catch_bag_failed" and dec.button == "B"
    assert ctx.catch_mode is False and ctx.catch_hint is None
    assert Catch().step(ctx) is None                          # no new hint for the rest of this battle


# --- the give-up (round 2: a settle without an Abra is never a success) ----------------------------------------------

def _stage_ctx(**kw):
    logs = []
    base = dict(abra_steps=0, abra_skipped=False, abra_encounters=2, had_abra=False,
                abra_gave_up=False, abra_settle="", opts=SimpleNamespace(build="abra"),
                log=lambda t, tag=None: logs.append(t), goals=lambda: {"catch_abra": True})
    return SimpleNamespace(**(base | kw)), logs


def test_abra_stage_marks_the_cap_settle_a_give_up_never_a_success():
    state = {"catch_abra": False}
    ctx, logs = _stage_ctx(abra_steps=ABRA_STEP_CAP, goals=lambda: dict(state))
    abra_stage(ctx, dict(state))                           # the open step that crosses the cap
    assert ctx.abra_skipped and any("gave up" in t for t in logs)
    state["catch_abra"] = True                             # the next goals() reports the skip settled
    abra_stage(ctx, dict(state))
    assert ctx.abra_gave_up and any("settled - gave up" in t for t in logs)
    assert not any("caught" in t for t in logs)


def test_abra_stage_reports_a_caught_abra_not_a_give_up():
    state = {"catch_abra": False}
    ctx, logs = _stage_ctx(goals=lambda: dict(state))
    abra_stage(ctx, dict(state))                           # an open step first: the latch arms
    ctx.had_abra = True
    state["catch_abra"] = True                             # the catch landed between calls
    abra_stage(ctx, dict(state))
    assert not ctx.abra_gave_up and any("settled - caught" in t for t in logs)


class _FakeEmu:
    def save_state(self, path):
        open(path, "wb").write(b"s")

    def read(self, addr):
        return 0


def _record_ctx(run, logs, **kw):
    return SimpleNamespace(emu=_FakeEmu(), run_dir=run, step=7, frame=70, goal_steps={},
                           initial_goals=set(), initial_goals_ready=True, goal_left_house=False,
                           log=lambda m, t=None: logs.append(m),
                           opts=SimpleNamespace(state_stem="", stop_at_goal=None, stop_at_map=None,
                                                headless=False, starter="x"), **kw)


def test_record_goals_marks_a_catch_abra_settle_without_an_abra_a_give_up(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {g: False for g in GOALS}
    state["catch_abra"] = True
    monkeypatch.setattr(press_goals, "check_goals", lambda emu, ctx: dict(state))
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text("{}")
    logs = []
    ctx = _record_ctx(run, logs, had_abra=False, abra_gave_up=False)
    press_goals.record_goals(ctx, SimpleNamespace(goals=None))
    assert ctx.goal_steps["catch_abra"] == 7 and ctx.goal_steps["catch_abra_gave_up"] == 7
    assert ctx.abra_gave_up
    row = json.loads((run / "goal_frames.jsonl").read_text().splitlines()[0])
    assert row["goal"] == "catch_abra" and row["gave_up"] is True
    hist = json.loads((tmp_path / "runs/milestones.json").read_text())
    assert hist["catch_abra"][-1]["gave_up"] is True
    assert any("gave up" in m for m in logs) and not any("GOAL REACHED" in m for m in logs)


# --- the Mart route (round 3: an armed trip walks a long learned route, and says why when it cannot) ---

from pokeagent.explorer import restock as rs
from pokeagent.explorer.world import WorldGraph


def _r24_cerulean_maps():
    """Faithful to the ROM geometry: Route 24's Abra grass is the x4-5 corridor y18-31 (walls x6-9
    below y15); the middle corridor x10-11 runs to the south edge openings (y35), whose crossing
    lands on Cerulean's north strip x20-21; the Mart door press is UP from (25,26) -> map 67's
    (3,7). A learned walk from deep grass is ~65 steps - over rs.MAX_PATH, inside the trip budget."""
    r24 = {"visited": {}, "blocked": [], "warps": {}}
    for y in range(15, 32):                                     # the west grass corridor
        for x in (4, 5):
            r24["visited"][f"{x},{y}"] = 1
    for x in range(4, 12):                                      # the open band at y15 joining grass to the bridge corridor
        r24["visited"][f"{x},15"] = 1
    for y in range(15, 36):                                     # the middle corridor down to the south edge
        for x in (10, 11):
            r24["visited"][f"{x},{y}"] = 1
    r24["warps"]["11,35,DOWN"] = [3, 21, 2]                     # the south crossing into Cerulean
    r24["npcs"] = {f"slot{i}:pic7": {"pic": 7, "slot": i, "positions": {f"{x},{y}": 5},
                                    "moves": False, "last": [x, y]}   # the beaten bridge trainers: static, BFS skips
                   for i, (x, y) in enumerate([(5, 20), (10, 22), (11, 25), (10, 28), (11, 31)], 1)}
    cer = {"visited": {}, "blocked": [], "warps": {}}
    for y in range(2, 13):                                      # the north strip down to the mid street
        for x in (20, 21):
            cer["visited"][f"{x},{y}"] = 1
    for x in range(20, 26):                                     # the mid street east toward the Mart
        cer["visited"][f"{x},12"] = 1
    for y in range(12, 27):                                     # down the Mart's column to the door tile
        cer["visited"][f"25,{y}"] = 1
    cer["warps"]["25,26,UP"] = [67, 3, 7]                       # the Mart door press -> map 67
    mart = {"visited": {f"3,{y}": 1 for y in (5, 6, 7)} | {"2,5": 1}, "blocked": [],
            "warps": {"3,7,DOWN": [3, 25, 26]}}
    return {"35": r24, "3": cer, "67": mart}


def test_armed_ball_errand_walks_a_long_learned_route_to_the_mart(tmp_path):
    """From the Route 24 grass the Cerulean Mart is ~65 learned steps away - over rs.MAX_PATH (the
    'is a Mart near' planning rule) but inside the trip budget: an ARMED errand must still walk it
    (2026-11-18 real-ROM FAIL: 'no route to a Mart' burned all three tries, no balls ever bought)."""
    ctx = make_ctx(tmp_path, balls=0, money=4000, m=35, x=5, y=28)
    ctx.mem.data["maps"] = _r24_cerulean_maps()
    ctx.restock = {"intent": True, "want": (rs.BALL_ID,), "steps": 0}
    d = Restock().step(ctx)
    assert d is not None and d.rule == "restock_walk"
    g = WorldGraph(ctx.mem.data["maps"])
    assert len(g.path(ctx.pos(), lambda n: n[0] in rs.MART_MAPS, 5000)) > rs.MAX_PATH   # the route is real, just long


def test_armed_trip_reports_why_no_mart_can_be_walked(tmp_path):
    """Every candidate Mart failed this run: the log must say the Mart set is empty - and a trip
    that never started spends no try; the recheck window holds the next arm off."""
    ctx = make_ctx(tmp_path, balls=0, money=4000, m=35, x=5, y=28)
    ctx.mem.data["maps"] = _r24_cerulean_maps()
    logs = []
    ctx.log = lambda t, tag=None: logs.append(t)
    ctx.restock = {"intent": True, "want": (rs.BALL_ID,), "steps": 0, "failed": set(rs.MART_MAPS)}
    assert Restock().step(ctx) is None
    assert any("no Mart left" in t for t in logs)
    assert ctx.restock["next_check"] > 0 and "tries" not in ctx.restock
    hunt = AbraHunt()
    assert hunt._ball_errand(ctx)                                 # no trip watched end: the errand arms
    ctx.restock["intent"] = False                                 # Restock ends it ('no route' again)
    hunt._ball_errand(ctx)                                        # it watched the trip die short: backs off
    assert not hunt._ball_errand(ctx)                             # the errand's own recheck window now
    ctx.step += rs.RECHECK_EVERY
    assert hunt._ball_errand(ctx)                                 # window over: try again


def test_no_name_table_settles_open_but_says_so_out_loud():
    st = _st("abra")
    assert catch_abra_settled(_emu(money=3000), st, set(), None)          # cannot judge: settled, never blocks
    assert st["abra_settle"] == "no name table"
    logs = []
    st2 = _st("abra", log=lambda t, tag=None: logs.append(t))             # the ctx's log, when it is there
    assert catch_abra_settled(_emu(money=3000), st2, set(), None)
    assert sum("no kb name table" in t for t in logs) == 1
    catch_abra_settled(_emu(money=3000), st2, set(), None)
    assert sum("no kb name table" in t for t in logs) == 1                # loud once, not every goals check
    st3 = _st("", log=lambda t, tag=None: logs.append(t))
    assert catch_abra_settled(_emu(money=3000), st3, set(), None)         # the default build never reaches the check


def test_record_goals_reports_a_caught_abra_as_an_ordinary_goal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {g: False for g in GOALS}
    state["catch_abra"] = True
    monkeypatch.setattr(press_goals, "check_goals", lambda emu, ctx: dict(state))
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text("{}")
    logs = []
    ctx = _record_ctx(run, logs, had_abra=True, abra_gave_up=False)
    press_goals.record_goals(ctx, SimpleNamespace(goals=None))
    assert ctx.goal_steps["catch_abra"] == 7 and "catch_abra_gave_up" not in ctx.goal_steps
    assert not ctx.abra_gave_up
    row = json.loads((run / "goal_frames.jsonl").read_text().splitlines()[0])
    assert row["goal"] == "catch_abra" and "gave_up" not in row
    assert any("GOAL REACHED: catch_abra" in m for m in logs)


# --- the throw owns the turn (round 5: nothing ahead of Catch may spend a flee-species turn) -------

from pokeagent.explorer.behaviours import abra_hunt as abra_hunt_mod
from pokeagent.explorer.behaviours import battle as battle_mod
from pokeagent.explorer.behaviours import battle_run as battle_run_mod
from pokeagent.explorer.behaviours import switch_out as switch_out_mod
from pokeagent.explorer.behaviours.battle import Battle
from pokeagent.explorer.behaviours.battle_moves import BattleMoves
from pokeagent.explorer.behaviours.battle_run import flee_throw_pending
from pokeagent.explorer.behaviours.switch_out import SwitchOut
from pokeagent.explorer.selector import Selector

BATTLE_MENU = [">FIGHT PKMN", "ITEM RUN"]
BALL_LIST = ["POKE BALL", "x5"]


def _low_hp_ctx(tmp_path, monkeypatch):
    """The wanted-Abra fight from _throw_ctx plus the RAM the REAL battle layer reads: ENEMY_MON =
    ABRA, a bag with 5 Poke Balls and 2 POTIONs, and a fighter at 4/20 HP - the exact spot where a
    POTION stole turn 1 on the real ROM (2026-11-18 FAIL: 4 throws in 48 encounters)."""
    ctx, logs = _throw_ctx(tmp_path, monkeypatch)
    _set(ctx.emu, {0xCFE5: ABRA_ID, 0xCFF3: 10,                    # enemy: ABRA L10
                   0xD31D: 2, 0xD31E: 0x04, 0xD31F: 5,             # bag: 5 Poke Balls ...
                   0xD320: 0x14, 0xD321: 2})                       # ... and 2 POTIONs
    monkeypatch.setattr(battle_run_mod, "ROM_KB", ABRA_KB)
    monkeypatch.setattr(battle_run_mod, "catch_wanted", lambda *a, **k: "catch_abra goal (build abra)")
    monkeypatch.setattr(battle_run_mod, "our_party", lambda emu: [])
    monkeypatch.setattr(battle_run_mod, "dex_owned_count", lambda emu: 0)
    monkeypatch.setattr(battle_run_mod, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(battle_mod, "party_hp", lambda emu: (4, 20))
    monkeypatch.setattr(battle_mod, "fighter", lambda emu: (177, 12, 4, 20))
    ctx.refresh = lambda: None                                     # the fixture owns the screen
    return ctx, logs


def test_pending_throw_owns_turn_one_against_every_earlier_behaviour(tmp_path, monkeypatch):
    """2026-11-18 real-ROM FAIL (7bda952): 48 Abra encounters, 4 throws - Battle runs BEFORE Catch and
    its POTION spent the one turn the Abra was staying for. With a wanted flee species the latch is
    armed before any behaviour decides (flee_throw_pending computes it lazily - Readiness and the
    guards ask before Battle does), and every earlier battle action yields to the bag walk."""
    ctx, logs = _low_hp_ctx(tmp_path, monkeypatch)
    sel = Selector([Battle(), SwitchOut(), Catch(), BattleMoves()])
    ctx.view.lines = BATTLE_MENU                                    # low HP + potions + RUN on screen
    d = sel.choose(ctx)
    assert d is not None and d.behaviour == "catch", d              # never a POTION, a switch or RUN
    assert d.rule in ("catch_jitter", "item_menu_down", "item_open", "item_list_scroll", "item_use")
    assert ctx.bv is not None and not ctx.bv.want_potion            # Battle saw the HP and stood down
    assert flee_throw_pending(ctx, ABRA_ID)
    monkeypatch.setattr(switch_out_mod, "trainee_out", lambda c: 1)  # a swap candidate is right there
    assert not SwitchOut().applies(ctx)                              # a swap hands Teleport the wild's turn
    ctx.view.lines = BALL_LIST                                       # the bag is open: the ball lands
    d = sel.choose(ctx)
    assert d is not None and d.behaviour == "catch" and d.rule == "item_use"
    assert (ctx.abra_pending or {}).get("thrown") == 1 and ctx.catch_attempt["thrown"] == 1
    # The latch dies with the catch (a skip, a full party, a bag give-up): the floor rules take over.
    ctx.catch_flee = ((ctx.battles, ABRA_ID), False)
    assert not flee_throw_pending(ctx, ABRA_ID)
    assert SwitchOut().applies(ctx)                                  # the swap candidate applies again
    ctx.view.lines = BATTLE_MENU
    d = sel.choose(ctx)
    assert d is not None and d.behaviour == "battle"                 # Battle's potion path is its own again


def test_a_policy_skip_releases_the_latch_and_the_battle_behaves_normally(tmp_path, monkeypatch):
    ctx, logs = _low_hp_ctx(tmp_path, monkeypatch)
    sel = Selector([Battle(), SwitchOut(), Catch(), BattleMoves()])
    ctx.view.lines = BATTLE_MENU
    d = sel.choose(ctx)
    assert d.behaviour == "catch" and flee_throw_pending(ctx, ABRA_ID)
    monkeypatch.setattr(catch_mod, "_policy_hint", lambda *a, **k: CatchStep("skip", why="rate too poor"))
    sel.choose(ctx)                                                  # Catch passes the catch up
    assert not flee_throw_pending(ctx, ABRA_ID)
    assert ctx.catch_mode is False
    ctx.view.lines = BATTLE_MENU
    d = sel.choose(ctx)
    assert d is not None and d.behaviour == "battle"                 # potion/flee decisions are back
    assert any("no throw: rate too poor" in t or "not catching" in t for t in logs)


def test_every_abra_encounter_without_a_throw_says_why(tmp_path, monkeypatch):
    """44 of 48 encounters ended with no ball and no clue (2026-11-18 FAIL). The resolve line now
    carries the reason the catch recorded - or 'catch never engaged' when none was."""
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)              # the fake bag is empty
    Catch().step(ctx)
    ctx.view.battling = False
    AbraHunt().applies(ctx)                                          # resolves the pending encounter
    assert any("fled" in t and "no throw: no ball in the bag" in t for t in logs)
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ctx.view.battling = False
    ctx.abra_pending = {"battle": ctx.battles, "species": "ABRA", "level": 8}   # nothing recorded at all
    AbraHunt().applies(ctx)
    assert any("no throw: catch never engaged" in t for t in logs)
    ctx.abra_pending = {"battle": ctx.battles, "species": "ABRA", "level": 8, "thrown": 2}
    AbraHunt().applies(ctx)
    assert any("fled" in t and "2 thrown" in t for t in logs)
    monkeypatch.setattr(abra_hunt_mod, "our_party", lambda emu: [_abra(10)])
    ctx.abra_pending = {"battle": ctx.battles, "species": "ABRA", "level": 10, "thrown": 1}
    AbraHunt().applies(ctx)
    assert any("caught" in t and "1 thrown" in t for t in logs)


def test_a_catch_attempt_with_no_ball_thrown_is_never_a_success(tmp_path, monkeypatch):
    """2026-11-18 real-ROM FAIL: '[catch attempt SUCCEEDED vs #148 L12 at 100%]' on a fight where the
    Abra teleported and no ball left the bag - the dex bit only said 'owned'. A success now needs a
    real throw AND new ownership (a member the party did not have, or a dex bit set during the fight)."""
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ca = {"species": ABRA_ID, "level": 12, "step": ctx.step, "dex": 63, "battle": ctx.battles,
          "presses": 0, "last": ctx.step, "hp_pct": 1.0, "owned0": True, "party0": (177,)}
    ctx.catch_attempt = dict(ca)
    ctx.in_battle = True
    ctx.view.battling = False
    _set(ctx.emu, {0xD2F7 + 7: 0x40})                # dex 63's bit was ALREADY set when the fight began
    Battle().step(ctx)
    assert not any("SUCCEEDED" in t for t in logs)
    assert any("no throw" in t and "#148" in t for t in logs)
    assert ctx.mem.data["catches"][-1]["caught"] is False
    # a throw that really landed and put the Abra in the party still reads SUCCEEDED
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ctx.catch_attempt = {**ca, "thrown": 1}
    ctx.in_battle = True
    ctx.view.battling = False
    _set(ctx.emu, {0xD2F7 + 7: 0x40, **party_mem([(177, 14, 30, 30), (ABRA_ID, 10, 25, 25)])})
    Battle().step(ctx)
    assert any("SUCCEEDED" in t and "#148" in t for t in logs)
    assert ctx.mem.data["catches"][-1]["caught"] is True
    # a real throw that missed and the wild one fled: 'failed', never 'SUCCEEDED' or 'no throw'
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ctx.catch_attempt = {**ca, "thrown": 1}
    ctx.in_battle = True
    ctx.view.battling = False
    _set(ctx.emu, party_mem([(177, 14, 30, 30)]))
    Battle().step(ctx)
    assert not any("SUCCEEDED" in t for t in logs)
    assert any("catch attempt failed" in t for t in logs)


# --- the re-arm (round 6: a bag that hits 0 with money buys again) -------------------------------------------

def test_ball_errand_rearms_when_balls_run_out_mid_hunt(tmp_path):
    """2026-11-18 real-ROM FAIL (89c6cdd): the bag hit 0 with money for a ball and no second Mart trip
    ever armed - the errand borrowed Restock's next_check, which Restock re-bumps on every planning
    pass BEFORE the errand's own check runs (Restock precedes AbraHunt in the registry), so the
    window never read expired to it. The errand's own abra_next_check re-arms a bag that hits 0 on
    the spot: Restock's recheck window never gates it."""
    ctx = make_ctx(tmp_path, balls=0, money=4000)
    hunt = AbraHunt()
    assert hunt._ball_errand(ctx)                               # the first Mart trip arms
    ctx.restock["intent"] = False                               # ... Restock ran it and bought a lot ...
    _set(ctx.emu, {0xD31D: 1, 0xD31E: 0x04, 0xD31F: 10})        # 10 balls in the bag now
    assert not hunt._ball_errand(ctx)                           # stocked: hunting, and no back-off was set
    assert "abra_next_check" not in ctx.restock
    _set(ctx.emu, {0xD31F: 0})                                  # the hunt spent the lot: 0 balls again
    ctx.restock["next_check"] = ctx.step + rs.RECHECK_EVERY     # Restock's own recheck is mid-window ...
    assert hunt._ball_errand(ctx)                               # ... but the errand re-arms on the spot
    assert ctx.restock["intent"] and hunt._ball_errand(ctx)     # and it yields to Restock while it walks


def test_a_failed_trip_backs_the_errand_off_one_recheck(tmp_path):
    """An armed trip that ends with the bag still short (a Mart it could not route to) does not
    re-arm every step: it watches the trip end, backs off one recheck window of its own, then tries."""
    ctx = make_ctx(tmp_path, balls=0, money=4000)
    hunt = AbraHunt()
    assert hunt._ball_errand(ctx)
    ctx.restock["intent"] = False                               # the trip ended, bag still short
    hunt._ball_errand(ctx)                                      # it watched the trip die: back off
    assert not hunt._ball_errand(ctx) and ctx.restock["abra_next_check"] > 0
    ctx.step = ctx.restock["abra_next_check"]
    assert hunt._ball_errand(ctx)                               # window over: it may try again


# --- jitter + RNG evidence (round 6: 0/24 full-HP throws) ----------------------------------------------------

from pokeagent.explorer.behaviours.catch_track import throw_jitter


def test_flee_throw_spends_seeded_jitter_presses_before_the_bag(tmp_path, monkeypatch):
    """0/24 throws at ~30% each on full-HP Abras (2026-11-18 FAIL): the emulator replays the ROM's
    RNG, so an identical press cadence draws identical bytes. A seeded count of B presses precedes
    the bag walk of a flee-species throw, and the throw line logs the RNG bytes it drew at - the
    per-encounter evidence of (or against) a repeated cadence."""
    ctx, logs = _throw_ctx(tmp_path, monkeypatch)
    _set(ctx.emu, {0xFFD3: 0xAB, 0xFFD4: 0xCD, 0xFF04: 0x42})    # hRandomAdd / hRandomSub / rDIV
    ctx.battles, ctx.step = 1, 0                                # jitter = (7 + 0 + 0) % 4 = 3
    ctx.view.lines = ["FIGHT PKMN", ">ITEM RUN"]
    for _ in range(3):
        dec = Catch().step(ctx)
        assert dec is not None and dec.rule == "catch_jitter" and dec.button == "B"
    dec = Catch().step(ctx)                                     # jitter spent: the bag walk begins
    assert dec is not None and dec.rule == "item_open" and dec.button == "A"
    ctx.view.lines = BALL_LIST
    _set(ctx.emu, {0xD31D: 1, 0xD31E: 0x04, 0xD31F: 5})
    dec = Catch().step(ctx)
    assert dec is not None and dec.rule == "item_use"
    assert any("rng AB/CD/div42" in t for t in logs)            # the press's RNG bytes are on the line
    assert (ctx.abra_pending or {}).get("rng") == [(0xAB, 0xCD, 0x42)]
    assert ctx.catch_attempt["jitter"] == throw_jitter(1, 0, 1)  # the next throw's walk re-arms fresh


def test_jitter_is_flee_species_only(tmp_path, monkeypatch):
    """A non-flee catch's sequence is unchanged: no spare presses precede its bag walk."""
    ctx, logs = _throw_ctx(tmp_path, monkeypatch)
    kb = {"dex_of_internal": {"36": 16, "148": 63},
          "name_of_internal": {"36": "PIDGEY", "148": "ABRA"}, "items": {}}
    monkeypatch.setattr(catch_mod, "ROM_KB", kb)
    ctx.bv = replace(ctx.bv, species=36)
    ctx.battles, ctx.step = 1, 0                                # a flee species would press B x3 here
    ctx.view.lines = ["FIGHT PKMN", ">ITEM RUN"]
    dec = Catch().step(ctx)
    assert dec is not None and dec.rule == "item_open"          # straight to the bag
    assert "jitter" not in (ctx.catch_attempt or {})


# --- a boxed Abra counts (round 6: a full party sends the catch to the PC box) -------------------------------

def test_boxed_abra_settles_the_goal_as_caught():
    """A full party sends the catch to the PC box on its own (no deposit prompt in RBY): the run has
    an Abra, so the goal settles caught - hunting on for a party copy would waste the stage."""
    emu = _emu(((177, 14, 30, 30),), money=3000)
    st = _st("abra")
    assert not catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})   # the start pool: no Abra
    _set(emu, {0xDA80: 1, 0xDA81: ABRA_ID})                       # the catch lands in wBoxSpecies
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})
    assert st["had_abra"] and st["abra_settle"] == "caught (boxed)"


def test_box_species_reads_the_species_list_not_the_box_structs():
    """wBoxSpecies (0xDA81) is the 0xFF-terminated species list; wBoxMons (0xDA96) is the 33-byte
    struct array - reading n bytes THERE sees the first mon's level/move/catch-rate bytes as
    species. The real nugget_bridge.state holds 2 boxed mons and trips that misread."""
    emu = _emu()
    _set(emu, {0xDA80: 2, 0xDA81: 0x70, 0xDA82: ABRA_ID, 0xDA83: 0xFF,   # the species list: [112, ABRA]
               0xDA96: 0x70, 0xDA97: 0x00, 0xDA98: 0x26})              # wBoxMons[0] struct head
    assert box_species(emu) == [0x70, ABRA_ID]


def test_resolve_line_counts_a_boxed_abra_as_caught(tmp_path, monkeypatch):
    """The encounter resolve line reads the box too: a caught Abra in a full party never reads 'fled'."""
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ctx.view.battling = False
    ctx.abra_pending = {"battle": ctx.battles, "species": "ABRA", "level": 8, "thrown": 1,
                        "rng": [(0xAB, 0xCD, 0x42)]}
    _set(ctx.emu, {0xDA80: 1, 0xDA81: ABRA_ID})
    monkeypatch.setattr(abra_hunt_mod, "our_party", lambda emu: [])
    monkeypatch.setattr(abra_hunt_mod, "table", lambda kb, name: NAMES if name == "name_of_internal" else {})
    AbraHunt().applies(ctx)
    assert any("caught" in t and "1 thrown" in t and "rng AB/CD/42" in t for t in logs)


# --- only an Abra gained THIS run counts (round 7: a pre-existing boxed Abra never settles) --------

def test_a_boxed_abra_at_run_start_leaves_the_goal_open_and_the_hunt_armed(tmp_path, monkeypatch):
    """2026-11-18 real-ROM FAIL (6af12e5): nugget_bridge.state's PC box already held an ABRA
    (wBoxSpecies [0x94, 0x70] - the wBoxMons struct reads L10, Psychic/Psychic, catch rate 200,
    TELEPORT). The box read settled catch_abra at the startup goal scan, so it landed in 'goals
    assumed done' and the hunt never ran (0 encounters). The first settle check snapshots the
    party+box species pool - the same moment initial_goals are computed - and the goal wants an
    Abra-line count ABOVE that baseline: only this run's catch counts."""
    from pokeagent.knowledge import kb as kb_mod
    monkeypatch.setattr(kb_mod, "ROM_KB", {"name_of_internal": NAMES})
    ctx = make_ctx(tmp_path, balls=5, money=4000)
    ctx.opts.build = "abra"
    _set(ctx.emu, {0xDA80: 1, 0xDA81: ABRA_ID})                        # the box ALREADY holds an Abra
    press_goals.seed_initial_goals(ctx)
    assert "catch_abra" not in ctx.initial_goals                     # pre-existing is not 'assumed done'
    assert AbraHunt().applies(ctx) and ctx.team_wants                # the hunt arms on the open goal
    _set(ctx.emu, {0xDA80: 2, 0xDA82: ABRA_ID})                      # a SECOND Abra lands: this run's catch
    assert ctx.goals()["catch_abra"] and ctx.had_abra and ctx.abra_settle == "caught (boxed)"


def test_a_party_abra_at_run_start_never_settles_either():
    """Same rule for a pre-existing PARTY Abra: presence at the first check is the baseline."""
    emu = _emu(((177, 14, 30, 30), (ABRA_ID, 10, 25, 25)), money=3000, balls={4: 5})
    st = _st("abra")
    assert not catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})   # already there: not ours
    _set(emu, party_mem([(177, 14, 30, 30), (ABRA_ID, 10, 25, 25), (KADABRA_ID, 20, 40, 40)]))
    assert catch_abra_settled(emu, st, set(), {"name_of_internal": NAMES})       # a NEW line member counts
    assert st["had_abra"] and st["abra_settle"] == "caught"


# --- round 8: the verdict sees a box gain; the resolve line is per-encounter; the want lapses --------

def test_a_box_gain_counts_as_new_ownership(tmp_path, monkeypatch):
    """2026-11-18 real-ROM (abra7 seed 1, step 1374): the real catch logged 'catch attempt failed' -
    the party was full so the Abra went to the PC box, and its dex bit was ALREADY set by the boxed
    Abra the save started with (round-7 find), so neither the party diff nor the dex bit could prove
    it. The attempt now snapshots wBoxSpecies (box0): a species count the box gained IS ownership."""
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ca = {"species": ABRA_ID, "level": 12, "step": ctx.step, "dex": 63, "battle": ctx.battles,
          "presses": 0, "last": ctx.step, "hp_pct": 1.0, "owned0": True, "party0": (177,),
          "box0": (0x70,), "thrown": 1}
    ctx.catch_attempt = dict(ca)
    ctx.in_battle, ctx.view.battling = True, False
    _set(ctx.emu, {0xD2F7 + 7: 0x40,                                        # dex bit already owned
                   0xDA80: 2, 0xDA81: 0x70, 0xDA82: ABRA_ID,                # the box gained THIS Abra
                   **party_mem([(177, 14, 30, 30)])})                       # the party is unchanged
    Battle().step(ctx)
    assert any("SUCCEEDED" in t and "#148" in t for t in logs)
    assert ctx.mem.data["catches"][-1]["caught"] is True
    # the same throw with the box UNCHANGED (the wild fled) still reads 'failed', not 'SUCCEEDED'
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ctx.catch_attempt = {**ca, "box0": (0x70, ABRA_ID)}                     # both were there at the start
    ctx.in_battle, ctx.view.battling = True, False
    _set(ctx.emu, {0xD2F7 + 7: 0x40, 0xDA80: 2, 0xDA81: 0x70, 0xDA82: ABRA_ID,
                   **party_mem([(177, 14, 30, 30)])})
    Battle().step(ctx)
    assert not any("SUCCEEDED" in t for t in logs)
    assert any("catch attempt failed" in t for t in logs)


def test_resolve_line_compares_against_the_encounters_own_snapshot(tmp_path, monkeypatch):
    """2026-11-18 real-ROM (abra7 seed 1): after the first catch every later Abra encounter logged
    'caught' - even 'caught, no throw: no ball in the bag' - because the check ran against the
    run-start baseline. The pending record's own owned0 (written at the battle's start) is the
    baseline now: 'caught' means THIS encounter added an Abra-line member."""
    ctx, logs = _abra_battle_ctx(tmp_path, monkeypatch)
    ctx.view.battling = False
    monkeypatch.setattr(abra_hunt_mod, "table", lambda kb, name: NAMES if name == "name_of_internal" else {})
    _set(ctx.emu, {0xDA80: 1, 0xDA81: ABRA_ID})                             # the box holds the EARLIER catch
    ctx.abra_pending = {"battle": ctx.battles, "species": "ABRA", "level": 8,
                        "owned0": {ABRA_ID: 1}}                             # it was already there when THIS fight began
    AbraHunt().applies(ctx)
    assert any("fled" in t for t in logs) and not any("caught" in t for t in logs)
    ctx.abra_pending = {"battle": ctx.battles + 1, "species": "ABRA", "level": 10, "thrown": 1,
                        "owned0": {ABRA_ID: 1}}                             # this fight's snapshot: 1 Abra
    _set(ctx.emu, {0xDA80: 2, 0xDA82: ABRA_ID})                             # ... and the box holds 2 now
    AbraHunt().applies(ctx)
    assert any("caught" in t and "1 thrown" in t for t in logs)


def test_the_build_want_lapses_when_catch_abra_settles(tmp_path, monkeypatch):
    """2026-11-18 real-ROM (abra7 seed 1): the goal settled at step 1374 and the hunt still met 6
    more Abras, burning the restock balls - the armed team_wants entry was stale and the build
    clause wanted every Abra-line mon anyway. The want lives only while the goal is open; another
    goal's want (an HM need, a plan) survives the settle."""
    assert catch_wanted("ABRA", [], 20, [], build="abra") == "catch_abra goal (build abra)"   # open: wanted
    assert catch_wanted("KADABRA", [], 20, [], build="abra", abra_open=False) is None          # settled: not
    assert catch_wanted("ABRA", [], 20, [], build="abra", abra_open=False,
                       wants={"ABRA": "planned: x"}) == "planned: x"                         # another goal's want stays
    ctx = make_ctx(tmp_path, balls=5, money=4000)
    ctx.opts.build = "abra"
    ctx.goals = lambda: {g: True for g in GOALS}                            # catch_abra settled
    ctx.team_wants = {"ABRA": ABRA_WANT}                                    # the want abra_hunt armed, now stale
    assert not AbraHunt().applies(ctx)
    assert ctx.team_wants == {}                                             # dropped once the goal is done
    ctx.team_wants = {"ABRA": "can learn FLASH (needed ahead, nobody in the party can)"}
    assert not AbraHunt().applies(ctx)
    assert ctx.team_wants                                                   # another goal's want is not ours to drop
