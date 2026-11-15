"""PP-zero move guard: usable_moves / cursor_step purity, STRUGGLE on the first all-zero read,
and no A press on an empty move however long the cursor walk runs. Synthetic only: FakeEmulator, no ROM."""
from __future__ import annotations

import pytest

from pokeagent.explorer.behaviours import battle_moves as bms
from pokeagent.explorer.behaviours.battle import BattleView
from pokeagent.explorer.behaviours.battle_moves import BattleMoves
from pokeagent.explorer.behaviours.battle_pp import cursor_step, off_disabled_step, usable_moves
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
        assert (d.button, d.rule) == ("UP", "move_cursor")  # target SCRATCH is above EMBER: walk up
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


# --- directional walk + disabled-screen loop (Route 3 Pidgey stall, 2026-11-15) ---
PIDGEY = ["GUST", "SAND-ATTACK", "QUICK ATTACK"]


def _redraw(ctx, rows):
    """Replace the box rows wholesale (pad to full width and blank the leftover rows of the previous frame)."""
    padded = [r.ljust(18) for r in rows] + [" " * 18] * (8 - len(rows))
    put_box(ctx, padded)
    ctx.refresh()


def test_cursor_step_walks_up_when_the_target_is_above():
    usable = ["GUST", "SAND-ATTACK"]
    assert cursor_step("SAND-ATTACK", "GUST", usable, 1, PIDGEY) == ("up", None)
    assert cursor_step("GUST", "SAND-ATTACK", usable, 1, PIDGEY) == ("down", None)


def test_disabled_last_slot_steps_up_and_keeps_counting_nav(tmp_path, monkeypatch):
    monkeypatch.setattr(bms, "move_scores", lambda emu, catching=False: {"GUST": (10, ""), "SAND-ATTACK": (0, ""), "QUICK ATTACK": (5, "")})
    # QUICK ATTACK (slot 2) has 0 PP; GUST is the target; the cursor starts on SAND-ATTACK
    ctx = _menu_ctx(tmp_path, {0xD014: 4, 0xD02D: 35, 0xD02E: 40, 0xD02F: 0})
    ctx.no_pp.add("QUICK ATTACK")
    _redraw(ctx, ("FIGHT", "TYPE/", "NORMAL", "29/30", "GUST", ">SAND-ATTACK", "QUICK ATTACK"))
    d = BattleMoves().step(ctx)
    assert (d.button, d.rule) == ("UP", "move_cursor")

    # DOWN landed on the disabled last slot: DOWN would be a no-op there, so the disabled screen steps back UP
    ctx.move_dir = "DOWN"
    _redraw(ctx, ("disabled!", "GUST", "SAND-ATTACK", ">QUICK ATTACK"))
    nav = ctx.move_nav
    d = BattleMoves().step(ctx)
    assert (d.button, d.rule) == ("UP", "disabled_move")  # last slot: DOWN would be a no-op, so back toward GUST
    assert ctx.move_nav == nav + 1  # not reset: the nav > 5 escape can still fire


def test_menu_disabled_alternation_ends_in_a_press_on_a_usable_move(tmp_path, monkeypatch):
    monkeypatch.setattr(bms, "move_scores", lambda emu, catching=False: {"GUST": (10, ""), "SAND-ATTACK": (0, ""), "QUICK ATTACK": (5, "")})
    ctx = _menu_ctx(tmp_path, {0xD014: 4, 0xD02D: 35, 0xD02E: 40, 0xD02F: 0})
    cursor = 1  # SAND-ATTACK
    pressed = None
    for _ in range(12):
        if PIDGEY[cursor] == "QUICK ATTACK":
            _redraw(ctx, ("disabled!", "GUST", "SAND-ATTACK", ">QUICK ATTACK"))
        else:
            rows = [("" if i != cursor else ">") + m for i, m in enumerate(PIDGEY)]
            _redraw(ctx, ("FIGHT", "TYPE/", "NORMAL", "29/30", *rows))
        d = BattleMoves().step(ctx)
        if d.button == "A":
            pressed = PIDGEY[cursor]
            break
        cursor = max(0, min(2, cursor + (1 if d.button == "DOWN" else -1)))
    assert pressed in ("GUST", "SAND-ATTACK")


# --- no-wrap cursor model: every menu / disabled-screen alternation must end in A on a usable move ---
ALL = ["GUST", "SAND-ATTACK", "QUICK ATTACK", "TACKLE"]


def _play(tmp_path, monkeypatch, n, disabled, zero, start, target, bound=30):
    """Menu of n moves; `disabled` moves show the disabled screen while the cursor sits on them (their PP byte
    stays > 0), `zero` moves have a 0 PP byte. Cursor does not wrap. Plays until A or B is pressed (the target
    only steers the walk; it need not be reached) and returns ("A", slot), ("B", slot) or (None, slot) at the bound."""
    names = ALL[:n]
    monkeypatch.setattr(bms, "move_scores", lambda emu, catching=False: {m: (10 if i == target else 1, "") for i, m in enumerate(names)})
    mem = {0xD014: 4}
    for i in range(n):
        mem[0xD02D + i] = 0 if i in zero else 20
    ctx = _menu_ctx(tmp_path, mem)
    cursor = start
    for _ in range(bound):
        if cursor in disabled:
            _redraw(ctx, ("disabled!", *[("" if i != cursor else ">") + m for i, m in enumerate(names)]))
        else:
            _redraw(ctx, ("TYPE/", "29/30", *[("" if i != cursor else ">") + m for i, m in enumerate(names)]))
        d = BattleMoves().step(ctx)
        if d.button in ("A", "B"):
            return d.button, cursor
        if d.button in ("UP", "DOWN"):
            cursor = max(0, min(n - 1, cursor + (1 if d.button == "DOWN" else -1)))
    return None, cursor


def test_disabled_at_slot_zero_with_the_cursor_on_it_moves_down(tmp_path, monkeypatch):  # (a)
    # menu [QUICK(disabled), GUST, SAND], cursor remembered on slot 0, disabled screen at once, nothing walked yet
    assert _play(tmp_path, monkeypatch, 3, disabled={0}, zero=set(), start=0, target=1)[1] in (1, 2)


def test_disabled_last_slot_with_pp_left_is_never_pressed_again(tmp_path, monkeypatch):  # (b)
    # menu [GUST, SAND, QUICK], QUICK disabled but its PP byte > 0, cursor on SAND, target QUICK
    assert _play(tmp_path, monkeypatch, 3, disabled={2}, zero=set(), start=1, target=2)[1] in (0, 1)


def test_menu_disabled_alternation_always_ends_in_a_on_a_usable_move_or_b(tmp_path, monkeypatch):
    from itertools import product
    for n in range(1, 5):
        for mask in product((0, 1, 2), repeat=n):  # 0 fine, 1 disabled (PP > 0), 2 zero PP
            disabled = {i for i, m in enumerate(mask) if m == 1}
            zero = {i for i, m in enumerate(mask) if m == 2}
            any_usable = len(disabled) + len(zero) < n
            for start, target in product(range(n), repeat=2):
                btn, at = _play(tmp_path, monkeypatch, n, disabled, zero, start, target)
                ctxt = (n, mask, start, target, btn, at)
                if btn == "A":
                    assert at not in disabled and at not in zero, ctxt
                else:
                    assert btn == "B" and not any_usable, ctxt  # B only when nothing is usable


def test_single_disabled_move_backs_out_with_b(tmp_path, monkeypatch):
    assert _play(tmp_path, monkeypatch, 1, {0}, set(), 0, 0)[0] == "B"


def test_two_disabled_moves_back_out_with_b(tmp_path, monkeypatch):
    for start in (0, 1):
        assert _play(tmp_path, monkeypatch, 2, {0, 1}, set(), start, 0)[0] == "B"


def _disabled_ctx(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(bms, "move_scores", lambda emu, catching=False: {})
    ctx = _menu_ctx(tmp_path, {0xD014: 4, 0xD02D: 20, 0xD02E: 20, 0xD02F: 20})
    _redraw(ctx, rows)
    return ctx


def test_disabled_screen_without_a_cursor_line_never_presses_a(tmp_path, monkeypatch):
    ctx = _disabled_ctx(tmp_path, monkeypatch, ("disabled!", "GUST", "SAND-ATTACK", "QUICK ATTACK"))
    d = BattleMoves().step(ctx)
    assert d.button in ("UP", "DOWN", "B") and d.rule != "fight"
    ctx = _disabled_ctx(tmp_path, monkeypatch, ("disabled!", "GUST"))
    assert BattleMoves().step(ctx).button == "B"


def test_disabled_screen_with_the_move_list_above_the_message(tmp_path, monkeypatch):
    ctx = _disabled_ctx(tmp_path, monkeypatch, ("GUST", "SAND-ATTACK", ">QUICK ATTACK", "disabled!"))
    d = BattleMoves().step(ctx)
    assert (d.button, d.rule) == ("UP", "disabled_move") and "QUICK ATTACK" in ctx.no_pp


def test_off_disabled_step_tie_break_follows_the_walk_direction():
    rows = ["A", "B", "C"]
    assert off_disabled_step(rows, "B", ["A", "C"], "DOWN") == "DOWN"
    assert off_disabled_step(rows, "B", ["A", "C"], "UP") == "UP"
    assert off_disabled_step(rows, "B", ["A", "C"], "") == "UP"
    assert off_disabled_step(rows, "B", [], "UP") == "B"
