from pathlib import Path

import pytest

from pokeagent.game import registry
from pokeagent.game.spec import LEGACY_FAMILY, GameSpec
from pokeagent.ramlab import games
from pokeagent.ramlab.labels import DATA


def _spec(key, family):
    return GameSpec(key=key, title=key, rom_sha1=("0" * 40,), default_rom=Path(f"roms/{key}.gb"),
                    screen=(160, 144), buttons=("up", "a"), memory_family=family, owns_legacy_paths=False)


def test_red_maps_to_ram_map():
    assert games.map_path_for("pokemon-red") == DATA / "ram_map.json"


def test_same_family_shares_map(monkeypatch):
    monkeypatch.setitem(registry.GAMES, "fake-blue", _spec("fake-blue", LEGACY_FAMILY))
    assert games.map_path_for("fake-blue") == games.map_path_for("pokemon-red")


def test_other_family_needs_own_map(monkeypatch):
    monkeypatch.setitem(registry.GAMES, "fake-green", _spec("fake-green", "other-fam"))
    with pytest.raises(ValueError, match=r"ram_map\.other-fam\.json"):
        games.map_path_for("fake-green")


def test_other_family_map_path_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(games, "DATA", tmp_path)
    (tmp_path / "ram_map.other-fam.json").write_text("[]", encoding="utf-8")
    monkeypatch.setitem(registry.GAMES, "fake-green", _spec("fake-green", "other-fam"))
    assert games.map_path_for("fake-green") == tmp_path / "ram_map.other-fam.json"
