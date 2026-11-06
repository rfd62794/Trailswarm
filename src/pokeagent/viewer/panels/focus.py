"""Focus-view extras: recent decision log, party/bag/money, goal list with first-reached steps."""
from __future__ import annotations

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.panels import DIM, TEXT, Line, driver_color, plain, span

_GOAL_MARK = {"done": "v", "current": ">", "ahead": "-"}
_GOAL_COLOR = {"done": "#5fa85f", "current": "#e0b050", "ahead": "#8a8f98"}
_MAX_EVENT_CHARS = 90


def _clip(text: str, n: int = _MAX_EVENT_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def focus_lines(snap: AgentSnapshot) -> list[Line]:
    out: list[Line] = []
    if snap.recent:
        out.append(plain("recent", DIM))
        for ev in snap.recent[-10:]:
            out.append([span(f"  {ev.step} ", DIM), span(ev.driver or "?", driver_color(ev.driver)),
                        span(f"  {_clip(ev.text)}", TEXT)])
    screen = snap.screen
    if screen.party or screen.money is not None or screen.bag_summary:
        out.append(plain("party / bag / money", DIM))
        for m in screen.party:
            name = m.species or "?"
            out.append(plain(f"  {name} L{m.level}  {m.hp}/{m.max_hp}"))
            if m.dvs:
                out.append(plain(f"    DV {m.dvs}  statexp {m.stat_exp}", DIM))
        if screen.money is not None:
            out.append(plain(f"  money {screen.money}"))
        if screen.bag_summary:
            out.append(plain(f"  bag  {_clip(screen.bag_summary, 70)}"))
    if snap.goals:
        done = sum(1 for g in snap.goals if g.status == "done")
        out.append(plain(f"goals {done}/{len(snap.goals)}", DIM))
        cur = next((i for i, g in enumerate(snap.goals) if g.status != "done"), len(snap.goals))
        for g in (snap.goals if len(snap.goals) <= 12 else snap.goals[max(0, cur - 1):cur + 5]):  # last done, current, next 4
            steps = f" ({g.steps})" if g.steps is not None else ""
            label = g.name or g.id
            out.append([span(f"  {_GOAL_MARK.get(g.status, '-')} {label}{steps}",
                             _GOAL_COLOR.get(g.status, DIM))])
    if not out:
        out.append(plain("(no focus data)", DIM))
    return out
