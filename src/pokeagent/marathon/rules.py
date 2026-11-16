"""The marathon stall rules: pure functions over a RunView, each returning None or (code, detail).

Thresholds are module constants in presses, tunable via the CLI flags. Rule order is priority:
hung, guard_stall, oscillation, map_dwell, goal_budget - the first hit wins the status and every
hit is listed in ``detail``. A run under a claude lease is ``held`` (skipped entirely); a run
younger than MIN_PRESSES is ``young``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pokeagent.goals import GOALS

GOAL_BUDGET = 2500       # presses since the last goal (or run start) before a stage reads stalled
GRIND_BUDGET = 6000      # same, while a floor-training stage is pending (XP gains reset the clock)
DWELL_PRESSES = 2000     # presses on one map with no goal and no floor-directed XP gain (dungeons 2x)
OSC_TRANSITIONS = 40     # crossings of one unordered map pair inside OSC_WINDOW
OSC_WINDOW = 1500        # presses
STALL_ESCALATIONS = 25   # distinct in-run "STALL #" escalations since the last goal
MIN_PRESSES = 300        # younger runs are never judged


def _grind_goals() -> tuple[str, ...]:
    """Stages that train toward a level floor, derived from the repo's own training knowledge
    (never a hand list): the ladder's hold goal (team_ready), every goal ``TRAIN_LEVEL_BY_GOAL``
    names - the boss a gym hold's floor is for - and ``MT_MOON_FLOOR_GOALS``, the floor goals
    whose stage has a floor of its own."""
    try:
        from pokeagent.explorer.training import MT_MOON_FLOOR_GOALS, TRAIN_LEVEL_BY_GOAL
        floors = frozenset(TRAIN_LEVEL_BY_GOAL) | frozenset(MT_MOON_FLOOR_GOALS)
    except Exception:  # knowledge tables unavailable: the ladder's own hold still counts
        floors = frozenset()
    return tuple(g for g in GOALS if g == "team_ready" or g in floors)


GRIND_GOALS = _grind_goals()


@dataclass(frozen=True)
class Thresholds:
    goal_budget: int = GOAL_BUDGET
    grind_budget: int = GRIND_BUDGET
    dwell: int = DWELL_PRESSES
    osc_transitions: int = OSC_TRANSITIONS
    osc_window: int = OSC_WINDOW
    stall_escalations: int = STALL_ESCALATIONS
    min_presses: int = MIN_PRESSES


def rule_hung(view, hung_check=None):
    """Delegate to ProgressWatch.check()'s hung branch (injected by the caller - the marathon
    package must not import tools/, and the swarm's loop rule is not reimplemented here)."""
    reason = hung_check() if hung_check else None
    return ("hung", reason) if reason and reason.startswith("hung") else None


def rule_guard_stall(view, th: Thresholds):
    """The in-run StallGuard escalated >= stall_escalations times since the last goal."""
    n = view.stalls_since(view.last_goal_press)
    if n >= th.stall_escalations:
        return ("guard_stall", f"{n} STALL escalations since the last goal (>= {th.stall_escalations})")
    return None


def rule_oscillation(view, th: Thresholds):
    """One unordered map pair crossed >= osc_transitions times in the trailing window, no goal."""
    if view.last_goal_press > view.presses - th.osc_window:
        return None  # a goal inside the window forgives the crossings
    counts = Counter()
    for prev, cur in zip(view.segments, view.segments[1:]):
        if cur[1] > view.presses - th.osc_window:
            counts[tuple(sorted((prev[0], cur[0])))] += 1
    pair, n = counts.most_common(1)[0] if counts else (None, 0)
    if n >= th.osc_transitions:
        return ("oscillation", f"{n} crossings between maps {pair[0]:#04x} and {pair[1]:#04x} "
                               f"in the last {th.osc_window} presses")
    return None


def rule_map_dwell(view, th: Thresholds):
    """One map continuously over the dwell limit with no goal landing and no floor-directed XP
    gain (the last goal or - in a grind stage - the last XP gain restarts the clock)."""
    if not view.segments:
        return None
    m, first, _ = view.segments[-1]
    try:
        from pokeagent.explorer.world import DUNGEON_MAPS
        limit = th.dwell * (2 if m in DUNGEON_MAPS else 1)
    except ImportError:
        limit = th.dwell
    since = max(first, view.last_goal_press)
    if view.current_goal in GRIND_GOALS:
        since = max(since, view.train_at)
    dwell = view.presses - since + 1
    if dwell > limit:
        return ("map_dwell", f"{dwell} presses on map {m:#04x} (limit {limit})")
    return None


def rule_goal_budget(view, th: Thresholds):
    """Presses since the last goal (or run start) over the budget: GRIND_BUDGET while the pending
    goal is a floor-training stage (a floor-directed XP gain resets it; tiles never do), else
    GOAL_BUDGET - and outside grind stages XP does not reset this rule."""
    grind = view.current_goal in GRIND_GOALS
    budget = th.grind_budget if grind else th.goal_budget
    since = view.presses - max(view.last_goal_press, view.train_at if grind else 0)
    if since > budget:
        return ("goal_budget", f"{since} presses since the last goal (budget {budget}, "
                               f"goal {view.current_goal or 'none'})")
    return None


_RULES = (rule_hung, rule_guard_stall, rule_oscillation, rule_map_dwell, rule_goal_budget)


def hits(view, th: Thresholds, hung_check=None) -> list[tuple[str, str]]:
    """Every rule that fires, in priority order."""
    out = []
    for fn in _RULES:
        h = fn(view, hung_check) if fn is rule_hung else fn(view, th)
        if h:
            out.append(h)
    return out


def evaluate(view, th: Thresholds | None = None, hung_check=None) -> dict:
    """{status, reason, detail, hits}: held and young skip the rules entirely; the first hit wins
    the reason and every hit is in detail."""
    th = th or Thresholds()
    if view.held():
        return {"status": "held", "reason": "claude hold", "detail": "", "hits": []}
    if view.presses < th.min_presses:
        return {"status": "young", "reason": "young", "detail": f"{view.presses} presses < {th.min_presses}",
                "hits": []}
    found = hits(view, th, hung_check)
    if not found:
        return {"status": "ok", "reason": "ok", "detail": "", "hits": []}
    return {"status": "stalled", "reason": found[0][0],
            "detail": "; ".join(d for _, d in found), "hits": [c for c, _ in found]}
