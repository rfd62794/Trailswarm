"""Engine: one explorer step = the selector chooses, the presser presses, the decision log records.

This is the old ``agent_step()`` closure's job, minus the window and the HTTP API (those stay in the demo).
"""
from __future__ import annotations

from pokeagent.explorer import party_log
from pokeagent.explorer.behaviours import default_behaviours
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.decisions import DecisionLog, classify_outcome, goal_stage, make_record
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open
from pokeagent.explorer.press import Presser
from pokeagent.explorer.press_goals import seed_initial_goals
from pokeagent.explorer.retalk_veto import veto
from pokeagent.explorer.selector import Selector
from pokeagent.explorer.toss_guard import toss_veto

MAX_PENDING = 2000  # cap on un-flushed decision records


def _tossed(ctx: ExplorerContext) -> int:
    """How many item_tossed anomalies the monitor has recorded this run."""
    return sum(f["type"] == "item_tossed" for f in ctx.anomalies.findings) if ctx.anomalies is not None else 0


class Engine:
    def __init__(self, ctx: ExplorerContext, presser: Presser | None = None, selector: Selector | None = None,
                 decision_log: DecisionLog | None = None) -> None:
        self.ctx = ctx
        self.presser = presser or Presser(ctx)
        self.selector = selector or Selector(default_behaviours())
        self.decision_log = decision_log
        self._prev_from = None  # `from` position of the last press that moved the player
        self._pending_outcomes: list[dict] = []  # decision records since the last goal event
        self.last_decision: Decision | None = None  # most recent choose() result (viewer adapter reads it)

    def step(self) -> Decision | None:
        ctx = self.ctx
        if ctx.bandit is not None:
            ctx.bandit.begin_step()
        seed_initial_goals(ctx)  # before the first decision, not after the first press
        decision = self.selector.choose(ctx)
        party_log.of(ctx).tick(ctx)  # level timeline: out-of-battle level/exp changes, grind/travel step counts
        self.last_decision = decision
        if decision is None or not decision.button:
            return decision  # nothing to do, or a wait: the step is used without a press
        why_veto = veto(ctx, decision)
        if why_veto:  # the policy table says this talk teaches nothing: B instead of A (keeps the loop guards counting)
            decision = Decision("B", "retalk_veto", why_veto, behaviour=decision.behaviour)
        why_toss = toss_veto(ctx.view.lines, decision)
        if why_toss:  # a toss screen is up: nothing may advance it, whichever behaviour pressed (B backs out, NO then A declines)
            decision = Decision("B", "toss_veto", why_toss, behaviour=decision.behaviour)
        view = ctx.view
        before, box, battle = (view.m, view.x, view.y), view.box, view.battling
        stage, goals_reached = goal_stage(ctx.goals()), len(ctx.goal_steps)
        tossed_before = _tossed(ctx)
        ctx.deciding_rule = decision.rule  # record_interaction reads it: choose_local's reason text does not say which rule chose
        self.presser.press(decision.button, "agent", decision.why)
        ctx.deciding_rule = ""
        if decision.after is not None:
            decision.after(ctx)
        after = ctx.pos()
        box_after = box_open(ctx.emu.read_range(TILEMAP, TILEMAP_LEN))
        outcome = classify_outcome(before, after, decision.button, box_after, len(ctx.goal_steps) > goals_reached)
        reversal = after != before and after == self._prev_from
        if after != before:
            self._prev_from = before
        rec = make_record(ctx.step, decision.behaviour, decision.rule, decision.button, before,
                          stage, box, battle, outcome, reversal)
        if ctx.bandit is not None:
            rec = ctx.bandit.tag(rec)  # driver/arm: only runs with the bandit on carry them
        if decision.driver:
            rec = {**rec, "driver": decision.driver}  # par_follow drove this press
        if self.decision_log is not None:
            self.decision_log.write(rec)
        if ctx.anomalies is not None:
            ctx.anomalies.note_decision(rec)
        if ctx.bandit is not None:
            for ev in ctx.bandit.after_press(ctx, rec, _tossed(ctx) > tossed_before):
                if self.decision_log is not None:
                    self.decision_log.write(ev)
        if self.decision_log is not None and _tossed(ctx) > tossed_before:  # an item was thrown away: the bandit reward counts this line
            self.decision_log.write({**rec, "event": "item_tossed", "outcome": "item_tossed"})
        self._note_novelty()
        self._pending_outcomes.append(rec)
        del self._pending_outcomes[:-MAX_PENDING]  # no goal for a long time: keep only the most recent
        if len(ctx.goal_steps) > goals_reached:
            self._flush_outcomes(ctx.step)
        elif ctx.done:
            self._flush_outcomes(None)
        if ctx.done:
            ctx.mem.save()  # shutdown() already saved inside the press, before the outcomes were back-filled
        return decision

    def _note_novelty(self) -> None:
        """Novelty off (ctx.novelty None): nothing. On: count what this press found; an explorer-role bandit run is paid for it."""
        ctx = self.ctx
        if ctx.novelty is None:
            return
        try:
            gain = ctx.novelty.observe(ctx.emu, ctx.step)
            if gain and ctx.bandit is not None:
                ctx.bandit.add_novelty(gain)
        except Exception as exc:  # noqa: BLE001  novelty is an add-on: it must never stop a run
            ctx.log(f"[novelty skipped: {exc!r}]", "res")

    def _flush_outcomes(self, goal_step: int | None) -> None:
        """Back-fill goal-keyed tile outcomes for a finished goal segment: every pending press gets
        presses_to_goal = presses between it and the goal (None when the segment ended without one)."""
        for rec in self._pending_outcomes:
            self.ctx.mem.record_outcome(rec["map"], rec["x"], rec["y"], rec["button"], rec["goal_stage"],
                                        rec["outcome"] not in ("blocked", "none"),
                                        None if goal_step is None else goal_step - rec["step"])
        self._pending_outcomes.clear()
