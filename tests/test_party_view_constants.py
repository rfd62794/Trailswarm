"""Grep guard for the constants migration: one named constant per RAM symbol.

Party/menu/battle-flag addresses live only in ``ram_symbols.py``; wBattleMon field addresses live
only in ``ramstructs.py`` / ``party_view.py`` (everything else must go through ``read_battle_view``).
A duplicate literal or a direct battle-mon read is a regression, not a shortcut.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "pokeagent"

DUP_RE = re.compile(r"0xD163|0xCC26|0xD057|0xCC2F", re.IGNORECASE)
BM_RE = re.compile(r"0xD014|0xD015|0xD016|0xD01C|0xD022|0xD023|0xD024|0xD02D|emu\.read\((0x)?[Dd]01[45]\)",
                   re.IGNORECASE)
SYMBOL_OWNERS = {"ram_symbols.py"}
BATTLE_MON_OWNERS = {"ram_symbols.py", "ramstructs.py", "party_view.py"}


def _sources():
    return sorted(p for p in ROOT.rglob("*.py") if "data" not in p.relative_to(ROOT).parts)


def test_no_duplicate_address_literals():
    for p in _sources():
        if p.name in SYMBOL_OWNERS:
            continue
        hits = [f"{i + 1}:{ln.strip()}" for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines())
                if DUP_RE.search(ln)]
        assert not hits, f"{p.relative_to(ROOT)} re-defines a ram_symbols address: {hits}"


def test_no_battle_mon_literals_outside_the_view():
    for p in _sources():
        if p.name in BATTLE_MON_OWNERS:
            continue
        hits = [f"{i + 1}:{ln.strip()}" for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines())
                if BM_RE.search(ln)]
        assert not hits, f"{p.relative_to(ROOT)} reads wBattleMon directly: {hits}"
