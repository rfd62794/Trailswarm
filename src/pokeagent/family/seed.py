"""Seeding an agent's own maps file from the shared one (the read hook of the swarm)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from pokeagent.family.active import family_active
from pokeagent.family.overlay import effective_memory, load_overlay
from pokeagent.game import resolve_game


def seed_own(src: str | Path, own: str | Path, game=None) -> None:
    """Plain copy when the family is inactive or the game has no overlay, else the overlay-first view."""
    game = game or resolve_game(None)
    if not family_active(game, src):
        shutil.copy(src, own)
        return
    overlay = load_overlay(src, game.key)
    if not overlay.get("maps"):  # nothing to apply for this game: keep the bytes identical (Red stays byte-for-byte)
        shutil.copy(src, own)
        return
    shared = json.loads(Path(src).read_text(encoding="utf-8"))
    Path(own).write_text(json.dumps(effective_memory(shared, overlay)), encoding="utf-8")
