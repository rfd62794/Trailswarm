"""readiness: the input-readiness wait (settle pause, then mash A through cutscenes and forced walks)."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext


class SettleWait(BehaviourBase):
    """After a map change the demo pauses a few frames so the watcher sees the arrival."""

    name = "settle"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.settle > 0

    def step(self, ctx: ExplorerContext) -> Decision | None:
        ctx.settle -= ctx.opts.frames_per_step
        return no_press("settle", "pause after a map change")


class Readiness(BehaviourBase):
    """Do not press while the screen is still changing on its own (cutscene, forced walk, fade, battle
    animation) or while the game says it is ignoring the joypad (wJoyIgnore, unverified): mash A instead."""

    name = "readiness"

    def applies(self, ctx: ExplorerContext) -> bool:
        return self._busy(ctx) or ctx.mash > 0

    def _busy(self, ctx: ExplorerContext) -> bool:
        # Only the OVERWORLD needs the stillness check (forced walks, fades, Oak dragging you to the lab).
        # Boxes and menus are paced by the game itself: pressing while text prints is harmless, and a
        # blinking cursor would otherwise look like "still changing" forever (that stalled the 23:20 run).
        return bool(not ctx.view.box and (ctx.stable_frames < 4 or ctx.emu.read(0xCD6B)))

    def step(self, ctx: ExplorerContext) -> Decision | None:
        joy_ignore = ctx.emu.read(0xCD6B)
        if self._busy(ctx):
            # Cutscene / forced walk / fade (Robert, 2026-11-03): do not wait for it - MASH A. A is harmless while the
            # joypad is ignored and it skips any text the moment it appears. The press is logged like any other.
            ctx.mash = ctx.mash + 1
            if ctx.mash == 1:
                ctx.log(f"[cutscene: {'joypad ignored (0x%02X)' % joy_ignore if joy_ignore else 'screen moving on its own'} - mashing A]", "res")
            if ctx.declined_balls and ctx.goals().get("first_pokemon"):
                ctx.declined_balls.clear()  # starter chosen: the lab balls no longer matter
            if (ctx.view.m, ctx.view.x, ctx.view.y, ctx.facing) in ctx.declined_balls:
                # The box we declined just closed and the screen is still settling: A would re-open the same ball's
                # offer (131 times in Oak's lab, 2026-11-05). B is as good at skipping text and touches nothing.
                return Decision("B", "mash", "settling at a declined starter ball: mashing B so A does not re-open it")
            return Decision("A", "mash", "cutscene/forced walk: mashing A to get through it")
        ctx.log(f"[cutscene over after {ctx.mash} A presses]", "res")
        ctx.mash = 0
        return None

    def done(self, ctx: ExplorerContext) -> bool:
        return ctx.mash == 0
