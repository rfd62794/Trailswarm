"""Interior label text and column layout (pure): tidy names that never overlap their neighbours."""
from __future__ import annotations

import re

_SMALL = {"of", "the", "and", "in", "to"}
_ALIAS = {"POKECENTER": "Pokecenter", "POKEMON": "Pokemon", "MT": "Mt.", "SS": "S.S."}


def tidy_name(raw: str) -> str:
    """``0x3E CERULEAN_TRASHED_HOUSE`` / ``CERULEAN_POKECENTER`` -> ``Cerulean Trashed House`` / ``Cerulean Pokecenter``."""
    s = re.sub(r"^0x[0-9a-fA-F]+\s*", "", raw.strip())
    words = [w for w in re.split(r"[_\s]+", s) if w]
    out = [_ALIAS.get(w.upper(), w.capitalize()) for w in words]
    return " ".join(w.lower() if i and w.lower() in _SMALL else w for i, w in enumerate(out))


def label_for(raw: str, width_px: float, char_px: float = 6.0) -> str:
    """The tidy name cut to the column (``width_px``) with a trailing '..' when it does not fit: neighbours never overlap."""
    text, cap = tidy_name(raw), max(3, int(width_px // char_px))
    return text if len(text) <= cap else text[:cap - 2].rstrip() + ".."


def column_px(w_cells: int, cell: int = 16, gap: int = 2) -> int:
    """A label's column: its inset's width plus the gap up to the next inset (laid out in rows by ``build_layout``), less a margin."""
    return (w_cells + gap) * cell - 4
