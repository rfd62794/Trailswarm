"""The cartridge's own tables (move powers, type chart, dex map), drained by tools/rom_tables.py.

``ROM_KB`` is None when kb/rom_tables.json is absent (no ROM was ever read on this machine).
"""
from __future__ import annotations

import json
from pathlib import Path

_KB = Path(__file__).resolve().parents[3] / "kb" / "rom_tables.json"
ROM_KB = json.loads(_KB.read_text(encoding="utf-8")) if _KB.exists() else None  # tools/rom_tables.py drains it from the cartridge
