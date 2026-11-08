"""The preset registry: genre rows, game rows, resolve precedence and unknown fallback."""
from dataclasses import fields, replace

from pokeagent.mapview.presets import DEFAULT_GENRE, GAMES, GENRES, resolve


def test_resolve_returns_each_genre_row():
    for g in ("platformer", "rpg-overworld", "flip-screen"):
        p = resolve(genre=g)
        assert p.name == g and p.genre == g


def test_games_inherit_their_genre_with_overrides():
    p = resolve(game="super-mario-land")
    assert p.name == "super-mario-land" and p.genre == "platformer"
    assert p.layout == "strip" and p.avatar == "frame_crop" and p.area_gap_px == 8
    assert p.status_fields == ("segment", "screen.box_text")
    q = resolve(game="pokemon-red")
    assert q.name == "pokemon-red" and q.genre == "rpg-overworld"
    assert q.avatar == "rom_sprite" and q.walk_frames and q.area_gap_px == 0
    assert q.edge_palette == ()


def test_precedence_preset_game_genre_default():
    assert resolve(game="pokemon-red", preset="flip-screen").name == "flip-screen"
    assert resolve(game="pokemon-red", genre="platformer").genre == "rpg-overworld"
    assert resolve(genre="flip-screen").name == "flip-screen"
    assert resolve().name == DEFAULT_GENRE == "platformer"


def test_unknown_names_fall_back_with_a_question_mark():
    p = resolve(game="nope")
    assert p.name == "nope?" and p.genre == DEFAULT_GENRE
    q = resolve(game="nope", genre="rpg-overworld")
    assert q.name == "nope?" and q.genre == "rpg-overworld"     # closest known genre wins
    r = resolve(preset="nope")
    assert r.name == "nope?" and r.genre == DEFAULT_GENRE
    s = resolve(genre="nope")
    assert s.name == "nope?"


def test_tables_are_plain_data():
    for p in GENRES.values():
        for f in fields(p):
            v = getattr(p, f.name)
            assert isinstance(v, (str, int, bool)) or (
                isinstance(v, tuple) and all(isinstance(x, str) for x in v)), (f.name, v)
    for name, spec in GAMES.items():
        assert isinstance(spec["inherits"], str) and spec["inherits"] in GENRES
        for k, v in spec.items():
            assert isinstance(v, (str, int, bool)) or (
                isinstance(v, tuple) and all(isinstance(x, str) for x in v)), (name, k, v)


def test_resolve_clamps_a_table_gap_typo(monkeypatch):
    for raw, want in ((40, 10), (1, 5), (8, 8)):
        monkeypatch.setitem(GENRES, "platformer", replace(GENRES["platformer"], area_gap_px=raw))
        assert resolve(genre="platformer").area_gap_px == want
