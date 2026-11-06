"""guards: the existing loop guards, moved as they were (the stuck-watchdog directive replaces them later).

LoopGuard runs first every step (shake / dialog-cycle / endless-A); StallGuard runs after the replay rules
(same tile and goals for 15 agent steps -> escalate).
"""
from __future__ import annotations

import random

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.demos import grade_replay
from pokeagent.explorer.perceive import DIRS, TILEMAP, TILEMAP_LEN, box_open


DIR_FAIL_BACKOUT = 6  # direction presses in a row that moved nothing (no box, no fight) before B backs out of the screen


class LoopGuard(BehaviourBase):
    name = "guards"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True  # its position history and A-streak counters must see every step

    def step(self, ctx: ExplorerContext) -> Decision | None:
        pw = ctx.pos()
        hist = ctx.pos_hist
        if ctx.emu.read(0xD057) == 0:  # battle presses never move us: counting them made every fight look like a stuck loop
            hist.append(pw); del hist[:-150]
        gnow = tuple(sorted(ctx.goal_steps))
        if ctx.shake_goals_150 != gnow:  # a goal landed: restart the 150-press window (it went dead after goal 1)
            ctx.shake_goals_150 = gnow; hist.clear(); hist.append(pw)
        # An unrecognised full-screen page (Pokedex entry opened by a stall escalation's START + menu exploration, 2026-11-05)
        # swallows every direction press while no box or battle is detected: back out with B instead of mashing A / walking.
        if ctx.last_press in DIRS and ctx.dir_fail_pos == pw and ctx.emu.read(0xD057) == 0 and not ctx.view.box:
            ctx.dir_fail += 1
        else:
            ctx.dir_fail = 0
        ctx.dir_fail_pos = pw
        if ctx.dir_fail >= DIR_FAIL_BACKOUT:
            ctx.shake = 0
            if ctx.dir_fail % DIR_FAIL_BACKOUT == 0:
                return Decision("B", "unknown_screen_back_out", f"{ctx.dir_fail} direction presses moved nothing: B in case a page is open")
        if ctx.shake > 0:
            tm_s = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
            ctx.shake -= 1
            if box_open(tm_s):
                return Decision("B", "shake_close_box", f"shake: closing a box ({ctx.shake} left)")
            if ctx.emu.read(0xD057) == 0:
                away = random.choice(list(DIRS))
                return Decision(away, "shake_walk", f"SHAKE: breaking a loop with a random walk {away} ({ctx.shake} left)")
        elif len(hist) >= 150 and len(set(hist[-150:])) <= 2 and ctx.emu.read(0xD057) == 0                 and tuple(sorted(ctx.goal_steps)) == ctx.shake_goals_150:
            # 150 presses on <=2 tiles with no goal progress, EVEN with boxes open: a dialog/answer cycle (A..., DOWN, A,
            # repeat) that never reaches 40 A in a row (Bulbasaur run re-asking the Charmander ball for 1700 steps).
            ctx.shake = 25; ctx.shakes = ctx.shakes + 1; hist.clear()
            ctx.log(f"[dialog cycle detected: 150 presses on <=2 tiles - shaking #{ctx.shakes}]", "res")
        elif len(hist) >= 60 and len(set(hist[-60:])) <= 6 and not box_open(ctx.emu.read_range(TILEMAP, TILEMAP_LEN))                 and ctx.emu.read(0xD057) == 0 and not ctx.explore_burst:
            ctx.shake = 25; ctx.shakes = ctx.shakes + 1; hist.clear()
            ctx.log(f"[loop detected: 60 presses on {len(set(hist)) or '<=6'} tiles - shaking #{ctx.shakes}]", "res")
        # Endless-A guard (runs BEFORE any box handling): 40 presses in a row that are all A while the position has
        # not changed = a sign/looping dialog. Close the box with B, then walk away.
        pos0 = ctx.pos()
        if ctx.a_pos != pos0 or ctx.last_press != "A":
            ctx.a_streak = 0
        ctx.a_pos = pos0
        if ctx.last_press == "A":
            ctx.a_streak = ctx.a_streak + 1
        if ctx.a_streak >= 40:
            tm_g = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
            if box_open(tm_g):
                return Decision("B", "a40_close_box", "40 A presses at the same tile: closing the box with B")
            ctx.a_streak = 0; ctx.stalls = ctx.stalls + 1; ctx.shake = 25
            away = random.choice([d for d in DIRS if d != ctx.facing])
            return Decision(away, "a40_walk_away", f"40 A presses at ({pos0[1]},{pos0[2]}): walking away {away}, then a shake")
        return None

    def failed(self, ctx: ExplorerContext) -> bool:
        return ctx.shake > 0  # a loop was detected and the random-walk recovery is running

    def done(self, ctx: ExplorerContext) -> bool:
        return ctx.shake == 0


class StallGuard(BehaviourBase):
    name = "stall_guard"

    def applies(self, ctx: ExplorerContext) -> bool:
        return True  # the stall counter advances on every step that reaches it

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        # Stall detector: same tile, same screen, no goal for 15 agent steps -> escalate instead of repeating.
        sig = (m, x, y, tuple(sorted(ctx.goal_steps)))  # NOT the screen hash: printing text changes it every press
        ctx.stall = ctx.stall + 1 if sig == ctx.last_sig else 0
        ctx.last_sig = sig
        if ctx.stall >= 15:
            ctx.stall = 0; ctx.stalls = ctx.stalls + 1
            if ctx.replay_ctx:
                ctx.replay = []; grade_replay(ctx)
            esc = ["B", "START", random.choice(list(DIRS)), "A", "B", random.choice(list(DIRS))][ctx.stalls % 6]
            return Decision(esc, "stall_escalate", f"STALL #{ctx.stalls} detected here - escalating with {esc}")
        return None

    def failed(self, ctx: ExplorerContext) -> bool:
        return ctx.stall >= 15
