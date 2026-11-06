"""The real rig: presses go through the explorer's Presser as source "claude" and are logged as ``driver: "claude"``.

``ClaudeDriver.press`` is the one place Claude's buttons enter the game: it presses, refreshes the lease, and writes a
decisions.jsonl record marked ``driver: "claude"`` (so the agent's own record stays distinguishable). ``EmuRig`` is what a
macro runs against: screen reads, presses, ticks, and the Goto behaviour for goto().
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.goto import Goto
from pokeagent.explorer.decisions import classify_outcome, goal_stage, make_record
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open
from pokeagent.intervene.screen import ScreenRead, read_screen


class ClaudeDriver:
    def __init__(self, ctx, presser, decision_log, hold) -> None:
        self.ctx, self.presser, self.log, self.hold = ctx, presser, decision_log, hold

    def press(self, button: str, why: str, rule: str = "remote_press") -> None:
        ctx = self.ctx
        before = ctx.pos()
        box = box_open(ctx.emu.read_range(TILEMAP, TILEMAP_LEN))
        battle = ctx.emu.read(0xD057) != 0
        self.presser.press(button, "claude", why)
        self.hold.touch()
        if self.log is None:
            return
        after = ctx.pos()
        box_after = box_open(ctx.emu.read_range(TILEMAP, TILEMAP_LEN))
        rec = make_record(ctx.step, "claude", rule, button, before, goal_stage(ctx.goals()), box, battle,
                          classify_outcome(before, after, button, box_after, False))
        rec["driver"], rec["why"] = "claude", why
        self.log.write(rec)


class EmuRig:
    def __init__(self, ctx, driver: ClaudeDriver, macro: str) -> None:
        self.ctx, self.driver, self.macro = ctx, driver, macro
        self.emu = ctx.emu
        self._goto = Goto()

    def read(self) -> ScreenRead:
        return read_screen(self.emu)

    def press(self, button: str, why: str) -> None:
        self.driver.press(button, why, self.macro)

    def tick(self, frames: int) -> None:
        self.emu.tick(frames)

    def goto_decision(self, target: tuple) -> tuple[str, str]:
        """Ask the Goto behaviour for the next button toward `target` (it clears ctx.goto on arrival or no route)."""
        ctx = self.ctx
        ctx.goto = list(target)
        ctx.refresh()
        d = self._goto.step(ctx)
        if d is None:
            arrived = ctx.pos() == tuple(target)
            ctx.goto = None
            return ("arrived", "") if arrived else ("stop", "no_route")
        ctx.goto = None  # the macro owns the walk; nothing else may keep steering toward it
        return ("press", d.button) if d.button else ("wait", "")
