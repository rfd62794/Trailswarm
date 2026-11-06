"""battle_text_wait: do not press A at a battle message that is not waiting for it.

Most battle messages ("BULBASAUR used TACKLE!", "Enemy RATTATA used TACKLE!") scroll on their own while the move animation
plays; an A during that is a no-op that still costs a step. In the seed runs 40% of all steps were battle presses and the same
message was on screen for 3-4 presses in a row. The game is waiting for A when the down-arrow prompt (tile 0xEE) is up, or when the
page has stopped changing; wait (no press, no step) until one of those holds."""
from __future__ import annotations

from pokeagent.explorer.behaviours.box_settle import uncount
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import is_menu
from pokeagent.explorer.text_pace import PROMPT_COL, PROMPT_ROW, prompt_waiting

STILL_FRAMES = 30  # a page unchanged this long (more than a prompt-arrow blink) is waiting for A even without the arrow
MAX_WAIT = 90  # decisions: the fallback cap for callers that never tick ctx.frame


def _masked(tm: bytes) -> bytes:
    i = PROMPT_ROW * 20 + PROMPT_COL
    return tm[:i] + bytes([0x7F]) + tm[i + 1:]


class BattleTextWait(BehaviourBase):
    name = "battle_text_wait"

    def applies(self, ctx: ExplorerContext) -> bool:
        v = ctx.view
        live = v.battling and v.box and bool(v.lines) and not is_menu(v.tm)
        if not live:
            ctx.btw_waits = 0
        return live

    def step(self, ctx: ExplorerContext) -> Decision | None:
        tm = ctx.view.tm
        h = hash(_masked(tm))
        if h != ctx.btw_hash:
            ctx.btw_hash, ctx.btw_since = h, ctx.frame  # the page changed: the clock restarts
        if prompt_waiting(tm) or ctx.frame - ctx.btw_since >= STILL_FRAMES or ctx.btw_waits >= MAX_WAIT:
            ctx.btw_waits = 0
            return None  # the game is waiting (or we waited long enough): the battle behaviours press A as before
        ctx.btw_waits += 1
        uncount(ctx)
        return no_press("battle_text_wait", "a battle message is still scrolling on its own: waiting, not pressing A")
