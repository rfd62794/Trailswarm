"""replay_beat: replay learned button sequences (text-triggered beats and recorded demonstrations), graded after."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.demos import grade_replay, matching_demo
from pokeagent.explorer.perceive import is_menu
from pokeagent.goals import check_goals


class ReplayInterrupt(BehaviourBase):
    """A box or a battle interrupted a demonstration: grade it now."""

    name = "replay_interrupt"

    def applies(self, ctx: ExplorerContext) -> bool:
        return bool(ctx.replay) and (ctx.view.battling or ctx.view.box)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        ctx.replay = []
        grade_replay(ctx)
        return None


class BeatStart(BehaviourBase):
    """Text-triggered beat: a known good sequence for this box text runs automatically (and gets graded)."""

    name = "beat_start"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.box

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        tm_now, lines_now = ctx.view.tm, ctx.view.lines
        sig = lines_now[0][:60] if len(lines_now) >= 2 else None
        beat = ctx.mem.beat_for(sig) if sig else None
        if is_menu(tm_now) and ctx.replay:  # a menu/YES-NO appeared mid-replay: stop, let the rules decide
            ctx.replay = []; ctx.pop("replay_ctx")
        if beat and not ctx.replay and not is_menu(tm_now) and ctx.beat_sig_done != sig and not ctx.explore_run:
            ctx.replay = list(beat["buttons"]); ctx.beat_sig_done = sig
            ctx.replay_ctx = {"demo": beat, "pos": (m, x, y), "goals": check_goals(ctx.emu, ctx)}
            ctx.log(f"[recognised \"{sig[:40]}\": running the known {len(beat['buttons'])}-press beat (grade {beat['grade']})]", "res")
            btn = ctx.replay.pop(0)
            return Decision(btn, "beat_replay", "beat replay", after=None if ctx.replay else grade_replay)
        return None


class ReplayBeat(BehaviourBase):
    """Continue a running replay, or start a matching recorded demonstration for this spot."""

    name = "replay_beat"

    def applies(self, ctx: ExplorerContext) -> bool:
        return bool(ctx.replay) or self._candidate(ctx) is not None

    def _candidate(self, ctx: ExplorerContext):
        v = ctx.view
        demo = matching_demo(ctx, v.m, v.x, v.y, v.tm)
        if demo and ctx.explore_run:
            demo = None  # this run is an exploration run: ignore known demonstrations and try to beat them
        if demo and ctx.replayed_here == (v.m, v.x, v.y, ctx.step // 50):
            demo = None
        return demo

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        if ctx.replay:  # replaying a demonstration (graded afterwards, dropped if it does not work)
            btn = ctx.replay.pop(0)
            why = f"testing a {ctx.replay_ctx['demo']['source']} demonstration ({len(ctx.replay)} presses left)"
            return Decision(btn, "replay_demo", why, after=None if ctx.replay else grade_replay)
        demo = self._candidate(ctx)
        if demo:
            ctx.replay = list(demo["buttons"]); ctx.replayed_here = (m, x, y, ctx.step // 50)
            ctx.replay_ctx = {"demo": demo, "pos": (m, x, y), "goals": check_goals(ctx.emu, ctx)}
            ctx.log(f"[testing a {demo['source']} demonstration for this spot (grade {demo.get('grade', 0)}): {demo['buttons']}]", "res")
            return no_press("replay_start")
        return None

    def done(self, ctx: ExplorerContext) -> bool:
        return not ctx.replay

    def failed(self, ctx: ExplorerContext) -> bool:
        return bool(ctx.replay_ctx) and ctx.replay_ctx["demo"].get("grade", 0) < 0
