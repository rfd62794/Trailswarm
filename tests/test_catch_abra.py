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
from pokeagent.abra_goal import ABRA_STEP_CAP, BALLS_MIN, abra_stage, catch_abra_settled, resolve_build
from pokeagent.campaign import goal_ids
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import press_goals
from pokeagent.explorer.behaviours import Catch, Restock
from pokeagent.explorer.behaviours import catch as catch_mod
from pokeagent.explorer.behaviours.abra_hunt import AbraHunt
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
        emu = _emu(((177, 14, 30, 30), (sp, 20, 40, 40)), money=0)
        assert catch_abra_settled(emu, _st("abra"), set(), {"name_of_internal": NAMES})


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
    assert not AbraHunt()._ball_errand(ctx)                       # the recheck window mutes the re-arm
    ctx.step = ctx.restock["next_check"]
    assert AbraHunt()._ball_errand(ctx)                           # past it: the errand may try again


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
