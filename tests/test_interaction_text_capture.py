"""Interaction text capture: an interaction note holds only the dialogue of that interaction.

A text box is not always a talk: a trainer's speech runs into the battle intro, a step can leave the
START menu open. On the 2026-11-08 maps.json audit most notes held battle or menu rows; these tests
pin down that only dialogue reaches entry["text"]/["pages"], and that interaction_spots honours
typed entries.

make_ctx/put_box are copied from tests/test_explorer_behaviours.py (per the directive, not imported);
ScreenFake adds the mid-press screen swap a real emulator does while the game answers the button.
"""
from __future__ import annotations

import io

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.perceive import TILEMAP_LEN
from pokeagent.explorer.press import Presser
from pokeagent.explorer.world import interaction_spots

TM = 0xC3A0
MAP, PX, PY, BATTLE = 0xD35E, 0xD362, 0xD361, 0xD057


class ScreenFake(FakeEmulator):
    """A FakeEmulator that swaps in the next scripted screen while the press settles, like the real game does."""

    def __init__(self, memory=None):
        super().__init__(memory)
        self.after_press = None  # one-shot callable applied inside the next press()

    def press(self, button, hold_frames=8, settle_frames=16):
        super().press(button, hold_frames, settle_frames)
        if self.after_press is not None:
            apply_screen, self.after_press = self.after_press, None
            apply_screen()


def make_ctx(tmp_path, memory=None, **fields) -> ExplorerContext:
    emu = ScreenFake({MAP: 0x28, PX: 5, PY: 6, **(memory or {})})
    mem = MapMemory(tmp_path / "maps.json")
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10, **fields)
    ctx.trans = io.StringIO()  # the Presser writes one transitions line per press
    return ctx


def put_box(ctx, menu: bool = False, text_rows=("HELLO THERE",)) -> None:
    """Draw a frame in the tile map: 0x79 0x7A top edge, then rows between 0x7C edges (CHARMAP letters at 0x80+)."""
    emu = ctx.emu
    emu.set(TM + 20 * 10, 0x79)
    emu.set(TM + 20 * 10 + 1, 0x7A)
    for r, text in enumerate(text_rows, start=11):
        emu.set(TM + 20 * r, 0x7C)
        emu.set(TM + 20 * r + 19, 0x7C)
        for i, ch in enumerate(text):
            emu.set(TM + 20 * r + 1 + i, 0x80 + (ord(ch) - ord("A")) if ch.isalpha() else 0x7F)
    if menu:
        emu.set(TM + 20 * 11 + 1, 0xED)


def clear_screen(ctx) -> None:
    for i in range(TILEMAP_LEN):
        ctx.emu.set(TM + i, 0)


def dialogue(ctx, *rows) -> None:
    clear_screen(ctx)
    put_box(ctx, text_rows=rows)


def menu_box(ctx, *rows) -> None:
    clear_screen(ctx)
    put_box(ctx, menu=True, text_rows=rows)


def battle_box(ctx, *rows) -> None:
    ctx.emu.set(BATTLE, 1)
    clear_screen(ctx)
    put_box(ctx, text_rows=rows)


def entries(ctx, map_id=0x28) -> dict:
    return ctx.mem.m(map_id).get("interactions", {})


def test_battle_after_a_talk_does_not_add_to_the_note(tmp_path):
    """A talk that runs into the battle intro keeps its dialogue; the battle line never reaches the note.

    Reproduced on the unpatched code: the mid-battle press overwrote entry["text"] with
    "HELLO RED DEAR / WILD PIDGEY | APPEARED" (press_interact's box_before block, which extends the
    note from ctx.dialog), and the box-closing press copied the battle line into pages
    (interaction_record.close_interaction -> add_pages over ctx.dialog). The contact half failed too:
    the LEFT press created an entry "5,6,LEFT" whose text was the battle intro.
    """
    ctx = make_ctx(tmp_path)
    ctx.facing = "UP"
    presser = Presser(ctx)
    ctx.emu.after_press = lambda: dialogue(ctx, "HELLO RED DEAR")
    presser.press("A", "agent", "talk to the spot")  # a one-page talk opens
    ctx.emu.after_press = lambda: battle_box(ctx, "WILD PIDGEY", "APPEARED")
    presser.press("A", "agent", "advance the text")  # the talk ran into the battle intro
    ctx.emu.after_press = lambda: clear_screen(ctx)
    presser.press("A", "agent", "the box finally closes")
    entry = entries(ctx)["5,6,UP"]
    assert ctx.inter is None  # the interaction is closed
    assert "PIDGEY" not in entry["text"] and "APPEARED" not in entry["text"]
    for page in entry.get("pages", []):
        assert "PIDGEY" not in page and "APPEARED" not in page

    # the other capture path: a wild-battle intro left open by a step press (the contact branch)
    ctx.emu.set(BATTLE, 0)
    clear_screen(ctx)
    ctx.emu.after_press = lambda: battle_box(ctx, "WILD ZUBAT", "APPEARED")
    presser.press("LEFT", "agent", "a step into the grass")
    assert "5,6,LEFT" not in entries(ctx) and ctx.inter is None


def test_a_menu_does_not_add_to_the_note(tmp_path):
    """A menu drawn over an open talk adds nothing to text or pages; a menu left open by a movement
    press creates no interaction entry at all.

    The first half is a guard: it already passed on the unpatched code (press.py keeps menu screens
    out of ctx.dialog, so text and pages stayed clean). The second half failed there: the contact
    branch stored the menu rows as the tile's interaction text.
    """
    ctx = make_ctx(tmp_path)
    ctx.facing = "UP"
    presser = Presser(ctx)
    ctx.emu.after_press = lambda: dialogue(ctx, "HELLO RED DEAR")
    presser.press("A", "agent", "talk")
    ctx.emu.after_press = lambda: menu_box(ctx, "POKEDEX", "POKEMON")
    presser.press("A", "agent", "the START menu covers the box")
    ctx.emu.after_press = lambda: clear_screen(ctx)
    presser.press("A", "agent", "the box closes")
    entry = entries(ctx)["5,6,UP"]
    assert "POKEDEX" not in entry["text"] and "POKEMON" not in entry["text"]
    for page in entry.get("pages", []):
        assert "POKEDEX" not in page and "POKEMON" not in page

    ctx.emu.after_press = lambda: menu_box(ctx, "POKEDEX", "ITEM")
    presser.press("RIGHT", "agent", "the START menu opened")
    assert "5,6,RIGHT" not in entries(ctx) and ctx.inter is None


def test_ordinary_multi_page_dialogue_still_records(tmp_path):
    """Three plain dialogue pages, then the box closes: all three pages in order, text the fullest
    dialogue. Passed before the fix and must still pass."""
    ctx = make_ctx(tmp_path)
    ctx.facing = "UP"
    presser = Presser(ctx)
    pages = ("FIRST PAGE OF TEXT", "SECOND PAGE HERE", "THIRD PAGE ENDS IT")  # <=18 chars a row, or the edge is hit
    ctx.emu.after_press = lambda: dialogue(ctx, pages[0])
    presser.press("A", "agent", "talk")
    for page in pages[1:]:
        ctx.emu.after_press = lambda p=page: dialogue(ctx, p)
        presser.press("A", "agent", "next page")
    ctx.emu.after_press = lambda: clear_screen(ctx)
    presser.press("A", "agent", "the box closes")
    entry = entries(ctx)["5,6,UP"]
    assert entry["pages"] == list(pages)
    assert entry["text"] == " / ".join(pages)
    assert ctx.inter is None


def test_interaction_spots_finds_a_typed_pc_entry_with_no_pc_text():
    """A typed entry matches the needle even with no text mention; type matches come before text-only
    matches, and text matching still works on its own."""
    maps = {"38": {"interactions": {"0,2,UP": {"type": "pc", "count": 5, "text": "hello there"},
                                   "0,2,DOWN": {"count": 2, "text": "turned on | the PC."}}}}
    spots = interaction_spots(maps, "PC")
    assert spots[0] == (38, 0, 2, "UP")
    assert spots[1] == (38, 0, 2, "DOWN")
    no_typed = {"38": {"interactions": {"0,2,DOWN": {"count": 2, "text": "turned on | the PC."}}}}
    assert interaction_spots(no_typed, "PC") == [(38, 0, 2, "DOWN")]
