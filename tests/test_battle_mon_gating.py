"""Stale wBattleMon gating: a species byte of 0 must never supply HP, level, moves or PP.

wBattleMon is half-filled at battle start (measured: wBattleMonSpecies 0 with HP 15, level 6,
max 21 left over from the last fight). Every reader goes through read_battle_view(emu).battle_mon,
which is None while the block is stale; with the species byte written nothing changes.
"""
from __future__ import annotations

from pokeagent.adapters.event_feed import EventFeed
from pokeagent.explorer.battle import move_scores
from pokeagent.explorer.behaviours.already_out import AlreadyOutGuard
from pokeagent.explorer.behaviours.bring_out import forced_faint_prompt
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.perceive import battle_view
from pokeagent.explorer.press import begin_press
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.intervene.screen import battle_moves as screen_battle_moves
from pokeagent.observations import combat_observation
from pokeagent.world import events as ev

from test_explorer_behaviours import make_ctx, put_box

BATTLE = 0xD057
STALE = {BATTLE: 1, 0xD016: 15, 0xD022: 6, 0xD024: 21,          # wBattleMon: species 0, HP 15, level 6, max 21
         0xD01C: 33, 0xD01D: 45, 0xD02D: 20, 0xD02E: 30}       # ... plus stale move/PP leftovers
LOADED = {**STALE, 0xD014: 0x99}                                # the same block with the species written


class _Bus:
    def __init__(self) -> None:
        self.events = []

    def emit(self, e) -> None:
        self.events.append(e)


def test_forced_faint_prompt_is_false_while_stale(tmp_path):
    lines = ["Bring out which POKeMON?"]
    stale = make_ctx(tmp_path, memory=STALE)
    assert forced_faint_prompt(stale, lines) is False
    loaded = make_ctx(tmp_path, memory=LOADED)
    assert forced_faint_prompt(loaded, lines) is False  # loaded, HP 15: not fainted
    loaded.emu.set(0xD016, 0)                           # loaded, HP 0: the real forced prompt
    assert forced_faint_prompt(loaded, lines) is True


def test_already_out_presses_nothing_while_stale(tmp_path):
    stale = make_ctx(tmp_path, memory=STALE)
    put_box(stale, text_rows=("WARTORTLE is", "already out!"))
    stale.refresh()
    assert AlreadyOutGuard().step(stale) is None
    loaded = make_ctx(tmp_path, memory=LOADED)
    put_box(loaded, text_rows=("WARTORTLE is", "already out!"))
    loaded.refresh()
    assert AlreadyOutGuard().step(loaded).button == "B"


def test_battle_view_shows_no_leftover_numbers_while_stale(tmp_path):
    stale = make_ctx(tmp_path, memory=STALE)
    rows = battle_view(stale.emu)
    assert rows[1] == "you  (not loaded)"
    assert "15" not in rows[1] and "21" not in rows[1]
    loaded = make_ctx(tmp_path, memory=LOADED)
    rows = battle_view(loaded.emu)
    assert rows[1].rstrip() == "you   L6   HP  15/21"


def test_press_battle_log_records_zeros_while_stale(tmp_path):
    stale = make_ctx(tmp_path, memory=STALE)
    put_box(stale, menu=True)
    begin_press(stale, PressFrame("A", "agent", "pick a move"))
    assert stale.battle_log["you"] == [0, 0] and stale.battle_log["turns"][0]["hp_you"] == 0
    loaded = make_ctx(tmp_path, memory=LOADED)
    put_box(loaded, menu=True)
    begin_press(loaded, PressFrame("A", "agent", "pick a move"))
    assert loaded.battle_log["you"] == [0x99, 6] and loaded.battle_log["turns"][0]["hp_you"] == 15


def test_event_feed_has_no_own_mon_while_stale(tmp_path):
    bus = _Bus()
    feed = EventFeed(bus=bus)
    stale = make_ctx(tmp_path, memory=STALE)
    feed.observe(stale.emu, stale)
    assert not any(isinstance(e, (ev.BattleStart, ev.BattleTurn)) for e in bus.events)
    loaded = make_ctx(tmp_path, memory=LOADED)
    feed.observe(loaded.emu, loaded)
    starts = [e for e in bus.events if isinstance(e, ev.BattleStart)]
    assert len(starts) == 1 and starts[0].own_level == 6 and starts[0].hp == 15 and starts[0].max_hp == 21


def test_combat_observation_is_zero_buckets_while_stale(tmp_path):
    assert combat_observation(make_ctx(tmp_path, memory=STALE).emu) == (0,) * 13
    loaded = combat_observation(make_ctx(tmp_path, memory=LOADED).emu)
    assert loaded[0] == 1 and loaded[3] == 6 and loaded[4] == 4 * 15 // 21


def test_move_scores_treats_stale_moves_as_unknown(tmp_path):
    assert move_scores(make_ctx(tmp_path, memory=STALE).emu) == {}
    if ROM_KB:
        assert move_scores(make_ctx(tmp_path, memory=LOADED).emu)


def test_screen_battle_moves_is_empty_while_stale(tmp_path):
    assert screen_battle_moves(make_ctx(tmp_path, memory=STALE).emu) == []
    assert len(screen_battle_moves(make_ctx(tmp_path, memory=LOADED).emu)) == 2  # moves 33 and 45
