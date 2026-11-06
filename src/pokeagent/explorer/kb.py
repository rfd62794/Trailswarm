"""The cartridge's own tables (move powers, type chart, dex map, species, trainers ...), drained by tools/rom_tables.py.

``ROM_KB`` is None when kb/rom_tables.json is absent (no ROM was ever read on this machine). Loaded in pokeagent.knowledge.kb.
"""
from __future__ import annotations

from pokeagent.knowledge.kb import ROM_KB  # noqa: F401
