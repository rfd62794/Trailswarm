"""PP-zero move guard: usable_moves / cursor_step purity, STRUGGLE on the first all-zero read,
and no A press on an empty move however long the cursor walk runs. Synthetic only: FakeEmulator, no ROM."""
from __future__ import annotations

import pytest

from pokeagent.explorer.behaviours import battle_moves as bms
from pokeagent.explorer.behaviours.battle import BattleView
from pokeagent.explorer.behaviours.battle_moves import BattleMoves
from pokeagent.explorer.behaviours.battle_pp import cursor_step, usable_moves
from test_battle_types import BATTLE, make_ctx, put_box

MOVES = ["SCRATCH", "GROWL", "EMBER", "LEER"]


# --- usable_moves ---
def test_usable_moves_excludes_zero_pp():
    assert usable_moves(MOVES, (35, 40, 0, 30), set()) == ["SCRATCH", "GROWL", "LEER"]


def test_usable_moves_masks_off_the_pp_up_bits():
    assert usable_moves(["A", "B"], (0xC0, 0x45), set()) == ["B"]  # 0xC0: 0 PP under two PP Ups; 0x45: 5 PP


def test_usable_moves_honours_the_refusal_set():
    assert usable_moves(MOVES, (35, 40, 25, 30), {"SCRATCH"}) == ["GROWL", "EMBER", "LEER"]


def test_usable_moves_all_zero_read_vs_missing_read():
    assert usable_moves(MOVES, (0, 0, 0, 0), set()) == []          # a real all-zero read: nothing usable
    assert usable_moves(MOVES, None, set()) == MOVES               # a stale struct: no PP data at all
    assert usable_moves(MOVES, None, {"EMBER"}) == ["SCRATCH", "GROWL", "LEER"]


def test_usable_moves_slot_beyond_the_pp_bytes_is_unusable():
    assert usable_moves(MOVES, (35, 40), set()) == ["SCRATCH", "GROWL"]


# --- cursor_step ---
@pytest.mark.parametrize("nav", [0, 5, 6, 50])
def test_cursor_step_never_presses_a_on_an_empty_move(nav):
    usable = ["SCRATCH", "GROWL", "LEER"]
    assert cursor_step("EMBER", "SCRATCH", usable, nav) == ("down", None)
    assert cursor_step("EMBER", "EMBER", usable, nav) == ("down", None)  # even as target it cannot be pressed


def test_cursor_step_takes_a_usable_move_only_after_five_walks():
    usable = ["SCRATCH", "GROWL", "LEER"]
    for nav in (0, 1, 5):
        assert cursor_step("GROWL", "SCRATCH", usable, nav) == ("down", None)
    for nav in (6, 7, 50):
        assert cursor_step("GROWL", "SCRATCH", usable, nav) == ("press_a", "GROWL")
    assert cursor_step("SCRATCH", "SCRATCH", usable, 0) == ("press_a", "SCRATCH")  # on target: press at once


# --- BattleMoves.step on the stub view (same harness as test_battle_types) ---
def _menu_ctx(tmp_path, memory):
    ctx = make_ctx(tmp_path, memory={BATTLE: 1, 0xCFE6: 0, 0xCFE7: 20, 0xCFF3: 3,
                                     0xCFF4: 0, 0xCFF5: 30, **memory})
    put_box(ctx, ("FIGHT", "TYPE/", "NORMAL", "29/30", "SCRATCH", "GROWL", ">EMBER", "LEER"))
    ctx.bv = BattleView(kind=1, hp=10, mx=20, species=25, my_sp=4, my_lvl=5, e_lvl=3, cur=">FIGHT")
    ctx.refresh()
    return ctx


def test_all_zero_pp_presses_b_for_struggle_on_the_first_step(tmp_path):
    ctx = _menu_ctx(tmp_path, {0xD014: 4})  # battle mon loaded (CHARMANDER), all four PP bytes 0
    d = BattleMoves().step(ctx)
    assert (d.button, d.rule) == ("B", "pp_out_struggle")
    assert ctx.all_pp_out == 1


def test_a_stale_battle_struct_leaves_every_move_usable(tmp_path):
    ctx = _menu_ctx(tmp_path, {})           # wBattleMonSpecies 0: no PP data -> do not B out for STRUGGLE
    d = BattleMoves().step(ctx)
    assert d.rule != "pp_out_struggle" and ctx.all_pp_out == 0


def test_cursor_on_an_empty_move_never_presses_a(tmp_path, monkeypatch):
    monkeypatch.setattr(bms, "move_scores", lambda emu, catching=False: {})
    # EMBER sits in slot 2 (0xD02F = 0 PP); the cursor starts on it and stays on it
    ctx = _menu_ctx(tmp_path, {0xD014: 4, 0xD02D: 35, 0xD02E: 40, 0xD02F: 0, 0xD030: 30})
    for _ in range(8):                      # well past the old 5-press take-what-is-under-the-cursor escape
        d = BattleMoves().step(ctx)
        assert (d.button, d.rule) == ("DOWN", "move_cursor")
        assert ctx.last_move_choice != "EMBER"
    assert ctx.move_nav == 8


def test_move_nav_resets_when_the_move_menu_leaves_the_screen(tmp_path):
    ctx = _menu_ctx(tmp_path, {0xD014: 4, 0xD02D: 35, 0xD02E: 40, 0xD02F: 0, 0xD030: 30})
    BattleMoves().step(ctx)
    assert ctx.move_nav == 1                     # one DOWN press, cursor still walking
    gone = make_ctx(tmp_path, memory={BATTLE: 1})  # the next frame: no box, no move menu on screen
    gone.move_nav = ctx.move_nav
    gone.bv = ctx.bv
    gone.refresh()
    d = BattleMoves().step(gone)
    assert d is not None and gone.move_nav == 0
