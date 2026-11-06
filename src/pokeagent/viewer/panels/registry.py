"""Panel registry: which panels a card shows and in what order (the single place that knows the set)."""
from __future__ import annotations

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.panels import focus as _focus
from pokeagent.viewer.panels import progress as _progress
from pokeagent.viewer.panels import sees as _sees
from pokeagent.viewer.panels import thinking as _thinking

# Multi-view card order: Render | Sees on top (handled by the UI as textures/text), then the
# text panels top-to-bottom. ``render`` has no text lines - it feeds a texture.
PANELS = ("render", "sees", "thinking", "progress")
FOCUS_PANELS = PANELS + ("focus",)

_LINE_FUNCS = {
    "sees": _sees.sees_lines,
    "thinking": _thinking.thinking_lines,
    "progress": _progress.progress_lines,
    "focus": _focus.focus_lines,
}


def lines_for(name: str, snap: AgentSnapshot, **kw) -> list:
    """Styled lines for a text panel; ``render`` (and unknown names) return []."""
    fn = _LINE_FUNCS.get(name)
    return fn(snap, **kw) if fn is not None else []
