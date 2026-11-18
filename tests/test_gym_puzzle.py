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
    """The real game's answer for a can press (pokered ground truth, cited by the controller): the
    1st lock is a random can; while it is open ANY press but the 2nd lock's can resets (D743
    re-randomizes, D744 is NEVER cleared - a stale index while unarmed). ``flags`` is the lock event
    byte the referee reads: bit1 = 1st lock opened, bit0 = 2nd."""

    def __init__(self, rng, first=None):
        self.rng = rng
        self.d744 = 0                       # never cleared: stale while the 1st lock is closed
        self._locks(first)

    def _locks(self, first=None):
        self.first = first if first is not None else self.rng.choice(CANS)
        self.second = self.rng.choice(gp.neighbours(CAN_SET, self.first))  # D744 names it once armed
        self.flags = 0x00                   # a reset drops the 1st-lock bit; D744 keeps its stale index

    def ram(self):
        """(D743, D744, D773) as the referee and the oracle read them."""
        return gp.can_id(self.first), self.d744, self.flags

    def answer(self, can):
        if not (self.flags & gp.FLAG_1ST):
            if can == self.first:
                self.flags |= gp.FLAG_1ST
                self.d744 = gp.can_id(self.second)
                return "first"
            return "nothing"
        if can == self.second:
            self.flags |= gp.FLAG_2ND
            return "second"
        self._locks()  # a wrong can while the 1st lock is open resets it, D743 re-randomized
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


def solve_blind(solver, game, locks=None):
    """Solve with the answer text lost on every press (--fast-text flashed the box): the only verdict is
    referee_result's diff of the lock event byte. ``locks`` = the live set_locks feed an Oracle gets."""
    seen = []
    while not (solver.done or solver.gave_up):
        if locks is not None:
            solver.set_locks(*game.ram())
        can = solver.next_can()
        if can is None:
            break
        seen.append(can)
        before = game.ram()
        game.answer(can)                        # the outcome lands in the event byte; its text is never seen
        solver.record(gp.referee_result(before[2], game.ram()[2]) or "nothing")
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
    # the four pokered lines (data/text/text_2.asm:714-748, cited by the controller round 5)
    assert gp.classify("Hey! There's a switch under the trash! Turn it on! "
                       "The 1st electric lock opened!") == "first"
    assert gp.classify("The 2nd electric lock opened! The motorized door opened!") == "second"
    assert gp.classify("Nope! There's only trash here. Hey! The electric locks were reset!") == "reset"
    assert gp.classify("Nope, there's only trash here.") == "nothing"     # the comma Nope: never armed
    assert gp.classify("Nope! There | only tra") == "reset"               # a fast-text flash keeps Nope!
    assert gp.classify("COOLTRAINER: I saw you!") == "nothing"
    assert gp.is_can_text("trash and locks") and gp.is_can_text("The 2nd electric / lock opened!")
    assert not gp.is_can_text("unrelated chatter")


def test_search_finds_both_locks_within_the_caps_for_many_seeds():
    unsolved = []
    for seed in range(200):
        game, s = FakeGame(random.Random(seed)), gp.Search(gp.can_cells(FakePlan()))
        solve(s, game)
        assert s.score()["tried"] <= gp.MAX_TOTAL    # the run cap is always respected
        if not s.done:
            unsolved.append((seed, s.score()))
    # a reset re-randomizes both locks; inside MAX_TOTAL=250 a run affords ~27 armed guesses, so
    # near-every seed solves and the rare rest end in the honest "gave up" (never a hang, over-cap)
    assert len(unsolved) <= 2, f"too many gave up: {unsolved}"
    assert all(score["tried"] == gp.MAX_TOTAL for _seed, score in unsolved), unsolved  # give-ups land on the run cap


def test_reset_clears_the_tried_sets_and_counts():
    game, s = FakeGame(random.Random(0), first=(1, 7)), gp.Search(gp.can_cells(FakePlan()))
    game.second = (3, 7)                   # the wrong neighbour is then (1,9), the search's first pick
    while not (game.flags & gp.FLAG_1ST):  # walk the fixed order until the first lock lands
        s.record(game.answer(s.next_can()))
    assert s.first == (1, 7) and s.hits == 1
    assert s.next_can() == (1, 9)          # the ONE armed guess: an untried neighbour of the first lock
    s.record(game.answer((1, 9)))          # a wrong neighbour while armed: the locks reset
    assert s.resets == 1 and s.first is None and not s.tried and not s.done


def test_an_armed_press_never_answers_nothing_and_costs_one_guess():
    """pokered: while the 1st lock is open every press but D744's resets - there is no probing the
    neighbours, just one guess per arming. A 'nothing' verdict that slips in anyway (a lost page)
    spends the guess and moves on instead of looping on it."""
    s = gp.Search(gp.can_cells(FakePlan()))
    s.next_can(); s.record("first")        # can (1,7) armed the lock
    assert s.next_can() == (1, 9)
    s.record("nothing")                    # impossible per the model: the guess is spent, not retried
    assert s.next_can() == (3, 7)
    s.record("nothing")
    assert s.next_can() == (1, 11)         # neighbours exhausted: the arming is spent, the hunt resumes
    assert s.first is None


def test_oracle_goes_straight_to_each_lock_as_the_game_arms_it():
    """The plan is leg by leg on the event bit: D743's can while the 1st-lock bit is clear, the live
    D744's once it reads set (D744 is never cleared - a stale index would send the walk astray)."""
    cans = gp.can_cells(FakePlan())
    s = gp.make_solver("oracle", cans, [gp.can_id((3, 7)), 0, 0])
    assert isinstance(s, gp.Oracle)
    assert s.next_can() == (3, 7)                          # only the first leg while the bit is clear
    s.record("first")
    s.set_locks(gp.can_id((3, 7)), gp.can_id((3, 9)), gp.FLAG_1ST)  # armed: the behaviour's fresh read
    assert s.next_can() == (3, 9)                          # straight to the second lock
    s.record("second")
    assert s.done


def test_oracle_ignores_a_stale_d744_while_the_first_lock_is_closed():
    """D744 is never cleared, so a leftover index sitting in it means nothing until the bit says
    armed - the round-4 bug: 'second' logged on a comma-Nope press because stale D744 matched."""
    cans = gp.can_cells(FakePlan())
    s = gp.make_solver("oracle", cans, [gp.can_id((3, 7)), gp.can_id((3, 9)), 0])
    assert s.next_can() == (3, 7)                          # the stale D744 is ignored, not a target
    s = gp.make_solver("oracle", cans, [gp.can_id((3, 7)), gp.can_id((3, 9)), gp.FLAG_1ST])
    assert s.next_can() == (3, 9)                          # the same index is the target once armed


def test_oracle_follows_a_re_randomized_first_index():
    cans = gp.can_cells(FakePlan())
    s = gp.make_solver("oracle", cans, [gp.can_id((3, 7)), 0, 0])
    assert s.next_can() == (3, 7)
    s.record("nothing")                                    # the read was stale: the lock moved
    s.set_locks(gp.can_id((9, 11)), 0, 0)                  # D743 re-randomized (14->2->0->14 in the live run)
    assert s.next_can() == (9, 11)


def test_oracle_falls_back_per_pick_on_a_bad_value():
    cans = gp.can_cells(FakePlan())
    for ids in ([40, 40], None):
        s = gp.make_solver("oracle", cans, ids)
        assert isinstance(s, gp.Oracle)                    # always an oracle; the bad leg falls back
        assert s.next_can() == cans[0]                     # ... to the plain search order
    s = gp.make_solver("oracle", cans, [0, 0])
    assert s.next_can() == (1, 7)                          # index 0 is can 0, a real index (no sentinel)
    assert type(gp.make_solver("search", cans, [1, 2])) is gp.Search


def test_referee_result_reads_the_lock_event_flags():
    """The referee is the lock event byte 0xD773 (UNVERIFIED base): bit1 = 1st lock, bit0 = 2nd - the
    controller's live read moved it 0x1E -> 0x1F on the 2nd-lock press. The D743/D744 pair is never
    judged: a stale D744 equal to the pressed can with bit1 clear is NOT a second (the round-4 bug)."""
    assert gp.referee_result(0x00, 0x02) == "first"      # 00 -> 10
    assert gp.referee_result(0x02, 0x00) == "reset"      # 10 -> 00 (the only way bit1 drops)
    assert gp.referee_result(0x02, 0x03) == "second"     # 10 -> 11
    assert gp.referee_result(0x1E, 0x1F) == "second"     # the live read itself
    assert gp.referee_result(0x00, 0x00) is None         # unmoved: no lock answer, however the pair sits
    assert gp.referee_result(0x02, 0x02) is None


def test_solve_blind_finds_both_locks_on_the_event_flag_alone():
    """--fast-text flashes every box: the only verdict is the event-byte diff, which is exact - the
    can-0 blind spot of the old pair-diff referee is gone (0 is a real index, the bits say armed)."""
    unsolved = []
    for seed in range(200):
        game, s = FakeGame(random.Random(seed)), gp.Search(gp.can_cells(FakePlan()))
        solve_blind(s, game)
        if not s.done:
            unsolved.append((seed, s.score()))
    assert len(unsolved) <= 2, f"too many gave up: {unsolved}"


def test_oracle_solves_blind_in_exactly_two_presses():
    for seed in range(50):
        game = FakeGame(random.Random(seed))
        first, second = game.first, game.second            # a straight run never resets: the pair holds
        s = gp.make_solver("oracle", gp.can_cells(FakePlan()), list(game.ram()))
        seen = solve_blind(s, game, locks=game)
        assert s.done and seen == [first, second], (seed, seen)   # straight there, two presses


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


def test_search_solves_random_lock_games_inside_the_run_cap():
    """The round-4 gate (the controller, 2026-11-17): a simulated game with random locks per seed
    must solve within MAX_TOTAL in >= 99% - the round-3 live run died on MAX_TOTAL=60 with every
    verdict correct, so the caps must make success near-certain, not lucky."""
    unsolved = []
    for seed in range(100):
        game, s = FakeGame(random.Random(seed)), gp.Search(gp.can_cells(FakePlan()))
        solve(s, game)
        if not s.done:
            unsolved.append((seed, s.score()))
    assert len(unsolved) <= 1, f"too many gave up: {unsolved}"


def test_search_caps_end_the_puzzle():
    s = gp.Search(gp.can_cells(FakePlan()))
    game = FakeGame(random.Random(0), first=(9, 11))
    game.answer = lambda can: "nothing"              # every answer lost: the capped loop retries each pass,
    seen = solve(s, game)                            # then gives up on the run cap - never a hang
    assert s.gave_up and len(seen) == gp.MAX_TOTAL and s.attempts > 1
    s2 = gp.Search(gp.can_cells(FakePlan()))
    s2.total = gp.MAX_TOTAL                          # the run cap
    assert s2.next_can() is None and s2.gave_up
    s3 = gp.Search(gp.can_cells(FakePlan()))
    for can in s3.cans:                              # every can unreachable: nothing left to press
        s3.skip(can)
    assert s3.next_can() is None and s3.gave_up      # ... so passes alone cannot loop forever
    assert "gym_puzzle" in NEVER_VETO                # self-capped: the loop ledger must not veto its presses


def test_a_lost_first_pass_does_not_end_the_run():
    """The controller's fix: one pass of misses used to be 'gave up'. Now the next pass starts over -
    a flashed box that hid the first hit gets retried until the run cap."""
    game = FakeGame(random.Random(0), first=(9, 11))
    game._locks = lambda first=None: (setattr(game, "first", (9, 11)), setattr(game, "second", (7, 11)),
                                      setattr(game, "flags", 0))      # a fixed lock pair, reset after reset
    game._locks()                                                     # pin the initial pair too
    s = gp.Search(gp.can_cells(FakePlan()))
    seen = []
    while not (s.done or s.gave_up):
        can = s.next_can()
        if can is None:
            break
        seen.append(can)
        s.record("nothing" if s.attempts == 1 else game.answer(can))  # pass one's answers all lost
    assert s.done and s.attempts >= 2 and len(seen) > gp.MAX_PER_ATTEMPT


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


D743, D744 = gp.LOCK_ADDRS
D773 = gp.LOCK_FLAGS


def test_a_hit_is_counted_when_the_answer_text_flashed_past(tmp_path):
    """--fast-text can drop every page of the can's box: no close event, no text, but the lock event
    byte moved. That diff is the verdict (the live run logged 'nothing' on a real first hit here)."""
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 1, PY: 6, D743: 7, D744: 0})
    ctx.facing = "DOWN"
    ctx.refresh()
    assert b.step(ctx).button == "A"                                  # press at the first can, (1,7)
    ctx.emu.set(D744, gp.can_id((1, 9)))                              # the game armed a second lock, unseen
    ctx.emu.set(D773, gp.FLAG_1ST)                                    # the 1st-lock bit landed
    d = b.step(ctx)
    assert d.rule == "gym_puzzle_judge" and "first" in d.why
    assert gp.state(ctx)["solver"].first == (1, 7)


def test_an_armed_reset_is_counted_without_text(tmp_path):
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 1, PY: 6, D743: 7,
                                                     D744: gp.can_id((3, 9)), D773: gp.FLAG_1ST})
    ctx.facing = "DOWN"
    ctx.refresh()
    assert b.step(ctx).button == "A"                                  # press can (1,7), not the armed one
    ctx.emu.set(D743, 12)                                             # the locks re-randomized, unseen
    ctx.emu.set(D773, 0)                                              # the 1st-lock bit dropped (D744 stays stale)
    d = b.step(ctx)
    assert d.rule == "gym_puzzle_judge" and "reset" in d.why
    assert gp.state(ctx)["solver"].resets == 1


def test_the_barrier_tile_read_can_open_the_gate(tmp_path):
    """The stepping tiles read 48/17 closed and all 17 once the 2nd lock opens (the controller's
    round-5 read) - a known open signal now, not just a logged change."""
    px, py = 4, 8
    tiles = {TM + (2 * (by - py + 4) + 1) * 20 + 2 * (bx - px + 4): gp.BARRIER_OPEN_TILE
             for bx, by in gp.BARRIER}
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: px, PY: py, **tiles})
    assert not applies(ctx, b)                        # the door reads open: the puzzle stops applying
    assert gp.state(ctx)["open"]
    ctx2 = make_ctx(tmp_path, memory={PX: px, PY: py, TM + 28: 48})   # a 48 in the mix: closed
    assert applies(ctx2, b)


def test_oracle_walks_to_the_named_can_not_the_first_in_order(tmp_path):
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 5, PY: 10, D743: gp.can_id((9, 11)), D744: 0})
    ctx.opts.gym_puzzle_mode = "oracle"
    ctx.facing = "UP"
    ctx.refresh()
    d = b.step(ctx)                                                   # stand tile of can 14 is (9,10): walk right
    assert d.rule == "gym_puzzle_walk" and "can 14" in d.why
    st = gp.state(ctx)
    assert st["can"] == (9, 11)                                       # D743's can, not cans[0]


def test_oracle_repicks_when_the_first_index_moves(tmp_path):
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 5, PY: 10, D743: gp.can_id((9, 11)), D744: 0})
    ctx.opts.gym_puzzle_mode = "oracle"
    ctx.facing = "UP"
    ctx.refresh()
    b.step(ctx)
    st = gp.state(ctx)
    assert st["can"] == (9, 11)
    ctx.emu.set(D743, gp.can_id((1, 9)))                              # the lock moved mid-walk: re-pick
    d = b.step(ctx)
    assert st["can"] == (1, 9) and "can 1" in d.why


def test_search_mode_never_lets_ram_pick_the_can(tmp_path):
    """The referee pair only scores a made press: two runs, different RAM, identical first pick."""
    picks = []
    for first_idx in (0, gp.can_id((9, 11))):
        ctx = make_ctx(tmp_path, memory={PX: 1, PY: 6, D743: first_idx, D744: 0})
        ctx.facing = "DOWN"
        ctx.refresh()
        b = GymPuzzle()
        d = b.step(ctx)
        picks.append(gp.state(ctx)["can"])
        assert d.rule in ("gym_puzzle_walk", "gym_puzzle_face", "gym_puzzle_press")
    assert picks == [(1, 7), (1, 7)]                                  # the fixed order, both times


def test_purge_walls_touching_drops_only_edges_on_the_cells():
    """Either endpoint counts: a wall learned ON a barrier cell and its ENTRY edges both go."""
    from pokeagent.explorer import memory_purge
    data = {"maps": {"92": {"blocked": ["5,5,UP", "5,6,UP", "3,4,RIGHT", "5,4,LEFT", "9,9,UP", "5,8,UP"],
                            "fails": {"5,5,UP": 2, "9,9,UP": 1}}}}
    gone = memory_purge.purge_walls_touching(data, gp.GYM, gp.BARRIER)
    assert sorted(gone) == ["3,4,RIGHT", "5,4,LEFT", "5,5,UP", "5,6,UP"]  # on or into barrier cells
    assert data["maps"]["92"]["blocked"] == ["9,9,UP", "5,8,UP"]          # order kept, others stay
    assert data["maps"]["92"]["fails"] == {"9,9,UP": 1}                   # the fail counters went too
    assert memory_purge.purge_walls_touching(data, 0x01, gp.BARRIER) == []


def test_opened_forgets_the_walls_the_closed_barrier_taught(tmp_path):
    """Round 3 (the controller's real-ROM bounce): the UP edge out of (5,5), learned bumping the CLOSED
    barrier, left beat_surge oscillating under an OPEN gate - 'nearest known tile' (5,5) with UP ruled
    out. The 'opened' verdict forgets every learned edge touching a barrier cell, and the learned
    goal path then crosses the barrier."""
    from pokeagent.explorer.world import WorldGraph
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 1, PY: 6})
    d = ctx.mem.m(gp.GYM)
    d["visited"] = {f"{x},{y}": 1 for x, y in ((5, 5), (5, 4), (5, 3), (5, 2), (5, 6), (4, 5))}
    d["blocked"] = ["5,5,UP", "5,6,UP", "3,4,RIGHT", "9,9,UP"]
    g = WorldGraph(ctx.mem.data["maps"])
    assert g._bfs_node((gp.GYM, 5, 5), lambda n: n == (gp.GYM, 5, 2), 100) is None  # strict: the wall shuts it
    ctx.facing = "DOWN"
    ctx.refresh()
    assert b.step(ctx).button == "A"
    ctx.dialog = ["THE 2ND ELECTRIC LOCK OPENED!"]
    ctx.talk_closed_frame = ctx.frame + 1
    b.step(ctx)
    assert gp.state(ctx)["open"]
    assert d["blocked"] == ["9,9,UP"]                                   # barrier edges forgot, others stay
    g = WorldGraph(ctx.mem.data["maps"])
    assert g._bfs_node((gp.GYM, 5, 5), lambda n: n == (gp.GYM, 5, 2), 100) == \
        ((gp.GYM, 5, 2), ["UP", "UP", "UP"])                            # the goal path passes the barrier


def test_reset_forgets_the_barrier_walls_too(tmp_path):
    """A reset re-randomizes the locks: the barrier's state moved, so its learned bumps are just as stale."""
    b, ctx = GymPuzzle(), make_ctx(tmp_path, memory={PX: 1, PY: 6})
    d = ctx.mem.m(gp.GYM)
    d["blocked"] = ["5,5,UP", "9,9,UP"]
    ctx.facing = "DOWN"
    ctx.refresh()
    assert b.step(ctx).button == "A"
    ctx.dialog = ["NOPE  THERE'S ONLY TRASH HERE  HEY  THE ELECTRIC LOCKS WERE RESET!"]
    ctx.talk_closed_frame = ctx.frame + 1
    d2 = b.step(ctx)
    assert d2.rule == "gym_puzzle_judge" and "reset" in d2.why
    assert d["blocked"] == ["9,9,UP"]
