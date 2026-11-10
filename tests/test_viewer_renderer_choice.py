"""Which renderer World mode uses: the preset's world_renderer field, gated on --source."""
from pokeagent.mapview.presets import GAMES, GENRES, resolve
from pokeagent.viewer import modes, renderer_choice
from pokeagent.viewer.layout import FocusState


def test_mode_vocabulary_unchanged():
    assert modes.CHOICES == ("tiles", "world")
    assert FocusState.MODES == ("grid", "world")
    assert modes.label("grid") == "Tiles" and modes.label("world") == "World"
    assert modes.label("focus") == "Focus"
    assert modes.internal("tiles") == "grid" and modes.internal("world") == "world"


def test_world_renderer_field_in_every_row():
    for name, p in GENRES.items():
        assert p.world_renderer in ("rom-world", "stitched"), name
        assert resolve(genre=name).world_renderer == p.world_renderer
    assert GAMES["super-mario-land"]["world_renderer"] == "stitched"
    assert GAMES["pokemon-red"]["world_renderer"] == "rom-world"
    assert resolve(game="super-mario-land").world_renderer == "stitched"
    assert resolve(game="pokemon-red").world_renderer == "rom-world"


def test_no_source_is_always_rom_world():
    for name in list(GENRES) + list(GAMES) + [None, "nope"]:
        assert renderer_choice.choose(name, None) == "rom-world", name
        p = resolve(preset=name) if name else None
        assert renderer_choice.choose(p, None) == "rom-world", name


def test_source_uses_the_preset_renderer():
    src = "runs/x"
    for name in ("pokemon-red", "rpg-overworld"):
        assert renderer_choice.choose(name, src) == "rom-world"
        assert renderer_choice.choose(resolve(preset=name), src) == "rom-world"
    for name in ("super-mario-land", "platformer", "flip-screen"):
        assert renderer_choice.choose(name, src) == "stitched"
        assert renderer_choice.choose(resolve(preset=name), src) == "stitched"


def test_unknown_preset_falls_back_without_raising():
    assert renderer_choice.choose("nope", "runs/x") == "stitched"          # unknown -> default genre row
    p = resolve(preset="nope", genre="rpg-overworld")
    assert renderer_choice.choose(p, "runs/x") == "rom-world"              # unknown -> closest genre row
