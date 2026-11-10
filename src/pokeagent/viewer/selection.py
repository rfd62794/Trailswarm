"""The one selection the stitched World renderer shares across map, focus panel and agent list (pure).

``auto`` follows whichever registry agent is "featured" (freshest live file); a user pick
(``select``) stays until "Auto" is chosen or a picked registry agent disappears. No Dear PyGui
import: the map window, the side panel and the status line all read this same object.
"""
from __future__ import annotations

from typing import Callable

AUTO, USER = "auto", "user"
LIVE, GHOST = "live", "ghost"


class Selection:
    """What is selected: ``agent`` (a registry id or a ghost-only name), ``source`` ("auto" |
    "user") and ``is_live`` (True when the name is a live/registry agent, False for ghost-only)."""

    def __init__(self) -> None:
        self.agent: str | None = None
        self.source: str = AUTO
        self.is_live: bool = False

    def update(self, live: dict, registry_ids: list[str]) -> str | None:
        """Re-evaluate after a poll. While ``auto`` the selection follows ``featured``; a user pick
        of a registry agent that disappeared releases back to auto (a ghost pick survives)."""
        if self.source == USER and self.is_live and self.agent not in (registry_ids or []):
            self.source = AUTO
        if self.source == AUTO:
            self.agent = featured(live, registry_ids)
            self.is_live = self.agent is not None
        return self.agent

    def select(self, agent: str, kind: str = LIVE) -> None:
        """A user pick: ``kind`` is "live" (a registry agent) or "ghost" (recorded-only name)."""
        self.agent, self.source, self.is_live = agent, USER, kind == LIVE

    def auto(self) -> None:
        """The "Auto" button: release the pick; the next ``update`` re-features the selection."""
        self.source = AUTO


def featured(live: dict, registry_ids: list[str]) -> str | None:
    """The registry agent with the freshest live file; else the first registry id; else None.
    A live record for a non-registry name is ignored for featuring (it is still drawn on the map)."""
    best, at = None, float("-inf")
    for aid, pos in live.items():
        if aid in registry_ids and getattr(pos, "updated_at", 0.0) > at:
            best, at = aid, pos.updated_at
    return best if best is not None else (registry_ids[0] if registry_ids else None)


def gameplay_agent(sel: Selection, registry_ids: list[str], featured_id: str | None) -> tuple[str | None, str]:
    """Which registry agent the gameplay panel shows, plus the notice under it. A live selection
    shows itself; a ghost-only selection keeps the featured agent with the recorded-run notice
    (replay on demand is out of scope); no registry agent at all is ``(None, "no live agent")``."""
    if sel.is_live and sel.agent is not None:
        return sel.agent, ""
    if not registry_ids:
        return None, "no live agent"
    if sel.agent is None:
        return featured_id, ""
    return featured_id, f"{sel.agent}: recorded run, no live frames - showing {featured_id}"


def camera_target(sel: Selection, live: dict, best_ghost_pos_for: Callable) -> tuple[float, float] | None:
    """The space point the camera follows, or None (the camera stays). ``live`` maps a registry
    agent to its space position (the caller computed them via ``layout.locate``);
    ``best_ghost_pos_for(agent)`` gives a ghost-only name's current best-ghost position."""
    if sel.agent is None:
        return None
    if sel.is_live:
        return live.get(sel.agent)
    return best_ghost_pos_for(sel.agent)
