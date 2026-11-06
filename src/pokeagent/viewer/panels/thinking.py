"""Thinking panel: want, plan-or-blocker, driver+rule, button->result, brain line, human hold."""
from __future__ import annotations

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.panels import DIM, TEXT, WARN, Line, driver_color, plain, span


def thinking_lines(snap: AgentSnapshot, hold_s: float | None = None) -> list[Line]:
    """``hold_s`` is the human-hold countdown when the caller knows it (agents on HTTP do not
    publish it, so the card shows a bare "YOU HAVE IT"); ``thinking.brain`` gets its own line."""
    t = snap.thinking
    out: list[Line] = []
    if snap.human_hold:
        left = f" {hold_s:.1f}s" if hold_s is not None else ""
        out.append([span("YOU HAVE IT", driver_color("human")), span(left, TEXT)])
    if t.want:
        out.append(plain(f"want  {t.want}"))
    if t.blocker:
        out.append([span("blocker  ", WARN), span(t.blocker, TEXT)])
    elif t.plan:
        out.append(plain(f"plan   {t.plan}"))
    if t.driver or t.rule:
        line: Line = []
        if t.driver:
            line.append(span(t.driver, driver_color(t.driver)))
            line.append(span("  ", TEXT))
        if t.rule:
            line.append(span(t.rule, DIM))
        if t.confidence is not None:
            line.append(span(f"   conf {t.confidence:.2f}", DIM))
        out.append(line)
    if t.button and t.result:
        out.append(plain(f"{t.button} -> {t.result}"))
    elif t.button or t.result:
        out.append(plain(t.button or t.result))
    if t.brain:
        out.append(plain(t.brain, DIM))
    return out
