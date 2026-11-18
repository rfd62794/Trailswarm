"""Activity segments: the run as maximal stretches of one activity each.

``ACTIVITY`` names what each behaviour is doing while it owns a step, read off the behaviour files
in ``src/pokeagent/explorer/behaviours/``; battle wins over everything else while the battle flag is
up. There is deliberately no "training" activity: telling a training fight from any other needs the
agent's training state, which is not logged per step yet (Rewinder slice 4), so it is not inferred
from rule names either.
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.rewind.frames import Frame, Rewind

# behaviour name -> activity. Every name in default_behaviours() must appear (tested).
ACTIVITY: dict[str, str] = {
    # settle pauses and input-readiness waits
    "settle": "wait",            # pause after a map change
    "post_talk_settle": "wait",  # let the screen redraw after a text box closes
    "readiness": "wait",         # wait/nudge while the screen is busy or the joypad is ignored
    "anomaly_wait": "wait",      # wait for a wandering NPC to move off the pressed tile
    "box_settle": "wait",        # never press A at an empty (opening/closing) text box
    # battles (also forced while frame.in_battle, whatever the behaviour)
    "battle": "battle", "battle_moves": "battle", "battle_yesno": "battle",
    "battle_text_wait": "battle", "switch_out": "battle", "already_out": "battle",
    "catch": "catch",
    # text boxes and dialog
    "naming_keyboard": "text",   # name entry: START ends the keyboard
    "beat_start": "text",        # a known button sequence for this box text runs automatically
    "advance_dialog": "text",    # keep text boxes moving
    # menus and menu-driven sequences
    "menu": "menu",              # YES/NO answers, move-forgetting, goal menu choices
    "field_cut": "menu",         # START -> POKeMON -> member -> CUT on a tree in the route
    "party_order": "menu",       # START -> POKeMON -> SWITCH reorder walk
    "procedures": "menu",        # named menu-task sequences (check health, open bag, save, TOWN MAP)
    "procedure_runner": "menu",  # a loaded goal procedure's bounded steps
    "cave_escape": "menu",       # START -> ITEM -> ESCAPE ROPE -> USE sequence
    "use_items": "menu",         # item-use sequences through the START menu (potion, bike, teach)
    # healing and shopping
    "heal": "heal",              # the Mom-heal check
    "retreat_heal": "heal",      # decide a precautionary walk back to a Pokecenter
    "status_care": "heal",       # cure poison / walk to the nurse
    "cave_topup": "heal",        # drink a Potion from the START menu while HP is low
    "restock": "shop",           # a Mart trip: walk there, sell, buy, leave
    # movement: routing, exploring, hunting, pacing grass
    "goto": "move", "frontier": "move", "explore_burst": "move", "plan_goal": "move",
    "goal_talk": "move",         # walk to the one person a goal needs, then A
    "grind_drill": "move",       # pace a grass patch on a grind map
    "pickup": "move",            # detour to an item ball and press A
    "gym_puzzle": "move",        # walk to a trash can and press A (Lt. Surge's locks)
    "learner_hunt": "move", "team_hunt": "move", "trainer_hunt": "move",
    # loop-breakers, replays, bookkeeping
    "guards": "other",           # shake walks / back-outs that break a detected loop
    "stall_guard": "other",      # stall escalation presses
    "replay_interrupt": "other", "replay_beat": "other",
    "after_victory": "other",    # post-trainer-win decision (potion / heal / push on)
}


def activity(frame: Frame) -> str:
    """What the agent is doing at this frame: battle whenever the flag is up, else the behaviour's."""
    return "battle" if frame.in_battle else ACTIVITY.get(frame.behaviour, "other")


@dataclass(frozen=True)
class Segment:
    """A maximal run of consecutive steps with one activity; ``end`` is inclusive."""

    start: int
    end: int
    activity: str


def segments(rw: Rewind) -> list[Segment]:
    """The run's activity segments in step order, covering first..last with no gaps or overlaps."""
    if len(rw) == 0:
        return []
    out = []
    start, cur = rw.first_step, activity(rw.frame(rw.first_step))
    for step in range(start + 1, rw.last_step + 1):
        a = activity(rw.frame(step))
        if a != cur:
            out.append(Segment(start, step - 1, cur))
            start, cur = step, a
    out.append(Segment(start, rw.last_step, cur))
    return out


def shares(segs: list[Segment]) -> dict[str, float]:
    """Fraction of steps per activity, summing to 1.0 (empty input -> {})."""
    counts: dict[str, int] = {}
    for s in segs:
        counts[s.activity] = counts.get(s.activity, 0) + s.end - s.start + 1
    total = sum(counts.values())
    return {a: n / total for a, n in counts.items()} if total else {}
