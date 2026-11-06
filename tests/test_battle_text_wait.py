"""battle_text_wait: wait while a battle message scrolls on its own, press when the prompt shows or the page is still."""
from types import SimpleNamespace as NS

from pokeagent.explorer.behaviours.battle_text_wait import STILL_FRAMES, BattleTextWait


def ctx(tm=b"\x00" * 360, frame=0, **kw):
    v = NS(battling=True, box=True, lines=["BULBASAUR used", "TACKLE!"], tm=tm)
    for k, val in kw.items():
        setattr(v, k, val)
    return NS(view=v, frame=frame, btw_hash=0, btw_since=0, btw_waits=0, pos_hist=[], emu=NS(read=lambda a: 2))


def prompt_tm():
    t = bytearray(360)
    t[16 * 20 + 18] = 0xEE
    return bytes(t)


def test_waits_on_a_fresh_page_then_presses_once_it_is_still():
    c, b = ctx(), BattleTextWait()
    assert b.applies(c) and b.step(c).button == ""            # just changed: wait
    c.frame = STILL_FRAMES - 1
    assert b.step(c).button == ""                              # still scrolling
    c.frame = STILL_FRAMES
    assert b.step(c) is None                                   # unchanged for 30 frames: pass to the A-pressing behaviours


def test_presses_at_once_when_the_prompt_arrow_is_up():
    c, b = ctx(tm=prompt_tm()), BattleTextWait()
    assert b.step(c) is None


def test_a_changing_page_restarts_the_clock():
    c, b = ctx(), BattleTextWait()
    b.step(c)
    c.frame = 25
    c.view.tm = bytes([1]) + b"\x00" * 359
    assert b.step(c).button == ""
    c.frame = 50
    assert b.step(c).button == ""    # only 25 frames since the change


def test_not_for_menus_or_the_overworld():
    b = BattleTextWait()
    assert not b.applies(ctx(tm=bytes([0xED]) + b"\x00" * 359))
    assert not b.applies(ctx(battling=False))
    assert not b.applies(ctx(box=False))


def test_bounded_even_if_the_frame_never_ticks():
    c, b = ctx(), BattleTextWait()
    for _ in range(200):
        r = b.step(c)
        if r is None:
            return
    raise AssertionError("never released")
