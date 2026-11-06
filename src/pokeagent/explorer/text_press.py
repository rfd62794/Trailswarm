"""text_press: one A press through an open text box at the learned pace (the emulator side of ``text_pace``).

Waits for the prompt tile (or a screen that stopped changing), presses A with a short hold, settles the learned
number of frames, and tells the learner whether the press was dropped. Counts frames in ``ctx.text_frames``."""
from __future__ import annotations

from pokeagent.emulator import Button
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open, is_menu
from pokeagent.explorer.text_pace import HOLD_FRAMES, PROMPT_COL, PROMPT_ROW, PaceLearner, prompt_waiting, screen_kind

WAIT_STEP, WAIT_MAX, STABLE_FRAMES = 2, 120, 10  # poll every 2 frames; give up after 120; a still screen counts as ready


def _tm(emu) -> bytes:
    return emu.read_range(TILEMAP, TILEMAP_LEN)


def _mask(tm: bytes) -> bytes:
    """The screen without the blinking prompt arrow (its blink must not read as the page changing)."""
    i = PROMPT_ROW * 20 + PROMPT_COL
    return tm[:i] + b"" + tm[i + 1:]


def learner(ctx) -> PaceLearner:
    if getattr(ctx, "pace", None) is None:
        ctx.pace = PaceLearner(ctx.mem.data)
    return ctx.pace


def fast_a_press(ctx) -> dict:
    """Press A once on an open box. Returns {"kind", "dropped", "waited", "frames"} for the metrics."""
    emu, pl = ctx.emu, learner(ctx)
    tm = _tm(emu)
    kind = screen_kind(tm, bool(emu.read(0xD057)), is_menu(tm))
    waited, still = 0, 0
    while waited < WAIT_MAX and not prompt_waiting(tm) and kind == "box":  # text still printing: let it finish
        emu.tick(WAIT_STEP); waited += WAIT_STEP
        nxt = _tm(emu)
        still = still + WAIT_STEP if _mask(nxt) == _mask(tm) else 0
        tm = nxt
        if still >= STABLE_FRAMES:
            break  # the last page has no prompt: it is simply waiting
    prompt = prompt_waiting(tm)
    settle = pl.settle(kind)
    emu.press(Button.A, HOLD_FRAMES, settle)
    after, calm, after_wait = _tm(emu), 0, 0
    while calm < 2 * WAIT_STEP and after_wait < WAIT_MAX:  # a half-drawn screen (a menu opening, text starting) is not "after" yet
        emu.tick(WAIT_STEP); after_wait += WAIT_STEP
        nxt = _tm(emu)
        calm = calm + WAIT_STEP if _mask(nxt) == _mask(after) else 0
        after = nxt
    dropped = (prompt or kind in ("menu", "yesno")) and _mask(after) == _mask(tm)  # something was waiting for A, we pressed, nothing changed
    pl.record(kind, dropped)
    st = ctx.mem.data.setdefault("text_press_stats", {"presses": 0, "pages": 0, "dropped": 0, "frames": 0})
    st["presses"] += 1
    st["pages"] += 1 if prompt or not box_open(after) else 0  # a page is a press at the prompt, or the press that closes the box
    st["dropped"] += 1 if dropped else 0
    frames = waited + after_wait + HOLD_FRAMES + settle
    st["frames"] = st.get("frames", 0) + frames
    ctx.text_frames = getattr(ctx, "text_frames", 0) + frames
    return {"kind": kind, "dropped": dropped, "waited": waited, "frames": frames}
