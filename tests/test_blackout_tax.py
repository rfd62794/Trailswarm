"""The blackout tax: per-stage readiness-margin steps learned from blackouts and decayed by trainer wins."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer import training
from pokeagent.explorer.grind import record_battle_result
from pokeagent.goals import GOALS
from pokeagent.knowledge import blackout_tax, kb as kbmod
from pokeagent.knowledge.readiness import MARGIN, assess
from test_knowledge import BOSS, SYN, _starter  # noqa: F401  (synthetic cartridge: AQUA water, BLAZE fire, PEBBLE rock/ground)


def _after(last_done: str) -> dict:
    i = GOALS.index(last_done)
    return {g: n <= i for n, g in enumerate(GOALS)}


def _rom(monkeypatch, trainers_tbl):
    monkeypatch.setattr(kbmod, "ROM_KB", {**SYN, "trainers": trainers_tbl})
    training._cache.clear()


def test_blackout_steps_climb_to_the_cap_and_wins_decay_and_remove_the_goal():
    data = {}
    for _ in range(6):
        last = blackout_tax.on_blackout(data, "rival_ss_anne")
    assert last == blackout_tax.MAX_STEPS == 4                       # the cap holds past MAX_STEPS calls
    assert data["blackout_tax"] == {"rival_ss_anne": {"steps": 4}}   # steps stored as an int, never a float
    assert blackout_tax.steps(data, "rival_ss_anne") == 4
    assert blackout_tax.extra_margin(data, "rival_ss_anne") == 0.4
    assert blackout_tax.on_win(data, "rival_ss_anne") == 3
    assert blackout_tax.on_win(data, "rival_ss_anne") == 2
    assert blackout_tax.steps(data, "rival_ss_anne") == 2
    assert blackout_tax.extras(data) == {"rival_ss_anne": 0.2}
    assert blackout_tax.on_win(data, "rival_ss_anne") == 1
    assert blackout_tax.on_win(data, "rival_ss_anne") == 0
    assert "rival_ss_anne" not in data["blackout_tax"]               # a stage at zero steps is removed
    assert blackout_tax.extras(data) == {}


def test_malformed_tables_are_treated_as_empty_and_never_raise():
    for data in ({}, {"blackout_tax": None}, {"blackout_tax": {"g": "x"}}):
        assert blackout_tax.steps(data, "g") == 0
        assert blackout_tax.extra_margin(data, "g") == 0.0
        assert blackout_tax.extras(data) == {}
        assert blackout_tax.on_win(data, "g") == 0
    data = {"blackout_tax": None}
    assert blackout_tax.on_blackout(data, "g") == 1                  # a malformed key is replaced, not raised on
    assert data["blackout_tax"] == {"g": {"steps": 1}}


def test_assess_margin_parameter_and_default():
    fire = _starter("BLAZE", 10, ["TACKLE", "EMBER"])                # resisted vs ROCK/GROUND: needs the levels
    low = assess([fire], BOSS, "BROCK", SYN, margin=0.3)
    high = assess([fire], BOSS, "BROCK", SYN, margin=0.7)
    assert high.required >= low.required
    assert assess([fire], BOSS, "BROCK", SYN) == assess([fire], BOSS, "BROCK", SYN, margin=MARGIN)


def test_set_blackout_tax_raises_the_required_level_and_clears(monkeypatch):
    _rom(monkeypatch, {"LT.SURGE": [[[21, "PEBBLE"], [24, "PEBBLE"]]]})
    goals = _after("bicycle")                                        # next stage: beat_surge
    water = _starter("AQUA", 10, ["TACKLE", "WATER GUN"])
    try:
        training.set_blackout_tax({})
        base = training.readiness_for(goals, [water]).required
        training.set_blackout_tax({"beat_surge": 0.4})
        taxed = training.readiness_for(goals, [water]).required
        assert taxed > base
        training.set_blackout_tax({})
        assert training.readiness_for(goals, [water]).required == base
    finally:
        training.set_blackout_tax({})
        training._cache.clear()


def test_record_battle_result_feeds_the_tax():
    ctx = SimpleNamespace(stage_goal="rival_ss_anne", mem=SimpleNamespace(data={}), blackouts_row=0)
    record_battle_result(ctx, won=False, moved_away=True, trainer=False)   # any blackout counts
    assert ctx.blackouts_row == 1
    assert blackout_tax.steps(ctx.mem.data, "rival_ss_anne") == 1
    record_battle_result(ctx, won=True, moved_away=False, trainer=True)    # a trainer win decays one step
    assert ctx.blackouts_row == 0
    assert ctx.mem.data["blackout_tax"] == {}                             # removed at zero steps
    record_battle_result(ctx, won=False, moved_away=True, trainer=False)
    assert ctx.blackouts_row == 1 and blackout_tax.steps(ctx.mem.data, "rival_ss_anne") == 1
    record_battle_result(ctx, won=True, moved_away=False, trainer=False)   # a wild win resets the row, never the tax
    assert ctx.blackouts_row == 0
    assert blackout_tax.steps(ctx.mem.data, "rival_ss_anne") == 1
    record_battle_result(ctx, won=False, moved_away=False, trainer=False)  # a flee changes nothing
    assert ctx.blackouts_row == 0 and blackout_tax.steps(ctx.mem.data, "rival_ss_anne") == 1


def test_record_battle_result_with_no_stage_goal_records_nothing():
    ctx = SimpleNamespace(stage_goal=None, mem=SimpleNamespace(data={}), blackouts_row=0)
    record_battle_result(ctx, won=False, moved_away=True, trainer=True)
    assert ctx.blackouts_row == 1
    assert "blackout_tax" not in ctx.mem.data
