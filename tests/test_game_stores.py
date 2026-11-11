"""store_path: the family/game namespacing of runs/ and kb/ stores. Red's paths are byte-identical."""
from pathlib import Path

import pytest

from pokeagent.game import RED
from pokeagent.game.spec import LEGACY_FAMILY, GameSpec
from pokeagent.game.stores import store_path


def _spec(key, family, owns) -> GameSpec:
    return GameSpec(
        key=key, title=key, rom_sha1=("A" * 40,), default_rom=Path("roms/x.gb"),
        screen=(2, 2), buttons=("a",), memory_family=family, owns_legacy_paths=owns,
    )


# test-sibling shares Red's memory family but does not own the legacy paths (stands in for Blue);
# test-game is a game outside the family, so its key is its family.
SIBLING = _spec("test-sibling", LEGACY_FAMILY, False)
OWN = _spec("test-game", "test-game", False)

FAMILY_STORES = ["runs/maps.json", "runs/bandit.json", "runs/novelty.json",
                 "kb/items.json", "kb/rom_tables.json"]


@pytest.mark.parametrize("rel", FAMILY_STORES)
def test_red_family_scope_is_unchanged(rel, tmp_path):
    assert store_path(rel, RED) == Path(rel)
    assert store_path(rel, RED, root=tmp_path) == tmp_path / rel


def test_red_game_scope_is_unchanged(tmp_path):
    assert store_path("runs/checkpoints", RED, scope="game") == Path("runs/checkpoints")
    assert store_path("runs/checkpoints", RED, root=tmp_path, scope="game") == tmp_path / "runs/checkpoints"


@pytest.mark.parametrize("rel", FAMILY_STORES)
def test_sibling_family_scope_shares_reds_paths(rel):
    assert store_path(rel, SIBLING) == Path(rel) == store_path(rel, RED)


def test_sibling_game_scope_is_namespaced_by_key():
    assert store_path("runs/checkpoints", SIBLING, scope="game") == Path("runs/test-sibling/checkpoints")
    assert store_path("runs/checkpoints/team_best.level", SIBLING, scope="game") \
        == Path("runs/test-sibling/checkpoints/team_best.level")


def test_own_family_game_scopes_both_namespaced():
    assert store_path("runs/maps.json", OWN) == Path("runs/test-game/maps.json")
    assert store_path("kb/items.json", OWN) == Path("kb/test-game/items.json")
    assert store_path("runs/checkpoints", OWN, scope="game") == Path("runs/test-game/checkpoints")


def test_rel_accepts_path_objects_and_backslashes():
    assert store_path(Path("runs") / "checkpoints", OWN, scope="game") == Path("runs/test-game/checkpoints")
    assert store_path("runs\\checkpoints", OWN, scope="game") == Path("runs/test-game/checkpoints")
    assert store_path("kb\\items.json", OWN) == Path("kb/test-game/items.json")


def test_non_namespaced_root_rejected():
    for rel in ("baselines/x.state", "roms/x.gb", "world/maps.json", "x/maps.json"):
        with pytest.raises(ValueError):
            store_path(rel, RED)


def test_unknown_scope_rejected():
    with pytest.raises(ValueError):
        store_path("runs/maps.json", RED, scope="bogus")


def test_default_game_honours_pokeagent_game(monkeypatch):
    monkeypatch.delenv("POKEAGENT_GAME", raising=False)
    assert store_path("runs/maps.json") == Path("runs/maps.json")
    assert store_path("runs/checkpoints", scope="game") == Path("runs/checkpoints")
    monkeypatch.setenv("POKEAGENT_GAME", "pokemon-red")
    assert store_path("runs/maps.json") == Path("runs/maps.json")


def test_unknown_env_fails_like_resolve_game(monkeypatch):
    from pokeagent.game import UnknownGame
    monkeypatch.setenv("POKEAGENT_GAME", "nope")
    with pytest.raises(UnknownGame):
        store_path("runs/maps.json")


def test_store_path_creates_nothing(tmp_path):
    store_path("runs/maps.json", OWN, root=tmp_path)
    assert not (tmp_path / "runs").exists()
