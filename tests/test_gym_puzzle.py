"""GymPuzzle: Lt. Surge's trash-can locks - synthetic tests (fake RAM, fake screen, no ROM, no emulator binary).

The can table below is the directive's probe fixture, kept ONLY here: in code the can positions come from the
ROM grid via plan.cells_with_tile(map_id, 0x1B). The lock rules the FakeGame plays (first lock random, second =
an orthogonal neighbour, a wrong can after the first resets both) are UNVERIFIED background knowledge.
"""
from __future__ import annotations

import random

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import gym_puzzle as gp
from pokeagent.explorer.behaviours.gym_puzzle import GymPuzzle
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.loop_memory import NEVER_VETO
from pokeagent.explorer.memory import MapMemory

MAP, PX, PY, BATTLE, TM = 0xD35E, 0xD362, 0xD361, 0xD057, 0xC3A0

# probe fixture: can id -> (can cell, stand tile, facing); cans 4 and 12 stand below (trainers block above)
CANS = [(1, 7), (1, 9), (1, 11), (3, 7), (3, 9), (3, 11), (5, 7), (5, 9), (5, 11),
        (7, 7), (7, 9), (7, 11), (9, 7), (9, 9), (9, 11)]
CAN_SET = frozenset(CANS)
STANDS = {(1, 7): (1, 6, "DOWN"), (1, 9): (1, 10, "UP"), (1, 11): (1, 12, "UP"), (3, 7): (3, 6, "DOWN"),
          (3, 9): (3, 10, "UP"), (3, 11): (3, 12, "UP"), (5, 7): (5, 6, "DOWN"), (5, 9): (5, 10, "UP"),
          (5, 11): (5, 12, "UP"), (7, 7): (7, 6, "DOWN"), (7, 9): (7, 10, "UP"), (7, 11): (7, 12, "UP"),
          (9, 7): (9, 8, "UP"), (9, 9): (9, 10, "UP"), (9, 11): (9, 12, "UP")}
WALKABLE = {s[:2] for s in STANDS.values()} | {(x, y) for x in range(10) for y in range(18)}  # fake floor


class FakePlan:
    """Stand-in for ctx.route_plan: the fixture's can cells and a Manhattan path to any goal."""

    def cells_with_tile(self, map_id, tile):
        # like the real ROM grid: the can tile also marks a non-can fixture at (6,1), filtered by can_cells
        return (set(CANS) | {(6, 1)}) if tile == gp.CAN_TILE else set()

    def __call__(self, start, goals, walls=None, blocked=None, hard=None, cut=False):
        m, gx, gy = next(iter(goals))
        x, y = start[1], start[2]
        path = ["UP"] * max(0, y - gy) + ["DOWN"] * max(0, gy - y) + ["LEFT"] * max(0, x - gx) + ["RIGHT"] * max(0, gx - x)
        return path or []


class FakeGame:
    """The real game's answer for a can press (UNVERIFIED rules): 'first', 'second', 'reset', 'nothing'."""

    def __init__(self, rng, first=None):
        self.rng = rng
        self._locks(first)

    def _locks(self, first=None):
        self.first = first if first is not None else self.rng.choice(CANS)
        self.second = self.rng.choice(gp.neighbours(CAN_SET, self.first))
        self.armed = False

    def answer(self, can):
        if not self.armed:
            if can == self.first:
                self.armed = True
                return "first"
            return "nothing"
        if can == self.second:
            return "second"
        self._locks()  # a wrong can after the first resets both locks, re-randomized
        return "reset"


def solve(solver, game):
    seen = []
    while not (solver.done or solver.gave_up):
        can = solver.next_can()
        if can is None:
            break
        seen.append(can)
        solver.record(game.answer(can))
    return seen


def make_ctx(tmp_path, memory=None, **fields):
    emu = FakeEmulator({MAP: gp.GYM, PX: 1, PY: 6, **(memory or {})})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, stable_frames=10, **fields)
    ctx.goals = lambda: {"beat_surge": False}
    ctx.route_plan = FakePlan()
    return ctx


def applies(ctx, behaviour=None):
    ctx.refresh()
    return (behaviour or GymPuzzle()).applies(ctx)


def test_neighbour_rule_is_orthogonal_only():
    assert sorted(gp.neighbours(CAN_SET, (5, 9))) == [(3, 9), (5, 7), (5, 11), (7, 9)]
    assert gp.neighbours(CAN_SET, (1, 7)) == [(1, 9), (3, 7)]      # a corner: two neighbours
    assert gp.neighbours(CAN_SET, (9, 11)) == [(7, 11), (9, 9)]    # the other corner
    assert (3, 9) not in gp.neighbours(CAN_SET, (1, 7))            # a diagonal is never a neighbour
    for can in CANS:                                               # every can's id round-trips its cell
        assert gp.can_cell(gp.can_id(can)) == can


def test_can_cells_keeps_only_real_can_cells():
    cells = gp.can_cells(FakePlan())
    assert cells == CANS                                           # the (6,1) same-tile fixture is dropped
    assert gp.can_id((6, 1)) == 3                                  # its id even collides with a real can's
    assert gp.can_cells(None) == []


def test_stand_tile_prefers_above_then_below_and_skips_blocked():
    assert gp.stand_tile((3, 7), WALKABLE, set()) == (3, 6, "DOWN")
    assert gp.stand_tile((3, 7), WALKABLE - {(3, 6)}, set()) == (3, 8, "UP")  # above not walkable: the tile below
    assert gp.stand_tile((3, 7), WALKABLE, {(3, 6)}) == (3, 8, "UP")      # a trainer stands above: below
    assert gp.stand_tile((3, 7), WALKABLE - {(3, 6), (3, 8)}, set()) is None


def test_classify_matches_the_lock_text_loosely():
    assert gp.classify("The 1st electric lock opened!") == "first"
    assert gp.classify("The 2nd electric lock opened!") == "second"
    assert gp.classify("Nope, there's only trash here! Hey! The electric locks were reset!") == "reset"
    assert gp.classify("Nope, there's only trash here.") == "nothing"
    assert gp.classify("COOLTRAINER: I saw you!") == "nothing"
    assert gp.is_can_text("trash and locks") and not gp.is_can_text("unrelated chatter")


def test_search_finds_both_locks_within_the_caps_for_many_seeds():
    unsolved = []
    for seed in range(200):
        game, s = FakeGame(random.Random(seed)), gp.Search(gp.can_cells(FakePlan()))
        solve(s, game)
        assert s.score()["tried"] <= gp.MAX_TOTAL    # the run cap is always respected
        if not s.done:
            unsolved.append((seed, s.score()))
    # a reset re-randomizes both locks, so a run can only afford ~6 armed guesses inside MAX_TOTAL:
    # most seeds solve; the rest end in the honest "gave up" (never a hang, never over-cap)
    assert len(unsolved) <= 20, f"too many gave up: {unsolved}"
    assert all(score["tried"] == gp.MAX_TOTAL for _seed, score in unsolved), unsolved  # give-ups land on the run cap


def test_reset_clears_the_tried_sets_and_counts():
    game, s = FakeGame(random.Random(0), first=(1, 7)), gp.Search(gp.can_cells(FakePlan()))
    game.second = (3, 7)                   # the wrong neighbour is then (1,9), the search's first pick
    while not game.armed:  # walk the fixed order until the first lock lands
        s.record(game.answer(s.next_can()))
    assert s.first == (1, 7) and s.hits == 1
    assert s.next_can() == (1, 9)          # untried neighbours of the first lock only
    s.record(game.answer((1, 9)))          # a wrong neighbour: the locks reset
    assert s.resets == 1 and s.first is None and not s.tried and not s.tried2 and not s.done


def test_oracle_goes_straight_and_falls_back_on_a_bad_value():
    cans = gp.can_cells(FakePlan())
    i1, i2 = gp.can_id((3, 7)), gp.can_id((3, 9))
    s = gp.make_solver("oracle", cans, [i1, i2])
    assert isinstance(s, gp.Oracle)
    game = FakeGame(random.Random(0), first=(3, 7))
    game.second = (3, 9)
    assert solve(s, game) == [(3, 7), (3, 9)]     # exactly the two lock cans, nothing else
    for ids in ([0, i2], [i1, 0], [40, i2], None):  # a zero or non-can value: back to search
        assert type(gp.make_solver("oracle", cans, ids)) is gp.Search
    assert type(gp.make_solver("search", cans, [i1, i2])) is gp.Search


def test_referee_values_never_change_search_choices():
    """The lock RAM values may reach the log only: two runs with different referee inputs must pick
    the identical can sequence (Search.next_can takes no RAM argument)."""
    seqs = []
    for referee in ([0, 0], [3, 4], [14, 11]):
        game, s = FakeGame(random.Random(7)), gp.Search(gp.can_cells(FakePlan()))
        log = []
        seen = solve(s, game)
        log += [{"can": c, "D743": referee[0], "D744": referee[1]} for c in seen]  # referee: log lines only
        seqs.append(seen)
    assert seqs[0] == seqs[1] == seqs[2]


def test_search_caps_end_the_puzzle():
    s = gp.Search(gp.can_cells(FakePlan()))
    game = FakeGame(random.Random(0), first=(9, 11))
    game.answer = lambda can: "nothing"              # the first lock never lands (missed text): the attempt cap bites
    assert solve(s, game) == CANS                    # every can tried once, then gave up
    assert s.gave_up and len(s.tried) == gp.MAX_PER_ATTEMPT
    s2 = gp.Search(gp.can_cells(FakePlan()))
    s2.total = gp.MAX_TOTAL                          # the run cap
    assert s2.next_can() is None and s2.gave_up
    assert "gym_puzzle" in NEVER_VETO                # self-capped: the loop ledger must not veto its presses


def test_mode_resolution_and_rejection():
    assert gp.resolve_mode(None, None) == "search"
    assert gp.resolve_mode(None, "oracle") == "oracle"
    assert gp.resolve_mode("search", "oracle") == "search"   # the CLI flag wins over the env var
    try:
        gp.resolve_mode("magic", None)
    except ValueError as e:
        assert "magic" in str(e)
    else:
        raise AssertionError("a bad mode must be rejected")


def test_behaviour_only_fires_in_the_gym_with_the_locks_closed(tmp_path):
    b = GymPuzzle()
    ctx = make_ctx(tmp_path)
    assert applies(ctx, b)
    ctx2 = make_ctx(tmp_path, memory={MAP: 0x05})    # outside the gym: silent
    assert not applies(ctx2, b)
    ctx3 = make_ctx(tmp_path)
    ctx3.goals = lambda: {"beat_surge": True}        # the badge is already in hand: nothing to open
    assert not applies(ctx3, b)
    ctx4 = make_ctx(tmp_path)
    ctx4.emu.set(BATTLE, 1)                          # a gym trainer fight: silent
    assert not applies(ctx4, b)
    ctx5 = make_ctx(tmp_path)
    ctx5.proc = {"name": "x"}                        # a procedure owns the screen: silent
    assert not applies(ctx5, b)
    ctx7 = make_ctx(tmp_path)
    ctx7.emu.set(TM + 20 * 10, 0x79)                 # a text box is open: the dialog behaviours own it
    ctx7.emu.set(TM + 20 * 10 + 1, 0x7A)
    assert not applies(ctx7, b)
    ctx6 = make_ctx(tmp_path)
    gp.state(ctx6)["open"] = True                    # barrier already read open: the puzzle stops applying
    assert not applies(ctx6, b)


def test_behaviour_walks_faces_presses_and_judges_a_can(tmp_path):
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 1, PY: 8})   # below can (1,7); stand tile is (1,6)
    ctx.facing = "UP"
    ctx.refresh()
    d = b.step(ctx)                                                  # not on the stand tile: walk toward it
    assert d.button == "UP" and d.rule == "gym_puzzle_walk"
    ctx = make_ctx(tmp_path, memory={PX: 1, PY: 6})                  # on the stand tile, facing wrong
    ctx.facing = "UP"
    ctx.refresh()
    d = b.step(ctx)
    assert (d.button, d.rule) == ("DOWN", "gym_puzzle_face")
    ctx.facing = "DOWN"                                              # facing the can: one A press
    d = b.step(ctx)
    assert (d.button, d.rule) == ("A", "gym_puzzle_press")
    ctx.dialog = ["NOPE  THERE'S ONLY TRASH HERE"]                   # the can's text came and went
    ctx.talk_closed_frame = ctx.frame + 1
    d = b.step(ctx)
    assert d.rule == "gym_puzzle_judge" and "nothing" in d.why
    st = gp.state(ctx)
    assert (1, 7) in st["solver"].tried and st["can"] is None        # judged: on to the next can


def test_the_second_lock_opens_the_barrier_for_goal_talk(tmp_path):
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 1, PY: 6})
    ctx.facing = "DOWN"
    ctx.refresh()
    assert b.step(ctx).button == "A"
    ctx.dialog = ["THE 2ND ELECTRIC LOCK OPENED!"]
    ctx.talk_closed_frame = ctx.frame + 1
    b.step(ctx)
    st = gp.state(ctx)
    assert st["open"] and gp.is_open(ctx) and st["solver"].done      # goal_talk's guard reads this flag
    ctx.refresh()
    assert not b.applies(ctx)


def test_a_miss_waits_then_retries_and_the_press_cap_gives_up(tmp_path):
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 1, PY: 6})
    ctx.facing = "DOWN"
    ctx.refresh()
    assert b.step(ctx).button == "A"
    st = gp.state(ctx)
    for _ in range(6):                                               # no box ever comes: bounded waits, then a miss
        assert b.step(ctx).rule == "gym_puzzle_wait"
    d = b.step(ctx)
    assert d.rule == "gym_puzzle_fail" and st["tries"][(1, 7)] == 1 and st["cooldown_until"] > ctx.step
    assert not applies(ctx, b)                                       # cooling down: silent
    ctx.step = st["cooldown_until"]
    st["presses"] = 40                                               # PRESS_CAP spent on this can
    d = b.step(ctx)
    assert d.rule == "gym_puzzle_fail" and st["tries"][(1, 7)] == 2


def test_goal_talk_is_held_until_the_barrier_reads_open(tmp_path):
    from pokeagent.explorer.behaviours.goal_talk import GOAL_TALKS, APPROACH, pending
    assert GOAL_TALKS["beat_surge"] == (0x5C, 5, 2, "UP", "Lt. Surge") and "beat_surge" in APPROACH
    ctx = make_ctx(tmp_path, memory={PX: 5, PY: 3})
    ctx.gym_hold_seen = (0, False)                                   # the readiness hold is clear: only the barrier gates
    ctx.refresh()
    assert pending(ctx) is None                                      # barrier closed: do not walk to Surge
    gp.state(ctx)["open"] = True
    hit = pending(ctx)
    assert hit == ("beat_surge", GOAL_TALKS["beat_surge"])           # open: the walk to Lt. Surge is on
