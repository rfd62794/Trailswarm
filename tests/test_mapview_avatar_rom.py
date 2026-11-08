"""rom_sprite avatars: provider errors mean 'no picture'; importing pulls no world code."""
import importlib
import sys

import numpy as np

from pokeagent.mapview.avatar_rom import RomAvatars


def test_get_returns_the_provider_array():
    img = np.zeros((18, 18, 4), np.uint8)
    img[..., 3] = 255
    av = RomAvatars(lambda facing, phase, colour: img)
    assert av.get("a", "DOWN", 0, (1, 2, 3)) is img


def test_get_swallows_lookup_errors():
    for exc in (ValueError, IndexError, KeyError):
        av = RomAvatars(lambda *a, _e=exc: (_ for _ in ()).throw(_e("nope")))
        assert av.get("a", "DOWN", 0, (1, 2, 3)) is None
    av = RomAvatars(lambda *a: None)
    assert av.get("a", "DOWN", 0, (1, 2, 3)) is None


def test_import_does_not_pull_world_draw():
    sys.modules.pop("pokeagent.world.draw", None)
    import pokeagent.mapview.avatar_rom as ar
    importlib.reload(ar)
    assert "pokeagent.world.draw" not in sys.modules
