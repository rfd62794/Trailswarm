"""Pure view-mode vocabulary: Tiles (card grid) and World. Internally FocusState keeps 'grid' | 'world'."""
from __future__ import annotations

DEFAULT_MODE = "world"           # World is the primary view; Tiles is the secondary tab (Robert, 2026-11-06)
CHOICES = ("tiles", "world")     # what `--mode` accepts
_TO_INTERNAL = {"tiles": "grid", "world": "world"}
_LABEL = {"grid": "Tiles", "world": "World", "focus": "Focus"}


def internal(mode: str) -> str:
    """CLI/user mode name -> FocusState mode ('tiles' -> 'grid')."""
    return _TO_INTERNAL[mode]


def label(view: str) -> str:
    return _LABEL.get(view, view)


def status_text(view: str, agents: int, selected: str | None, follow_id: str | None) -> str:
    """The always-visible status line: mode, agent count, selected agent, follow on/off."""
    follow = f"on ({follow_id})" if follow_id else "off"
    return f"Mode: {label(view)}  |  Agents: {agents}  |  Selected: {selected or 'none'}  |  Follow: {follow}"
