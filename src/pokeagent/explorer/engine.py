"""Engine: one explorer step = the selector chooses, the presser presses, the decision log records.

This is the old ``agent_step()`` closure's job, minus the window and the HTTP API (those stay in the demo).
"""
from __future__ import annotations

from pokeagent.explorer import grind_episode, loop_veto, party_log, retalk_memory, trainer_ledger, xp_meter
from pokeagent.explorer.behaviours import default_behaviours
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.decisions import DecisionLog, classify_outcome, goal_stage, make_record
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open
from pokeagent.explorer.press import Presser
from pokeagent.explorer.press_goals import seed_initial_goals
from pokeagent.explorer.progress import PROGRESS_LOG_EVERY, ProgressLog, ProgressTracker
from pokeagent.explorer.retalk_veto import veto
from pokeagent.explorer.selector import Selector
from pokeagent.explorer.toss_guard import toss_veto
from pokeagent.explorer.training_ctl.controller import TrainingController
from pokeagent.novelty.features import Snapshot, read_snapshot

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
        self._progress = ProgressTracker()  # presses since the last progress (explorer.progress)
        self._prog_snap: Snapshot | None = None  # the game-state snapshot of the previous press
        self._prog_log: ProgressLog | None = None  # progress.jsonl, opened on first write
        self._training = TrainingController()  # slice 1: shadow owner of the training flags (never writes)

    def step(self) -> Decision | None:
        ctx = self.ctx
        if ctx.bandit is not None:
            ctx.bandit.begin_step()
        seed_initial_goals(ctx)  # before the first decision, not after the first press
        decision = self.selector.choose(ctx)
        self._training.observe(ctx)  # shadow check of the training flags plan_goal just set
        party_log.of(ctx).tick(ctx)  # level timeline: out-of-battle level/exp changes, grind/travel step counts
        xp_meter.of(ctx).tick(ctx)  # XP windows: per-member rates, xp_rates.jsonl, spot ledger (measurement only)
        trainer_ledger.tick(ctx)  # trainer ledger: new maps, talk probes, the 50-step flag sync (never raises)
        grind_episode.tick(ctx)   # grind episode: start/end checks run here so applies() stays a pure read
        self.last_decision = decision
        if decision is None or not decision.button:
            return decision  # nothing to do, or a wait: the step is used without a press
        decision = loop_veto.check(ctx, self.selector, decision)  # a dead (situation, button) is skipped, not re-pressed
        self.last_decision = decision
        if not decision.button:
            return decision  # the veto re-chose a wait (e.g. post_talk_settle): pressing "" raised KeyError('')
        why_veto = veto(ctx, decision)
        if why_veto:  # the policy table says this talk teaches nothing: B instead of A (keeps the loop guards counting)
            retalk_memory.note(ctx, decision)  # and the planner must not choose this talk again
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
        reasons = self._note_progress(goals_reached, after)
        loop_veto.record(ctx, decision, reasons)
        self._pending_outcomes.append(rec)
        del self._pending_outcomes[:-MAX_PENDING]  # no goal for a long time: keep only the most recent
        if len(ctx.goal_steps) > goals_reached:
            self._flush_outcomes(ctx.step)
        elif ctx.done:
            self._flush_outcomes(None)
        if ctx.done:
            loop_veto.finish(ctx)  # fold this run's dead actions into the shared memory, write the ledger row
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

    def _progress_snapshot(self) -> Snapshot:
        """One game-state snapshot per press. When novelty is on it already read this press's: reuse its
        ``prev`` (the current one after observe) rather than read the same RAM twice."""
        snap = getattr(self.ctx.novelty, "prev", None) if self.ctx.novelty is not None else None
        return snap if isinstance(snap, Snapshot) else read_snapshot(self.ctx.emu)

    def _progress_log(self, ctx) -> ProgressLog:
        if self._prog_log is None:
            self._prog_log = ProgressLog(ctx.run_dir / "progress.jsonl", ctx.log, buf=getattr(ctx, "jsonl_buf", None))
        return self._prog_log

    def _note_progress(self, goals_before: int, after: tuple) -> list[str]:
        """The per-step progress signal: did this press change anything worth changing (progress.py) and how
        long it has been since something did. The returned reasons feed the loop ledger's fruitless count."""
        ctx = self.ctx
        try:
            cur = self._progress_snapshot()
            prev, self._prog_snap = self._prog_snap, cur
            new_tile = ctx.mem.m(after[0])["visited"].get(f"{after[1]},{after[2]}", 0) <= 1  # count 1 = this press's visit
            gap = self._progress.steps_since  # presses since the last progress, before this press
            battle_ended = prev is not None and prev.in_battle and not cur.in_battle
            reasons = self._progress.observe(ctx.step, prev, cur, new_tile, goals_before, len(ctx.goal_steps), battle_ended)
            ctx.steps_since_progress = self._progress.steps_since
            if reasons:
                self._progress_log(ctx).event(ctx.step, ctx.frame, reasons, gap)
            elif ctx.step % PROGRESS_LOG_EVERY == 0:
                self._progress_log(ctx).heartbeat(ctx.step, self._progress.steps_since)
            return reasons
        except Exception as exc:  # noqa: BLE001  like novelty: an observer must never stop a run
            ctx.log(f"[progress skipped: {exc!r}]", "res")
            return []

    def _flush_outcomes(self, goal_step: int | None) -> None:
        """Back-fill goal-keyed tile outcomes for a finished goal segment: every pending press gets
        presses_to_goal = presses between it and the goal (None when the segment ended without one)."""
        for rec in self._pending_outcomes:
            self.ctx.mem.record_outcome(rec["map"], rec["x"], rec["y"], rec["button"], rec["goal_stage"],
                                        rec["outcome"] not in ("blocked", "none"),
                                        None if goal_step is None else goal_step - rec["step"])
        self._pending_outcomes.clear()
