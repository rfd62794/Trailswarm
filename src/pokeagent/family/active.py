"""When the family code runs: only for gen1-pokemon games, and never for a Red-only repo."""
from __future__ import annotations

from pathlib import Path

from pokeagent.family.provenance import provenance_path
from pokeagent.game.spec import LEGACY_FAMILY, GameSpec


def family_active(game: GameSpec, shared_path: str | Path) -> bool:
    """True for a non-founder family member, or for Red once the provenance file exists (so a Red-only
    repo never creates provenance, overlay or report files and its maps.json bytes stay as before)."""
    if game.memory_family != LEGACY_FAMILY:
        return False
    return (not game.owns_legacy_paths) or provenance_path(shared_path).exists()
