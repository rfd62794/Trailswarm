"""The view preset registry: plain data that says how one game's Map view looks and moves.

A ``Preset`` row holds no behaviour - every value is a str, int, bool or tuple of str - so
the whole table can later be absorbed unchanged into the ``GameSpec`` of the
Multi_Game_Framework plan. ``resolve`` never raises on an unknown name: it falls back to
the closest known genre and marks ``Preset.name`` with ``?`` so the window can say
"unknown preset". This is the only mapview file allowed to name games.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

DEFAULT_GENRE = "platformer"
GAP_MIN, GAP_MAX = 5, 10               # resolve clamps a nonzero area_gap_px into this range
EDGE_PALETTE = ("#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4")


@dataclass(frozen=True)
class Preset:
    name: str
    genre: str                    # "platformer" | "rpg-overworld" | "flip-screen"
    layout: str                   # "strip" rows | "grid"
    avatar: str                   # "frame_crop" | "rom_sprite"
    avatar_size: int              # px at zoom 1
    trail: str                    # "line" | "dots"
    trail_points: int
    follow_default: str           # "live" | "best"
    status_fields: tuple[str, ...]
    walk_frames: bool             # facing + walk phase apply
    area_gap_px: int              # world px between stacked areas; 0 = the layout default
    edge_palette: tuple[str, ...] # hex colours; empty = no edge lines
    world_renderer: str           # "rom-world" | "stitched": which renderer World mode uses


GENRES = {
    "platformer": Preset("platformer", "platformer", "strip", "frame_crop", 16, "line", 90,
                         "live", ("segment",), False, 8, EDGE_PALETTE, "stitched"),
    "rpg-overworld": Preset("rpg-overworld", "rpg-overworld", "grid", "rom_sprite", 18, "dots", 90,
                            "live", ("segment",), True, 0, (), "rom-world"),
    "flip-screen": Preset("flip-screen", "flip-screen", "strip", "frame_crop", 16, "line", 90,
                          "live", ("segment",), False, 0, EDGE_PALETTE, "stitched"),
}

GAMES = {
    "super-mario-land": {"inherits": "platformer", "status_fields": ("segment", "screen.box_text"),
                         "world_renderer": "stitched"},
    "pokemon-red": {"inherits": "rpg-overworld", "world_renderer": "rom-world",
                    "status_fields": ("segment", "screen.party", "screen.money")},
}


def _clamp(p: Preset) -> Preset:
    if p.area_gap_px:
        p = replace(p, area_gap_px=min(GAP_MAX, max(GAP_MIN, p.area_gap_px)))
    return p


def _game(name: str) -> Preset:
    spec = GAMES[name]
    overrides = {k: v for k, v in spec.items() if k != "inherits"}
    return _clamp(replace(GENRES[spec["inherits"]], name=name, **overrides))


def _unknown(requested: str, genre: str | None) -> Preset:
    return _clamp(replace(GENRES.get(genre or "", GENRES[DEFAULT_GENRE]), name=f"{requested}?"))


def resolve(game: str | None = None, preset: str | None = None, genre: str | None = None) -> Preset:
    """Precedence: preset name, then game, then genre, then ``DEFAULT_GENRE``."""
    if preset is not None:
        if preset in GENRES:
            return _clamp(GENRES[preset])
        if preset in GAMES:
            return _game(preset)
        return _unknown(preset, genre)
    if game is not None:
        if game in GAMES:
            return _game(game)
        return _unknown(game, genre)
    if genre is not None:
        return _clamp(GENRES[genre]) if genre in GENRES else _unknown(genre, None)
    return _clamp(GENRES[DEFAULT_GENRE])
