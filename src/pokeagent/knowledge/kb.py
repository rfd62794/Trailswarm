"""The cartridge's drained tables (kb/rom_tables.json, gitignored; tools/rom_tables.py writes it). None without a ROM read."""
from __future__ import annotations

import json
from pathlib import Path

_KB = Path(__file__).resolve().parents[3] / "kb" / "rom_tables.json"
ROM_KB = json.loads(_KB.read_text(encoding="utf-8")) if _KB.exists() else None


def table(kb: dict | None, key: str) -> dict:
    """kb[key] for an explicit kb, else the loaded one; {} when absent."""
    src = kb if kb is not None else ROM_KB
    return (src or {}).get(key) or {}
