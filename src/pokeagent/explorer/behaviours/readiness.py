"""readiness: the input-readiness wait (settle pause, then a learned way through animations and cutscenes)."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.mash_skill import WAIT, MashSkill, gap_frames, signature


class SettleWait(BehaviourBase):
    """After a map change the demo pauses a few frames so the watcher sees the arrival."""

    name = "settle"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.settle > 0

    def step(self, ctx: ExplorerContext) -> Decision | None:
        ctx.settle -= ctx.opts.frames_per_step
        return no_press("settle", "pause after a map change")


WALKER_RADIUS = 3  # a wandering NPC this close keeps the screen changing without anything being "busy"
_WALKING = 0xFE    # wSpriteStateData2 +6 movement byte: random walk (0xFF is STAY)


def walker_near(ctx: ExplorerContext) -> bool:
    """A random-walking NPC sprite within WALKER_RADIUS tiles of the player (sprite tables, slots 1-15)."""
    emu, px, py = ctx.emu, ctx.view.x, ctx.view.y
    for i in range(1, 16):
        if emu.read(0xC100 + 16 * i) and emu.read(0xC206 + 16 * i) == _WALKING:
            nx, ny = emu.read(0xC205 + 16 * i) - 4, emu.read(0xC204 + 16 * i) - 4
            if max(abs(nx - px), abs(ny - py)) <= WALKER_RADIUS:
                return True
    return False


BUSY_STABLE_FRAMES = 4  # the overworld screen must be unchanged this many frames to count as settled


class Readiness(BehaviourBase):
    """Do not press blindly while the screen is still changing on its own (walking animation, fade, forced walk,
    cutscene) or while the game says it is ignoring the joypad (wJoyIgnore, unverified). How to get through it is a
    LEARNED skill per situation (mash_skill): WAIT (one nudge A per BOUND_FRAMES) or A every N frames, graded by the
    frames each busy episode takes to resolve."""

    name = "readiness"

    def applies(self, ctx: ExplorerContext) -> bool:
        return self._busy(ctx) or ctx.mash > 0

    def _busy(self, ctx: ExplorerContext) -> bool:
        # Only the OVERWORLD needs the stillness check (forced walks, fades, Oak dragging you to the lab).
        # Boxes and menus are paced by the game itself: a waiting text box goes to advance_dialog, and a
        # blinking cursor would otherwise look like "still changing" forever (that stalled the 23:20 run).
        if ctx.view.box:
            return False
        if ctx.emu.read(0xCD6B):
            return True  # the game is ignoring the joypad
        # A walker nearby makes the picture change forever: that is not a cutscene, and A "in case text is waiting" would
        # talk to it (164 times at Mt Moon 1F (16,23), 2026-11-05). Only a still-changing screen with nobody walking is busy.
        return ctx.stable_frames < BUSY_STABLE_FRAMES and not walker_near(ctx)

    @staticmethod
    def _skill(ctx: ExplorerContext) -> MashSkill:
        if ctx.skill is None:
            ctx.skill = MashSkill(ctx.mem.data)
        return ctx.skill

    def _begin(self, ctx: ExplorerContext, joy_ignore: int) -> None:
        first = next((ln for ln in ctx.view.lines if ln.strip()), "")
        ctx.busy_sig = signature(ctx.view.m, ctx.view.battling, bool(joy_ignore), first)
        ctx.busy_strategy = self._skill(ctx).choose(ctx.busy_sig)
        ctx.busy_start = ctx.frame
        ctx.busy_presses = 0
        # A strategies press at once; WAIT lets BOUND_FRAMES pass before its single nudge
        ctx.busy_last_press = ctx.frame if ctx.busy_strategy == WAIT else ctx.frame - gap_frames(ctx.busy_strategy)
        ctx.log(f"[busy {ctx.busy_sig}: {'joypad ignored (0x%02X)' % joy_ignore if joy_ignore else 'screen moving'}"
                f" - strategy {ctx.busy_strategy}]", "res")

    def step(self, ctx: ExplorerContext) -> Decision | None:
        joy_ignore = ctx.emu.read(0xCD6B)
        skill = self._skill(ctx)
        if self._busy(ctx):
            if ctx.mash == 0:
                self._begin(ctx, joy_ignore)
            ctx.mash += 1  # busy decisions in this stretch
            tag = f"{ctx.busy_strategy} (learned {skill.mean_frames(ctx.busy_sig, ctx.busy_strategy)}f)"
            if ctx.frame - ctx.busy_last_press < gap_frames(ctx.busy_strategy):
                return no_press(f"busy_wait {tag}", "screen moving / joypad ignored: waiting instead of pressing")
            ctx.busy_last_press = ctx.frame
            ctx.busy_presses += 1
            if ctx.declined_balls and ctx.goals().get("first_pokemon"):
                ctx.declined_balls.clear()  # starter chosen: the lab balls no longer matter
            if (ctx.view.m, ctx.view.x, ctx.view.y, ctx.facing) in ctx.declined_balls:
                # The box we declined just closed and the screen is still settling: A would re-open the same ball's
                # offer (131 times in Oak's lab, 2026-11-05). B is as good at skipping text and touches nothing.
                return Decision("B", f"mash {tag}", "busy at a declined starter ball: B so A does not re-open it")
            return Decision("A", f"mash {tag}", "busy: A in case text is waiting")
        frames = ctx.frame - ctx.busy_start
        skill.record(ctx.busy_sig, ctx.busy_strategy, frames, ctx.busy_presses)
        ctx.log(f"[busy over: {ctx.busy_strategy} took {frames}f, {ctx.busy_presses} presses]", "res")
        ctx.mash = 0
        ctx.busy_presses = 0
        return None

    def done(self, ctx: ExplorerContext) -> bool:
        return ctx.mash == 0
