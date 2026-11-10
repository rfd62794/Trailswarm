"""Which renderer World mode uses for a launch (pure): the preset's ``world_renderer`` field.

No ``--source`` means ``"rom-world"`` always, so every existing launch is unchanged. With a
source the resolved preset decides; unknown names fall back through ``resolve`` as usual.
"""
from __future__ import annotations

from pokeagent.mapview.presets import Preset, resolve

ROM_WORLD, STITCHED = "rom-world", "stitched"


def choose(preset=None, source=None) -> str:
    """``"rom-world" | "stitched"``. ``preset`` is a resolved ``Preset`` or a preset name (None =
    the default); an unknown name resolves to its genre's row rather than raising."""
    if source is None:
        return ROM_WORLD
    p = preset if isinstance(preset, Preset) else resolve(preset=preset)
    return STITCHED if getattr(p, "world_renderer", ROM_WORLD) == STITCHED else ROM_WORLD
