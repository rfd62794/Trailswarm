"""box_settle: never press A at an empty text box, nor right after one closes (a box that is opening or closing has a border and no words).

That A is what re-triggered signs and NPCs: the last page closes, the border lingers a few frames, the agent presses A
again and the same text opens (46 re-talks of info/sign spots in a 3,000-step run). Wait instead, up to MAX_WAIT
consecutive decisions so a genuinely wordless frame can never stall the agent."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.ram_symbols import IS_IN_BATTLE

def uncount(ctx: ExplorerContext) -> None:
    """A wait is not a press: take the decision LoopGuard just added to its position history back out, so a few waits
    never add up to "60 presses on <=6 tiles" (that fired at step 18 and cost a 25-step shake)."""
    if ctx.pos_hist and ctx.emu.read(IS_IN_BATTLE) == 0:  # LoopGuard only appends outside battle: pop only what it added
        ctx.pos_hist.pop()


MAX_WAIT = 40  # decisions (a fallback cap for callers that never tick ctx.frame)
EMPTY_FRAMES = 45  # a box border can linger this long while the screen redraws after the last page


class BoxSettle(BehaviourBase):
    name = "box_settle"

    def applies(self, ctx: ExplorerContext) -> bool:
        empty = ctx.view.box and not ctx.view.lines and not ctx.view.battling
        if not empty:
            ctx.box_empty_waits, ctx.box_empty_since = 0, -1
        elif ctx.box_empty_since < 0:
            ctx.box_empty_since = ctx.frame
        return empty and ctx.box_empty_waits < MAX_WAIT and ctx.frame - ctx.box_empty_since < EMPTY_FRAMES

    def step(self, ctx: ExplorerContext) -> Decision | None:
        ctx.box_empty_waits += 1
        uncount(ctx)
        return no_press("box_settle", "the text box is empty (opening or closing): waiting, not pressing A")


POST_TALK_FRAMES = 24  # the closing animation after a text box ends; more than the readiness stillness window


class PostTalkSettle(BehaviourBase):
    """After a text box closes the screen is still redrawing; Readiness reads that as "busy" and mashes A, which
    re-opens the very sign or NPC just read. Wait out the redraw (bounded by POST_TALK_FRAMES) instead."""

    name = "post_talk_settle"

    def applies(self, ctx: ExplorerContext) -> bool:
        return (not ctx.view.box and not ctx.view.battling and ctx.talk_closed_frame >= 0
                and ctx.frame - ctx.talk_closed_frame < POST_TALK_FRAMES and ctx.post_talk_waits < MAX_WAIT)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        uncount(ctx)
        ctx.post_talk_waits += 1  # bounded even if nothing ticks ctx.frame (a caller without the demo loop)
        return no_press("post_talk_settle", "a text box just closed: letting the screen redraw before pressing anything")
