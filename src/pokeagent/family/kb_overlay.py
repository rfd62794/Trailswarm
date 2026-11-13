"""Per-game kb overlay: only what a game's kb holds differently from the family base (key-agnostic)."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def build_overlay(base: dict, game_kb: dict) -> dict:
    """Top-level keys of ``game_kb`` that differ from ``base``; dict-valued keys keep only differing entries."""
    out: dict = {}
    for k, v in game_kb.items():
        b = base.get(k)
        if v == b:
            continue
        out[k] = {e: x for e, x in v.items() if not (isinstance(b, dict) and b.get(e) == x)} \
            if isinstance(v, dict) and isinstance(b, dict) else copy.deepcopy(v)
    return out


def read(base: dict, overlay: dict | None) -> dict:
    """``base`` with the overlay applied (overlay entries replace base entries)."""
    out = copy.deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(copy.deepcopy(v))
        else:
            out[k] = copy.deepcopy(v)
    return out


def overlay_dir(base_path: str | Path, game_key: str) -> Path:
    return Path(base_path).parent / "overlay" / game_key


def write_overlay(base_path: str | Path, game_key: str, base: dict, game_kb: dict) -> dict:
    """Write ``overlay/<game_key>/rom_tables.json`` and ``disagreements.json`` next to the base kb file
    (the base file itself is never touched). Returns the overlay."""
    o = build_overlay(base, game_kb)
    d = overlay_dir(base_path, game_key)
    d.mkdir(parents=True, exist_ok=True)
    (d / "rom_tables.json").write_text(json.dumps(o, indent=1, sort_keys=True), encoding="utf-8")
    summary = {k: (len(v) if isinstance(v, dict) else 1) for k, v in o.items()}
    (d / "disagreements.json").write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    return o
